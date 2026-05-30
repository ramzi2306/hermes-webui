"""Tool handlers — actual code that runs when Hermes calls an email tool."""

import sys
import os

# Add webui root to path so we can import custom.email.handler
_HERE = os.path.dirname(os.path.abspath(__file__))
_WEBUI_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
if _WEBUI_ROOT not in sys.path:
    sys.path.insert(0, _WEBUI_ROOT)


def email_list_accounts(**kwargs) -> list:
    """List all configured email accounts (without passwords)."""
    from custom.email.handler import load_email_accounts
    accounts = load_email_accounts()
    return [{"email": a["email"], "name": a.get("name", a["email"])} for a in accounts]


def email_fetch_inbox(account_email: str, folder: str = "INBOX", limit: int = 20, **kwargs) -> list:
    """Fetch emails from inbox."""
    from custom.email.handler import load_email_accounts, fetch_emails
    accounts = load_email_accounts()
    account = next((a for a in accounts if a["email"] == account_email), None)
    if not account:
        return [{"error": f"Account '{account_email}' not found. Available: {[a['email'] for a in accounts]}"}]
    try:
        return fetch_emails(account, folder, limit)
    except Exception as e:
        return [{"error": str(e)}]


def email_send(account_email: str, to: str, subject: str, body: str, reply_to_id: str = None, **kwargs) -> dict:
    """Send an email."""
    from custom.email.handler import load_email_accounts, send_email
    accounts = load_email_accounts()
    account = next((a for a in accounts if a["email"] == account_email), None)
    if not account:
        return {"error": f"Account '{account_email}' not found"}
    try:
        send_email(account, to=to, subject=subject, body=body, reply_to_message_id=reply_to_id)
        return {"ok": True, "sent_to": to, "subject": subject}
    except Exception as e:
        return {"error": str(e)}


def email_draft_reply(
    email_subject: str,
    from_name: str,
    from_email: str,
    email_body: str,
    instruction: str = "",
    **kwargs,
) -> str:
    """Generate an AI draft reply."""
    from custom.email.handler import generate_ai_draft
    email_data = {
        "subject": email_subject,
        "from_name": from_name,
        "from_email": from_email,
        "body": email_body,
    }
    return generate_ai_draft(email_data, instruction)
