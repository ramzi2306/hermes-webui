"""Tool handlers — code that runs when Hermes calls an email tool."""
import sys, os

_HERE = os.path.dirname(os.path.abspath(__file__))
_WEBUI_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
if _WEBUI_ROOT not in sys.path:
    sys.path.insert(0, _WEBUI_ROOT)


# ── Himalaya wrapper ──────────────────────────────────────────────────────────

def email_list_accounts(**_) -> list:
    from custom.email.handler import load_email_accounts
    return [{"email": a["email"], "name": a.get("name", a["email"])} for a in load_email_accounts()]


def email_fetch_inbox(account_email: str, folder: str = "INBOX", limit: int = 50, **_) -> list:
    """Fetch emails — tries Himalaya first, falls back to IMAP handler."""
    import subprocess, json as _json
    try:
        result = subprocess.run(
            ["himalaya", "--account", account_email.split("@")[0],
             "envelope", "list", "--folder", folder,
             "--page-size", str(limit), "--output", "json"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return _json.loads(result.stdout)
    except Exception:
        pass
    # Fallback to direct IMAP
    from custom.email.handler import load_email_accounts, fetch_emails
    accounts = load_email_accounts()
    account = next((a for a in accounts if a["email"] == account_email), None)
    if not account:
        return [{"error": f"Account {account_email} not found"}]
    return fetch_emails(account, folder, limit)


def email_send(account_email: str, to: str, subject: str, body: str, reply_to_id: str = None, **_) -> dict:
    from custom.email.handler import load_email_accounts, send_email
    accounts = load_email_accounts()
    account = next((a for a in accounts if a["email"] == account_email), None)
    if not account:
        return {"error": f"Account {account_email} not found"}
    try:
        send_email(account, to=to, subject=subject, body=body, reply_to_message_id=reply_to_id)
        return {"ok": True, "sent_to": to}
    except Exception as e:
        return {"error": str(e)}


def email_draft_reply(email_subject: str, from_name: str, from_email: str, email_body: str, instruction: str = "", **_) -> str:
    from custom.email.handler import generate_ai_draft
    return generate_ai_draft(
        {"subject": email_subject, "from_name": from_name, "from_email": from_email, "body": email_body},
        instruction
    )


# ── UI Control Tools ──────────────────────────────────────────────────────────

def email_show_card(thread_id: str, from_name: str, from_email: str, subject: str,
                    ai_summary: str, draft: str, urgency: str = "normal", **_) -> dict:
    from custom.email.ui_server import email_show_card as _show
    return _show(thread_id=thread_id, from_name=from_name, from_email=from_email,
                 subject=subject, ai_summary=ai_summary, draft=draft, urgency=urgency)


def email_update_queue(threads: list, **_) -> dict:
    from custom.email.ui_server import email_update_queue as _upd
    return _upd(threads)


def email_notify(message: str, urgency: str = "normal", **_) -> dict:
    from custom.email.ui_server import email_notify as _notify
    return _notify(message, urgency)


def email_await_approval(thread_id: str, timeout: float = 86400.0, **_) -> dict:
    from custom.email.ui_server import email_await_approval as _await
    return _await(thread_id, timeout)


def email_update_draft(thread_id: str, new_draft: str, **_) -> dict:
    from custom.email.ui_server import email_update_draft as _upd
    return _upd(thread_id, new_draft)


def email_mark_done(thread_id: str, action: str = "approved", **_) -> dict:
    from custom.email.ui_server import email_mark_done as _done
    return _done(thread_id, action)
