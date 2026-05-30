"""Tool handlers — code that runs when Hermes calls an email tool."""
import sys, os, tempfile, subprocess, json as _json

_HERE = os.path.dirname(os.path.abspath(__file__))
_WEBUI_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
if _WEBUI_ROOT not in sys.path:
    sys.path.insert(0, _WEBUI_ROOT)


# ── Dynamic Himalaya config generator ────────────────────────────────────────

def _build_himalaya_config(account: dict) -> str:
    """Generate Himalaya TOML config dynamically from stored account data."""
    name = account.get("email", "").split("@")[0]
    return f"""
[accounts.{name}]
default = true
email = "{account['email']}"
display-name = "{account.get('name', 'Ramzi')}"

backend.type = "imap"
backend.host = "{account['imap_host']}"
backend.port = {account.get('imap_port', 993)}
backend.encryption.type = "tls"
backend.auth.type = "password"
backend.auth.raw = "{account['password']}"

message.send.backend.type = "smtp"
message.send.backend.host = "{account['smtp_host']}"
message.send.backend.port = {account.get('smtp_port', 587)}
message.send.backend.encryption.type = "start-tls"
message.send.backend.auth.type = "password"
message.send.backend.auth.raw = "{account['password']}"
""".strip()


def _run_himalaya(account: dict, args: list) -> tuple[bool, str]:
    """Run himalaya with a dynamically generated config for this account."""
    config_content = _build_himalaya_config(account)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
        f.write(config_content)
        config_path = f.name
    try:
        result = subprocess.run(
            ["himalaya", "--config", config_path] + args,
            capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0, result.stdout if result.returncode == 0 else result.stderr
    except FileNotFoundError:
        return False, "himalaya not installed"
    except Exception as e:
        return False, str(e)
    finally:
        os.unlink(config_path)


# ── Account tools ─────────────────────────────────────────────────────────────

def email_list_accounts(**_) -> list:
    from custom.email.handler import load_email_accounts
    return [{"email": a["email"], "name": a.get("name", a["email"])} for a in load_email_accounts()]


def email_fetch_inbox(account_email: str, folder: str = "INBOX", limit: int = 50, **_) -> list:
    """Sync inbox+sent into local store, then return stored emails (both directions)."""
    from custom.email.handler import sync_inbox, get_stored_emails
    sync = sync_inbox(account_email)
    if isinstance(sync, dict) and sync.get("error"):
        return [{"error": sync["error"]}]
    return get_stored_emails(account_email, limit)


def email_send(account_email: str, to: str, subject: str, body: str, reply_to_id: str = None, **_) -> dict:
    from custom.email.handler import get_account_decrypted, send_email
    account = get_account_decrypted(account_email)
    if not account:
        return {"error": f"Account '{account_email}' not found. Add it in WebUI Email Settings."}
    try:
        send_email(account, to=to, subject=subject, body=body, reply_to_message_id=reply_to_id)
        return {"ok": True, "sent_to": to, "subject": subject}
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


# ── Management API tools (organize/rework/draft) ──────────────────────────────

def email_preprocess(account: str, **_) -> dict:
    from custom.email import api as eapi
    return eapi.preprocess(account)

def email_list_threads(account: str, **_) -> list:
    from custom.email import api as eapi
    return eapi.list_threads(account)

def email_get_original(email_id: int, **_) -> dict:
    from custom.email import api as eapi
    return eapi.get_original(int(email_id))

def email_rework(email_id: int, text: str, **_) -> dict:
    from custom.email import api as eapi
    return eapi.rework_email(int(email_id), text)

def email_restore(email_id: int, **_) -> dict:
    from custom.email import api as eapi
    return eapi.restore_email(int(email_id))

def email_rename_thread(thread_id: str, title: str, **_) -> dict:
    from custom.email import api as eapi
    return eapi.rename_thread(thread_id, title)

def email_reorder_threads(account: str, order: list, **_) -> dict:
    from custom.email import api as eapi
    return eapi.reorder_threads(account, order)

def email_move_email(email_id: int, thread_id: str, position: int = 0, **_) -> dict:
    from custom.email import api as eapi
    return eapi.move_email(int(email_id), thread_id, int(position))

def email_reorder_emails(thread_id: str, order: list, **_) -> dict:
    from custom.email import api as eapi
    return eapi.reorder_emails(thread_id, order)

def email_create_thread(account: str, title: str, position: int = 0, **_) -> dict:
    from custom.email import api as eapi
    return eapi.create_thread(account, title, int(position))

def email_save_draft(account: str, thread_id: str, body: str, to: str = "", subject: str = "", draft_id: str = None, **_) -> dict:
    from custom.email import api as eapi
    return eapi.save_draft(account, thread_id, body, to, subject, draft_id)

def email_delete_draft(draft_id: str, **_) -> dict:
    from custom.email import api as eapi
    return eapi.delete_draft(draft_id)


# ── Telegram tools ────────────────────────────────────────────────────────────

def email_telegram_summary(account: str, **_) -> dict:
    """Send Ramzi a mailbox summary (grouped by urgency) on Telegram."""
    from custom.email import telegram
    return telegram.send_summary(account)

def email_telegram_message(text: str, **_) -> dict:
    """Send Ramzi a custom message on Telegram."""
    from custom.email import telegram
    return telegram.send_message(text)
