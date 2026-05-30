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
    from custom.email.paths import state_dir
    return state_dir() / "email_accounts.json"


def load_email_accounts() -> list:
    """Load accounts. Passwords remain ENCRYPTED in the returned dicts."""
    path = _get_email_config_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_email_accounts(accounts: list) -> None:
    """Save accounts, ENCRYPTING any plaintext passwords at rest."""
    from custom.email.crypto import encrypt
    safe = []
    for a in accounts:
        a = dict(a)
        if a.get("password"):
            a["password"] = encrypt(a["password"])  # idempotent if already encrypted
        safe.append(a)
    path = _get_email_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe, indent=2), encoding="utf-8")
    try:
        import os, stat
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except Exception:
        pass


def get_account_decrypted(account_email: str) -> Optional[dict]:
    """Return an account dict with a decrypted '_password_plain' field for connecting."""
    from custom.email.crypto import decrypt
    for a in load_email_accounts():
        if a["email"] == account_email:
            a = dict(a)
            a["_password_plain"] = decrypt(a.get("password", ""))
            # also keep 'password' as plain for legacy callers (handler fetch/send)
            a["password"] = a["_password_plain"]
            return a
    return None


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
    """Load email settings (profile choice, import limits) from state dir."""
    from custom.email.paths import state_dir
    defaults = {"profile": "collab-manager", "import_count": 60, "import_days": 0}
    path = state_dir() / "email_settings.json"
    if path.exists():
        try:
            return {**defaults, **json.loads(path.read_text(encoding="utf-8"))}
        except Exception:
            pass
    return defaults


def sync_inbox(account_email: str, max_per_folder: int = None) -> dict:
    """Incrementally sync INBOX + Sent into local SQLite store."""
    from custom.email import store
    acct = get_account_decrypted(account_email)
    if not acct:
        return {"error": f"Account '{account_email}' not found"}
    if max_per_folder is None:
        max_per_folder = int(_email_settings().get("import_count", 60))
    return store.sync_account(acct, max_per_folder=max_per_folder)


def get_stored_emails(account_email: str, limit: int = 200) -> list:
    """Read emails from local store (instant, no IMAP)."""
    from custom.email import store
    return store.get_emails(account_email, limit)


def get_last_sync(account_email: str) -> float:
    from custom.email import store
    return store.get_last_sync(account_email)


def _save_email_settings(settings: dict) -> None:
    from custom.email.paths import state_dir
    path = state_dir() / "email_settings.json"
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


def _run_hermes(prompt: str, profile: str = None, timeout: int = 90,
                system_message: str = "You are Ramzi's email assistant.") -> str:
    """
    Ask the agent a one-shot question using the webui's IN-PROCESS AIAgent
    (the same path the main webui chat uses — guaranteed to work in-container).
    On failure, returns a diagnostic string prefixed with ⚠️ so it's visible.
    """
    errors = []

    # ── Primary: in-process AIAgent.run_conversation ──
    try:
        import uuid
        from api.config import (
            get_effective_default_model,
            resolve_model_provider,
            resolve_custom_provider_connection,
        )
        from run_agent import AIAgent

        model, provider, base_url = resolve_model_provider(get_effective_default_model())
        api_key = None
        try:
            from api.oauth import resolve_runtime_provider_with_anthropic_env_lock
            from hermes_cli.runtime_provider import resolve_runtime_provider
            rt = resolve_runtime_provider_with_anthropic_env_lock(
                resolve_runtime_provider, requested=provider)
            api_key = rt.get("api_key")
            if not provider:
                provider = rt.get("provider")
            if not base_url:
                base_url = rt.get("base_url")
        except Exception as e:
            errors.append(f"runtime-provider: {e}")
        if isinstance(provider, str) and provider.startswith("custom:"):
            ck, cb = resolve_custom_provider_connection(provider)
            api_key = api_key or ck
            base_url = base_url or cb

        agent = AIAgent(
            model=model, provider=provider, base_url=base_url, api_key=api_key,
            platform="webui", quiet_mode=True, enabled_toolsets=[],
            session_id=f"email-{uuid.uuid4().hex[:8]}",
        )
        result = agent.run_conversation(
            user_message=prompt,
            system_message=system_message,
            conversation_history=[],
            task_id=f"email-{uuid.uuid4().hex[:8]}",
        )
        out = str(result.get("final_response") or "").strip()
        if out:
            return out
        errors.append("in-process agent returned empty")
    except Exception as e:
        errors.append(f"in-process AIAgent: {e}")

    # ── Fallback: HTTP gateway ──
    base = os.getenv("HERMES_AGENT_URL", "http://hermes-agent:8642").rstrip("/")
    try:
        import urllib.request
        payload = json.dumps({
            "model": os.getenv("HERMES_EMAIL_MODEL", "deepseek-v4-pro"),
            "messages": [{"role": "system", "content": system_message},
                         {"role": "user", "content": prompt}],
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            base + "/v1/chat/completions", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
            choices = data.get("choices") or []
            if choices:
                msg = choices[0].get("message", {}).get("content", "")
                if msg.strip():
                    return msg.strip()
        errors.append("HTTP gateway returned no content")
    except Exception as e:
        errors.append(f"HTTP gateway: {e}")

    return "⚠️ Agent unavailable. " + " | ".join(errors[:3])


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


def agent_chat(thread: list, history: list, message: str, profile: str = None, scope: str = "thread") -> str:
    """
    Right-column agent chat.
    scope='thread' → context is the open thread's emails.
    scope='global' → context is a digest of the whole mailbox.
    """
    hist_lines = []
    for turn in history[-8:]:
        role = "Ramzi" if turn.get("role") == "user" else "You"
        hist_lines.append(f"{role}: {turn.get('text', '')}")
    hist_ctx = "\n".join(hist_lines) if hist_lines else "(start of conversation)"

    if scope == "global":
        items = []
        for t in (thread or [])[:30]:
            items.append(f"• {t.get('subject','')} — from {t.get('from_name','')} ({t.get('date','')}): {(t.get('body','') or '')[:200]}")
        ctx = "\n".join(items) if items else "(mailbox empty)"
        prompt = f"""You are Ramzi's email manager. Here is a digest of his current mailbox:

{ctx}

Conversation so far:
{hist_ctx}

Ramzi: {message}

Answer about his mailbox: identify urgent items, who needs replies, summarize, prioritize. Concise, in Ramzi's direct warm voice."""
    else:
        thread_ctx = _format_thread(thread) if thread else "(no email selected)"
        prompt = f"""You are Ramzi's email assistant. You are looking at this email thread:

{thread_ctx}

Conversation so far:
{hist_ctx}

Ramzi: {message}

Respond helpfully: summarize, explain context, draft a reply, suggest actions. If asked to draft, write the draft clearly. Concise, in Ramzi's direct warm voice."""

    return _run_hermes(prompt, profile=profile, timeout=120)


def summarize_thread(thread: list, profile: str = None) -> str:
    """Summarize a thread into a clean readable summary."""
    prompt = f"""Summarize this email thread concisely for Ramzi. Capture the key points, what's being asked, and any action needed.

{_format_thread(thread)}

Write a clear 2-4 sentence summary."""
    try:
        return _run_hermes(prompt, profile=profile, timeout=60) or "(Could not summarize)"
    except Exception as e:
        return f"(Summary error: {e})"
