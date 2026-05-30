"""
Email Handler for Hermes WebUI
Handles IMAP (receive) + SMTP (send) + AI draft generation
"""

import imaplib
import smtplib
import email
import email.mime.text
import email.mime.multipart
import json
import os
import re
import time
import threading
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime, parseaddr
from pathlib import Path
from typing import Optional


def _get_email_config_path() -> Path:
    from api.config import STATE_DIR
    return STATE_DIR / "email_accounts.json"


def load_email_accounts() -> list:
    path = _get_email_config_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_email_accounts(accounts: list) -> None:
    path = _get_email_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(accounts, indent=2), encoding="utf-8")


def decode_str(s) -> str:
    if s is None:
        return ""
    if isinstance(s, bytes):
        return s.decode("utf-8", errors="replace")
    parts = decode_header(s)
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(str(part))
    return "".join(result)


def get_email_body(msg) -> str:
    """Extract plain text body from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition") or "")
            if ct == "text/plain" and "attachment" not in cd:
                try:
                    charset = part.get_content_charset() or "utf-8"
                    body = part.get_payload(decode=True).decode(charset, errors="replace")
                    break
                except Exception:
                    pass
        if not body:
            for part in msg.walk():
                ct = part.get_content_type()
                cd = str(part.get("Content-Disposition") or "")
                if ct == "text/html" and "attachment" not in cd:
                    try:
                        charset = part.get_content_charset() or "utf-8"
                        html = part.get_payload(decode=True).decode(charset, errors="replace")
                        body = re.sub(r"<[^>]+>", " ", html).strip()
                        body = re.sub(r"\s+", " ", body)
                        break
                    except Exception:
                        pass
    else:
        try:
            charset = msg.get_content_charset() or "utf-8"
            body = msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            body = str(msg.get_payload())
    return body.strip()


def fetch_emails(account: dict, folder: str = "INBOX", limit: int = 30) -> list:
    """Fetch emails from IMAP server."""
    imap_host = account.get("imap_host", "")
    imap_port = int(account.get("imap_port", 993))
    username = account.get("email", "")
    password = account.get("password", "")

    if not all([imap_host, username, password]):
        raise ValueError("Missing IMAP configuration")

    emails = []
    try:
        if imap_port == 993:
            mail = imaplib.IMAP4_SSL(imap_host, imap_port)
        else:
            mail = imaplib.IMAP4(imap_host, imap_port)
            mail.starttls()

        mail.login(username, password)
        mail.select(folder)

        _, data = mail.search(None, "ALL")
        ids = data[0].split()
        ids = ids[-limit:] if len(ids) > limit else ids
        ids = list(reversed(ids))

        for uid in ids:
            try:
                _, msg_data = mail.fetch(uid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                from_raw = decode_str(msg.get("From", ""))
                from_name, from_email = parseaddr(from_raw)
                from_name = from_name or from_email

                date_str = msg.get("Date", "")
                try:
                    dt = parsedate_to_datetime(date_str)
                    timestamp = dt.timestamp()
                    date_formatted = dt.strftime("%b %d, %Y %H:%M")
                except Exception:
                    timestamp = time.time()
                    date_formatted = date_str

                thread_id = decode_str(msg.get("Thread-Index", "")) or \
                            decode_str(msg.get("References", "")).split()[-1] if msg.get("References") else ""
                message_id = decode_str(msg.get("Message-ID", uid.decode()))
                subject = decode_str(msg.get("Subject", "(no subject)"))
                body = get_email_body(msg)

                emails.append({
                    "id": uid.decode(),
                    "message_id": message_id,
                    "thread_id": thread_id or message_id,
                    "subject": subject,
                    "from_name": from_name,
                    "from_email": from_email,
                    "to": decode_str(msg.get("To", "")),
                    "date": date_formatted,
                    "timestamp": timestamp,
                    "body": body,
                    "preview": body[:150].replace("\n", " ") if body else "",
                    "read": False,
                    "folder": folder,
                    "account_email": username,
                })
            except Exception:
                continue

        mail.logout()
    except Exception as e:
        raise RuntimeError(f"IMAP error: {e}")

    return emails


def send_email(account: dict, to: str, subject: str, body: str, reply_to_message_id: str = None) -> bool:
    """Send email via SMTP."""
    smtp_host = account.get("smtp_host", "")
    smtp_port = int(account.get("smtp_port", 587))
    username = account.get("email", "")
    password = account.get("password", "")
    display_name = account.get("name", username)

    if not all([smtp_host, username, password]):
        raise ValueError("Missing SMTP configuration")

    msg = email.mime.multipart.MIMEMultipart()
    msg["From"] = f"{display_name} <{username}>"
    msg["To"] = to
    msg["Subject"] = subject

    if reply_to_message_id:
        msg["In-Reply-To"] = reply_to_message_id
        msg["References"] = reply_to_message_id

    msg.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))

    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                server.login(username, password)
                server.sendmail(username, to, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(username, password)
                server.sendmail(username, to, msg.as_string())
        return True
    except Exception as e:
        raise RuntimeError(f"SMTP error: {e}")


def _email_settings() -> dict:
    """Load email settings (profile choice, etc.) from state dir."""
    path = STATE_DIR / "email_settings.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"profile": "collab-manager"}


def _save_email_settings(settings: dict) -> None:
    path = STATE_DIR / "email_settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def _profile_home(profile: str) -> Optional[str]:
    """Resolve HERMES_HOME for a named profile, or None for default."""
    if not profile or profile == "default":
        return None
    base = os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))
    base_path = Path(base)
    # If HERMES_HOME already points into profiles/, walk up to base
    if base_path.name and base_path.parent.name == "profiles":
        base_path = base_path.parent.parent
    candidate = base_path / "profiles" / profile
    return str(candidate) if candidate.exists() else None


def _run_hermes(prompt: str, profile: str = None, timeout: int = 60) -> str:
    """Run hermes one-shot with optional profile, return stdout."""
    import subprocess
    import sys

    env = dict(os.environ)
    profile = profile or _email_settings().get("profile", "collab-manager")
    phome = _profile_home(profile)
    if phome:
        env["HERMES_HOME"] = phome

    result = subprocess.run(
        [sys.executable, "-m", "hermes", "-q", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(Path.home()),
        env=env,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return ""


def _format_thread(thread: list) -> str:
    """Format a list of emails into a readable thread context."""
    lines = []
    for em in thread[:15]:
        who = em.get("from_name") or em.get("from_email") or "Unknown"
        date = em.get("date", "")
        body = (em.get("body", "") or "")[:1500]
        lines.append(f"--- From: {who} ({date}) ---\n{body}")
    return "\n\n".join(lines)


def generate_ai_draft(email_data: dict, user_instruction: str = "") -> str:
    """Generate AI draft reply using Hermes agent."""
    subject = email_data.get("subject", "")
    from_name = email_data.get("from_name", "")
    from_email = email_data.get("from_email", "")
    body = email_data.get("body", "")[:2000]

    prompt = f"""You are drafting a professional email reply on behalf of Ramzi.

