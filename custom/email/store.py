"""
Local SQLite email store + incremental IMAP sync.
- Pulls INBOX + Sent folders, stores both text and HTML bodies.
- Incremental: only fetches UIDs newer than last seen per folder.
- Queries read from SQLite (instant, no re-pull on every UI load).
- Junk is the only thing flushed; everything else persists.
"""
import imaplib
import email
import sqlite3
import json
import re
import time
import threading
from email.header import decode_header
from email.utils import parsedate_to_datetime, parseaddr
from pathlib import Path

_db_lock = threading.Lock()

# Common Sent-folder names across providers
_SENT_CANDIDATES = ["Sent", "Sent Items", "INBOX.Sent", "Sent Messages", "[Gmail]/Sent Mail"]


def _db_path() -> Path:
    from api.config import STATE_DIR
    return STATE_DIR / "emails.db"


def _conn():
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(p), timeout=15)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _db_lock, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS emails (
            pk INTEGER PRIMARY KEY AUTOINCREMENT,
            account TEXT NOT NULL,
            folder TEXT NOT NULL,
            uid TEXT NOT NULL,
            message_id TEXT,
            thread_key TEXT,
            subject TEXT,
            from_name TEXT,
            from_email TEXT,
            to_addr TEXT,
            date_str TEXT,
            timestamp REAL,
            body_text TEXT,
            body_html TEXT,
            direction TEXT,
            has_attachments INTEGER DEFAULT 0,
            synced_at REAL,
            UNIQUE(account, folder, uid)
        );
        CREATE TABLE IF NOT EXISTS sync_state (
            account TEXT NOT NULL,
            folder TEXT NOT NULL,
            last_uid INTEGER DEFAULT 0,
            last_sync REAL,
            UNIQUE(account, folder)
        );
        CREATE INDEX IF NOT EXISTS idx_emails_account_ts ON emails(account, timestamp);
        CREATE INDEX IF NOT EXISTS idx_emails_thread ON emails(account, thread_key);
        """)


# ── Header / body parsing ────────────────────────────────────────────────────

def _decode(s) -> str:
    if s is None:
        return ""
    if isinstance(s, bytes):
        return s.decode("utf-8", errors="replace")
    out = []
    for part, enc in decode_header(s):
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(str(part))
    return "".join(out)


def _extract_bodies(msg) -> tuple[str, str, bool]:
    """Return (text, html, has_attachments)."""
    text, html, has_att = "", "", False
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition") or "")
            if "attachment" in cd:
                has_att = True
                continue
            if ct == "text/plain" and not text:
                try:
                    text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    pass
            elif ct == "text/html" and not html:
                try:
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            payload = str(msg.get_payload())
        if msg.get_content_type() == "text/html":
            html = payload
        else:
            text = payload
    # If only html, derive a text preview
    if html and not text:
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
    return text.strip(), html.strip(), has_att


def _normalize_subject(s: str) -> str:
    return re.sub(r"^(re|fwd|fw|aw|tr)\s*:\s*", "", re.sub(r"^(re|fwd|fw|aw|tr)\s*:\s*", "", str(s or ""), flags=re.I), flags=re.I).strip().lower()


def _imap_connect(account: dict):
    host = account["imap_host"]
    port = int(account.get("imap_port", 993))
    if port == 993:
        m = imaplib.IMAP4_SSL(host, port)
    else:
        m = imaplib.IMAP4(host, port)
        m.starttls()
    m.login(account["email"], account["_password_plain"])
    return m


def _find_sent_folder(mail) -> str:
    try:
        typ, folders = mail.list()
        names = []
        for f in folders or []:
            line = f.decode(errors="replace") if isinstance(f, bytes) else str(f)
            # folder name is last quoted segment
            mname = re.search(r'"([^"]+)"\s*$', line) or re.search(r'(\S+)\s*$', line)
            if mname:
                names.append(mname.group(1))
        for cand in _SENT_CANDIDATES:
            for n in names:
                if n.lower() == cand.lower():
                    return n
        # heuristic
        for n in names:
            if "sent" in n.lower():
                return n
    except Exception:
        pass
    return "Sent"


# ── Sync ──────────────────────────────────────────────────────────────────────

def sync_account(account: dict, max_per_folder: int = 60) -> dict:
    """
    Incrementally sync INBOX + Sent for an account into SQLite.
    account must include '_password_plain' (decrypted).
    Returns counts.
    """
    init_db()
    result = {"new": 0, "folders": {}}
    try:
        mail = _imap_connect(account)
    except Exception as e:
        return {"error": f"IMAP connect failed: {e}"}

    sent_folder = _find_sent_folder(mail)
    folders = [("INBOX", "received"), (sent_folder, "sent")]

    for folder, direction in folders:
        try:
            status, _ = mail.select(folder, readonly=True)
            if status != "OK":
                continue
        except Exception:
            continue

        last_uid = _get_last_uid(account["email"], folder)
        # Fetch UIDs greater than last seen
        try:
            typ, data = mail.uid("search", None, f"UID {last_uid + 1}:*")
            uids = data[0].split() if data and data[0] else []
        except Exception:
            uids = []

        # If first sync, limit to most recent N
        if last_uid == 0 and len(uids) > max_per_folder:
            uids = uids[-max_per_folder:]

        new_count = 0
        max_seen = last_uid
        for uid in uids:
            uid_i = int(uid)
            if uid_i <= last_uid:
                continue
            try:
                typ, msg_data = mail.uid("fetch", uid, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                _store_email(account["email"], folder, str(uid_i), msg, direction)
                new_count += 1
                max_seen = max(max_seen, uid_i)
            except Exception:
                continue

        _set_last_uid(account["email"], folder, max_seen)
        result["folders"][folder] = new_count
        result["new"] += new_count

    try:
        mail.logout()
    except Exception:
        pass
    return result


def _store_email(account_email: str, folder: str, uid: str, msg, direction: str):
    from_raw = _decode(msg.get("From", ""))
    from_name, from_email = parseaddr(from_raw)
    to_raw = _decode(msg.get("To", ""))
    subject = _decode(msg.get("Subject", "(no subject)"))
    message_id = _decode(msg.get("Message-ID", uid))
    refs = _decode(msg.get("References", "")) or _decode(msg.get("In-Reply-To", ""))
    thread_key = _normalize_subject(subject) or (from_email if direction == "received" else to_raw) or message_id

    try:
        dt = parsedate_to_datetime(msg.get("Date", ""))
        ts = dt.timestamp()
        date_str = dt.strftime("%b %d, %Y %H:%M")
    except Exception:
        ts = time.time()
        date_str = msg.get("Date", "")

    text, html, has_att = _extract_bodies(msg)

    with _db_lock, _conn() as c:
        c.execute("""
            INSERT OR IGNORE INTO emails
            (account, folder, uid, message_id, thread_key, subject, from_name, from_email,
             to_addr, date_str, timestamp, body_text, body_html, direction, has_attachments, synced_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (account_email, folder, uid, message_id, thread_key, subject,
              from_name or from_email, from_email, to_raw, date_str, ts,
              text, html, direction, 1 if has_att else 0, time.time()))


