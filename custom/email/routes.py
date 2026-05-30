"""
Email Routes — custom extension for Hermes WebUI
All email API endpoints isolated here for easy upstream merges
"""


def register_get(parsed, handler, j, bad):
    """Handle GET /api/email/* routes. Returns True if handled."""
    if parsed.path == "/api/email/accounts":
        try:
            from custom.email.handler import load_email_accounts
            accounts = load_email_accounts()
            safe = [{k: v for k, v in a.items() if k != "password"} for a in accounts]
            return j(handler, {"accounts": safe})
        except Exception as e:
            return bad(handler, str(e), status=500)
    return False


def register_post(parsed, handler, body, j, bad):
    """Handle POST /api/email/* routes. Returns True if handled."""

    if parsed.path == "/api/email/accounts":
        try:
            from custom.email.handler import save_email_accounts
            save_email_accounts(body.get("accounts", []))
            return j(handler, {"ok": True})
        except Exception as e:
            return bad(handler, str(e), status=500)

    if parsed.path == "/api/email/fetch":
        try:
            from custom.email.handler import fetch_emails, load_email_accounts
            accounts = load_email_accounts()
            account = next((a for a in accounts if a["email"] == body.get("account_email")), None)
            if not account:
                return bad(handler, "Account not found", status=404)
            emails = fetch_emails(account, body.get("folder", "INBOX"), int(body.get("limit", 30)))
            return j(handler, {"emails": emails})
        except Exception as e:
            return bad(handler, str(e), status=500)

    if parsed.path == "/api/email/send":
        try:
            from custom.email.handler import send_email, load_email_accounts
            accounts = load_email_accounts()
            account = next((a for a in accounts if a["email"] == body.get("account_email")), None)
            if not account:
                return bad(handler, "Account not found", status=404)
            send_email(
                account,
                to=body.get("to", ""),
                subject=body.get("subject", ""),
                body=body.get("body", ""),
                reply_to_message_id=body.get("reply_to_message_id"),
            )
            return j(handler, {"ok": True})
        except Exception as e:
            return bad(handler, str(e), status=500)

    if parsed.path == "/api/email/draft":
        try:
            from custom.email.handler import generate_ai_draft
            draft = generate_ai_draft(body.get("email", {}), body.get("instruction", ""))
            return j(handler, {"draft": draft})
        except Exception as e:
            return bad(handler, str(e), status=500)

    return False