Original email:
From: {from_name} <{from_email}>
Subject: {subject}
Body:
{body}

{"User instruction: " + user_instruction if user_instruction else "Write a professional, concise reply."}

Write ONLY the email body text. No subject line, no 'Subject:', just the reply body. Be professional and concise in Ramzi's voice: direct, warm, gets to the point."""

    try:
        out = _run_hermes(prompt, timeout=60)
        if out:
            return out
    except Exception:
        pass
    return f"Hi {from_name},\n\nThank you for your email.\n\nBest regards,\nRamzi"


def agent_chat(thread: list, history: list, message: str, profile: str = None) -> str:
    """
    Right-column agent chat. Ramzi talks to the email agent about a thread.
    thread = list of emails in the conversation
    history = prior chat turns [{role, text}]
    message = new user message
    """
    thread_ctx = _format_thread(thread) if thread else "(no email selected)"

    hist_lines = []
    for turn in history[-8:]:
        role = "Ramzi" if turn.get("role") == "user" else "You"
        hist_lines.append(f"{role}: {turn.get('text', '')}")
    hist_ctx = "\n".join(hist_lines) if hist_lines else "(start of conversation)"

    prompt = f"""You are Ramzi's email assistant managing his inbox. You are looking at this email thread:

{thread_ctx}

Conversation so far:
{hist_ctx}

Ramzi: {message}

Respond helpfully. You can: summarize the thread, explain context, draft a reply, suggest actions. If Ramzi asks you to draft a reply, write the draft clearly marked. Keep responses concise and in Ramzi's direct, warm voice."""

    try:
        out = _run_hermes(prompt, profile=profile, timeout=90)
        if out:
            return out
    except Exception as e:
        return f"(Agent error: {e})"
    return "(No response from agent — check that Hermes is running.)"


def summarize_thread(thread: list, profile: str = None) -> str:
    """Summarize a thread into a clean readable summary."""
    prompt = f"""Summarize this email thread concisely for Ramzi. Capture the key points, what's being asked, and any action needed.

{_format_thread(thread)}

Write a clear 2-4 sentence summary."""
    try:
        return _run_hermes(prompt, profile=profile, timeout=60) or "(Could not summarize)"
    except Exception as e:
        return f"(Summary error: {e})"