def _get_last_uid(account_email: str, folder: str) -> int:
    with _db_lock, _conn() as c:
        row = c.execute("SELECT last_uid FROM sync_state WHERE account=? AND folder=?",
                        (account_email, folder)).fetchone()
        return int(row["last_uid"]) if row else 0


def _set_last_uid(account_email: str, folder: str, uid: int):
    with _db_lock, _conn() as c:
        c.execute("""
            INSERT INTO sync_state (account, folder, last_uid, last_sync) VALUES (?,?,?,?)
            ON CONFLICT(account, folder) DO UPDATE SET last_uid=excluded.last_uid, last_sync=excluded.last_sync
        """, (account_email, folder, uid, time.time()))


# ── Query ─────────────────────────────────────────────────────────────────────

def get_emails(account_email: str, limit: int = 200) -> list:
    """Read stored emails (both directions) from SQLite — instant, no IMAP."""
    init_db()
    with _db_lock, _conn() as c:
        rows = c.execute("""
            SELECT * FROM emails WHERE account=? ORDER BY timestamp DESC LIMIT ?
        """, (account_email, limit)).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": f"{r['folder']}:{r['uid']}",
            "uid": r["uid"],
            "folder": r["folder"],
            "message_id": r["message_id"],
            "thread_key": r["thread_key"],
            "subject": r["subject"],
            "from_name": r["from_name"],
            "from_email": r["from_email"],
            "to": r["to_addr"],
            "date": r["date_str"],
            "timestamp": r["timestamp"],
            "body": r["body_text"],
            "body_html": r["body_html"],
            "preview": (r["body_text"] or "")[:140].replace("\n", " "),
            "direction": r["direction"],
            "has_attachments": bool(r["has_attachments"]),
        })
    return out


def get_last_sync(account_email: str) -> float:
    with _db_lock, _conn() as c:
        row = c.execute("SELECT MAX(last_sync) as m FROM sync_state WHERE account=?",
                        (account_email,)).fetchone()
        return float(row["m"]) if row and row["m"] else 0.0


def flush_junk(account_email: str, junk_folder: str = "Junk"):
    """Delete junk emails from local store (the only thing that gets flushed)."""
    with _db_lock, _conn() as c:
        c.execute("DELETE FROM emails WHERE account=? AND folder=?", (account_email, junk_folder))
