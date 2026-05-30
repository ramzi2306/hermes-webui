"""
Email Management API — data model the Hermes agent fully controls.

Design:
  - Every email has: id, type (incoming/outgoing), metadata (from, subject, date…),
    an IMMUTABLE original body, and a mutable WORKING body (AI reworks here).
  - Threads are ordered arrays of emails. Each thread has an AI-controllable
    title and a position (sort order). Emails have a position within a thread.
  - Drafts are unsent reply bodies attached to a thread.
  - The agent reads originals, reworks (summarizes/cleans) into working copies,
    renames threads, reorders threads/emails, and saves drafts — without sending.

All state lives in the same SQLite DB as store.py (STATE_DIR/emails.db).
"""
import json
import time
import threading
import uuid

from custom.email import store

_lock = store._db_lock


def _conn():
    return store._conn()


def init():
    """Create the management tables (idempotent) and add rework columns."""
    store.init_db()
    with _lock, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS threads (
            thread_id TEXT PRIMARY KEY,
            account   TEXT NOT NULL,
            title     TEXT,
            position  INTEGER DEFAULT 0,
            created_at REAL,
            updated_at REAL
        );
        CREATE TABLE IF NOT EXISTS thread_emails (
            thread_id TEXT NOT NULL,
            email_pk  INTEGER NOT NULL,
            position  INTEGER DEFAULT 0,
            UNIQUE(thread_id, email_pk)
        );
        CREATE TABLE IF NOT EXISTS drafts (
            draft_id   TEXT PRIMARY KEY,
            account    TEXT,
            thread_id  TEXT,
            to_addr    TEXT,
            subject    TEXT,
            body       TEXT,
            created_at REAL,
            updated_at REAL
        );
        """)
        # Add rework columns to emails if missing
        cols = {r["name"] for r in c.execute("PRAGMA table_info(emails)").fetchall()}
        if "working_text" not in cols:
            c.execute("ALTER TABLE emails ADD COLUMN working_text TEXT")
        if "is_reworked" not in cols:
            c.execute("ALTER TABLE emails ADD COLUMN is_reworked INTEGER DEFAULT 0")


# ── Preprocess: build threads from raw emails ─────────────────────────────────

def preprocess(account: str) -> dict:
    """
    Group all stored emails for an account into threads (by thread_key),
    assigning positions. Idempotent — keeps existing thread titles/positions
    when re-run, only adds new emails.
    """
    init()
    emails = store.get_emails(account, limit=1000)
    # group by thread_key
    groups = {}
    for e in emails:
        key = e.get("thread_key") or e["subject"] or e["id"]
        groups.setdefault(key, []).append(e)

    created, added = 0, 0
    with _lock, _conn() as c:
        # existing thread positions
        existing = {r["thread_id"]: r for r in c.execute(
            "SELECT * FROM threads WHERE account=?", (account,)).fetchall()}
        next_pos = (max([r["position"] for r in existing.values()], default=-1) + 1)

        for key, items in groups.items():
            items.sort(key=lambda x: x.get("timestamp") or 0)
            tid = "th_" + uuid.uuid5(uuid.NAMESPACE_URL, account + "|" + key).hex[:12]
            if tid not in existing:
                title = items[-1]["subject"] or "(no subject)"
                c.execute("INSERT OR IGNORE INTO threads(thread_id,account,title,position,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                          (tid, account, title, next_pos, time.time(), time.time()))
                next_pos += 1
                created += 1
            # map emails → thread with position
            for pos, e in enumerate(items):
                pk = _email_pk(c, account, e["folder"], e["uid"])
                if pk is None:
                    continue
                cur = c.execute("SELECT 1 FROM thread_emails WHERE thread_id=? AND email_pk=?", (tid, pk)).fetchone()
                if not cur:
                    c.execute("INSERT OR IGNORE INTO thread_emails(thread_id,email_pk,position) VALUES(?,?,?)", (tid, pk, pos))
                    added += 1
    return {"threads_created": created, "emails_added": added}


def _email_pk(c, account, folder, uid):
    r = c.execute("SELECT pk FROM emails WHERE account=? AND folder=? AND uid=?",
                  (account, folder, str(uid))).fetchone()
    return r["pk"] if r else None


# ── Read ──────────────────────────────────────────────────────────────────────

def list_threads(account: str) -> list:
    """Return threads (ordered by position) with their emails (ordered) + drafts."""
    init()
    with _lock, _conn() as c:
        threads = c.execute("SELECT * FROM threads WHERE account=? ORDER BY position ASC, updated_at DESC", (account,)).fetchall()
        out = []
        for t in threads:
            rows = c.execute("""
                SELECT e.*, te.position AS thread_pos
                FROM thread_emails te JOIN emails e ON e.pk = te.email_pk
                WHERE te.thread_id=? ORDER BY te.position ASC, e.timestamp ASC
            """, (t["thread_id"],)).fetchall()
            emails = [_email_dto(r) for r in rows]
            drafts = [dict(d) for d in c.execute("SELECT * FROM drafts WHERE thread_id=? ORDER BY updated_at", (t["thread_id"],)).fetchall()]
            last_ts = max([e["timestamp"] for e in emails], default=0)
            out.append({
                "thread_id": t["thread_id"],
                "title": t["title"],
                "position": t["position"],
                "last_ts": last_ts,
                "emails": emails,
                "drafts": drafts,
                "participants": list({(e["from_name"] or e["from_email"]) for e in emails if e["type"] == "incoming"}),
            })
    return out


def _email_dto(r) -> dict:
    reworked = bool(r["is_reworked"]) and (r["working_text"] or "").strip() != ""
    display = r["working_text"] if reworked else r["body_text"]
    return {
        "id": r["pk"],
        "type": "outgoing" if r["direction"] == "sent" else "incoming",
        "from_name": r["from_name"],
        "from_email": r["from_email"],
        "to": r["to_addr"],
        "subject": r["subject"],
        "date": r["date_str"],
        "timestamp": r["timestamp"],
        "message_id": r["message_id"],
        "body": display,
        "body_html": None if reworked else r["body_html"],  # reworked shows clean text
        "is_reworked": reworked,
        "has_attachments": bool(r["has_attachments"]),
        "thread_pos": r["thread_pos"] if "thread_pos" in r.keys() else 0,
    }


def get_original(email_id: int) -> dict:
    init()
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM emails WHERE pk=?", (email_id,)).fetchone()
        if not r:
            return {"error": "not found"}
        return {"id": r["pk"], "subject": r["subject"], "from_name": r["from_name"],
                "from_email": r["from_email"], "date": r["date_str"],
                "body_text": r["body_text"], "body_html": r["body_html"]}


# ── Mutations the agent can perform ───────────────────────────────────────────

def rework_email(email_id: int, text: str) -> dict:
    """Store an AI-reworked (summarized/cleaned) version. Original is preserved."""
    init()
    with _lock, _conn() as c:
        c.execute("UPDATE emails SET working_text=?, is_reworked=1 WHERE pk=?", (text, email_id))
    return {"ok": True, "email_id": email_id}


def restore_email(email_id: int) -> dict:
    """Clear the reworked version; revert to showing the original."""
    init()
    with _lock, _conn() as c:
        c.execute("UPDATE emails SET working_text=NULL, is_reworked=0 WHERE pk=?", (email_id,))
    return {"ok": True, "email_id": email_id}


def rename_thread(thread_id: str, title: str) -> dict:
    init()
    with _lock, _conn() as c:
        c.execute("UPDATE threads SET title=?, updated_at=? WHERE thread_id=?", (title, time.time(), thread_id))
    return {"ok": True, "thread_id": thread_id, "title": title}


def reorder_threads(account: str, order: list) -> dict:
    """order = list of thread_ids in the desired top-to-bottom order."""
    init()
    with _lock, _conn() as c:
        for pos, tid in enumerate(order):
            c.execute("UPDATE threads SET position=?, updated_at=? WHERE thread_id=? AND account=?", (pos, time.time(), tid, account))
    return {"ok": True, "count": len(order)}


def set_thread_position(thread_id: str, position: int) -> dict:
    init()
    with _lock, _conn() as c:
        c.execute("UPDATE threads SET position=?, updated_at=? WHERE thread_id=?", (position, time.time(), thread_id))
    return {"ok": True}


def move_email(email_id: int, thread_id: str, position: int = 0) -> dict:
    """Move an email into a thread at a position."""
    init()
    with _lock, _conn() as c:
        c.execute("DELETE FROM thread_emails WHERE email_pk=?", (email_id,))
        c.execute("INSERT OR REPLACE INTO thread_emails(thread_id,email_pk,position) VALUES(?,?,?)", (thread_id, email_id, position))
    return {"ok": True}


def reorder_emails(thread_id: str, order: list) -> dict:
    """order = list of email ids (pk) in desired order within the thread."""
    init()
    with _lock, _conn() as c:
        for pos, eid in enumerate(order):
            c.execute("UPDATE thread_emails SET position=? WHERE thread_id=? AND email_pk=?", (pos, thread_id, eid))
    return {"ok": True}


def create_thread(account: str, title: str, position: int = 0) -> dict:
    init()
    tid = "th_" + uuid.uuid4().hex[:12]
    with _lock, _conn() as c:
        c.execute("INSERT INTO threads(thread_id,account,title,position,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                  (tid, account, title, position, time.time(), time.time()))
    return {"ok": True, "thread_id": tid}


# ── Drafts (unsent) ───────────────────────────────────────────────────────────

def save_draft(account: str, thread_id: str, body: str, to_addr: str = "", subject: str = "", draft_id: str = None) -> dict:
    init()
    did = draft_id or ("dr_" + uuid.uuid4().hex[:12])
    with _lock, _conn() as c:
        c.execute("""INSERT INTO drafts(draft_id,account,thread_id,to_addr,subject,body,created_at,updated_at)
                     VALUES(?,?,?,?,?,?,?,?)
                     ON CONFLICT(draft_id) DO UPDATE SET body=excluded.body, to_addr=excluded.to_addr,
                       subject=excluded.subject, updated_at=excluded.updated_at""",
                  (did, account, thread_id, to_addr, subject, body, time.time(), time.time()))
    return {"ok": True, "draft_id": did}


def delete_draft(draft_id: str) -> dict:
    init()
    with _lock, _conn() as c:
        c.execute("DELETE FROM drafts WHERE draft_id=?", (draft_id,))
    return {"ok": True}


def get_draft(draft_id: str) -> dict:
    init()
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM drafts WHERE draft_id=?", (draft_id,)).fetchone()
        return dict(r) if r else {"error": "not found"}
