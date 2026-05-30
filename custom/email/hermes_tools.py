"""
Hermes Email Tools
Register these with Hermes so the agent can read/send emails directly.

Install:
  Copy this file to ~/.hermes/tools/email_tools.py
  Or add to HERMES_HOME/tools/

Usage by Hermes:
  fetch_inbox(account_email)
  send_email_tool(account_email, to, subject, body)
  draft_reply(email_data, instruction)
"""

import sys
import os

# Add webui root to path so we can import custom.email.handler
WEBUI_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if WEBUI_ROOT not in sys.path:
    sys.path.insert(0, WEBUI_ROOT)


def fetch_inbox(account_email: str, folder: str = "INBOX", limit: int = 20) -> list:
    """
    Fetch emails from inbox.

    Args:
        account_email: The email account to fetch from
        folder: Mail folder (default: INBOX)
        limit: Max number of emails to return

    Returns:
        List of email dicts with keys: id, subject, from_name, from_email, date, body, preview
    """
    from custom.email.handler import load_email_accounts, fetch_emails
    accounts = load_email_accounts()
    account = next((a for a in accounts if a["email"] == account_email), None)
    if not account:
        return [{"error": f"Account {account_email} not found. Run setup first."}]
    return fetch_emails(account, folder, limit)


def send_email_tool(account_email: str, to: str, subject: str, body: str, reply_to_id: str = None) -> dict:
    """
    Send an email.

    Args:
        account_email: The sender account email
        to: Recipient email address
        subject: Email subject
        body: Email body text
        reply_to_id: Optional message ID to reply to

    Returns:
        {"ok": True} on success or {"error": str}
    """
    from custom.email.handler import load_email_accounts, send_email
    accounts = load_email_accounts()
    account = next((a for a in accounts if a["email"] == account_email), None)
    if not account:
        return {"error": f"Account {account_email} not found"}
    try:
        send_email(account, to=to, subject=subject, body=body, reply_to_message_id=reply_to_id)
        return {"ok": True, "sent_to": to, "subject": subject}
    except Exception as e:
        return {"error": str(e)}


def list_accounts() -> list:
    """
    List configured email accounts.

    Returns:
        List of account dicts (without passwords)
    """
    from custom.email.handler import load_email_accounts
    accounts = load_email_accounts()
    return [{"email": a["email"], "name": a.get("name", a["email"])} for a in accounts]


def draft_reply(email_subject: str, from_name: str, from_email: str, email_body: str, instruction: str = "") -> str:
    """
    Generate an AI draft reply for an email.

    Args:
        email_subject: Subject of the email to reply to
        from_name: Sender's name
        from_email: Sender's email
        email_body: Body of the email to reply to
        instruction: Optional instruction (e.g. "decline politely", "ask for more info")

    Returns:
        Draft reply text
    """
    from custom.email.handler import generate_ai_draft
    email_data = {
        "subject": email_subject,
        "from_name": from_name,
        "from_email": from_email,
        "body": email_body,
    }
    return generate_ai_draft(email_data, instruction)


# ── Tool manifest for Hermes ──────────────────────────────────────────────────
HERMES_TOOLS = [
    {
        "name": "fetch_inbox",
        "description": "Fetch emails from Ramzi's inbox. Returns list of emails with subject, sender, body.",
        "function": fetch_inbox,
        "parameters": {
            "account_email": {"type": "string", "description": "Email account to fetch from"},
            "folder": {"type": "string", "description": "Folder name (default: INBOX)", "default": "INBOX"},
            "limit": {"type": "integer", "description": "Max emails to return", "default": 20},
        },
        "required": ["account_email"],
    },
    {
        "name": "send_email",
        "description": "Send an email on behalf of Ramzi.",
        "function": send_email_tool,
        "parameters": {
            "account_email": {"type": "string", "description": "Sender account email"},
            "to": {"type": "string", "description": "Recipient email"},
            "subject": {"type": "string", "description": "Email subject"},
            "body": {"type": "string", "description": "Email body text"},
            "reply_to_id": {"type": "string", "description": "Message ID to reply to (optional)"},
        },
        "required": ["account_email", "to", "subject", "body"],
    },
    {
        "name": "list_email_accounts",
        "description": "List Ramzi's configured email accounts.",
        "function": list_accounts,
        "parameters": {},
        "required": [],
    },
    {
        "name": "draft_email_reply",
        "description": "Generate a draft reply for an email using AI.",
        "function": draft_reply,
        "parameters": {
            "email_subject": {"type": "string"},
            "from_name": {"type": "string"},
            "from_email": {"type": "string"},
            "email_body": {"type": "string"},
            "instruction": {"type": "string", "description": "How to reply (e.g. 'decline politely')", "default": ""},
        },
        "required": ["email_subject", "from_name", "from_email", "email_body"],
    },
]
