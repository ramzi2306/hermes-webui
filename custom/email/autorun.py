"""
Autonomous email pass — safe to trigger from cron or manually.

run_pass() does the DETERMINISTIC work (no LLM needed):
  1. sync new mail (INBOX + Sent)
  2. preprocess into threads
  3. send a Telegram summary grouped by urgency

The INTELLIGENT work (triage, rework noisy emails, draft replies) is done by the
Hermes agent itself — schedule a Hermes cron that prompts the agent with the
email-manager workflow (see custom/email/API.md). The agent then calls the
email_* tools (including email_telegram_summary) on its own.
"""


def run_pass(account: str) -> dict:
    from custom.email.handler import sync_inbox, load_email_accounts
    from custom.email import api as eapi, telegram

    if not account:
        accts = load_email_accounts()
        if not accts:
            return {"error": "no account configured"}
        account = accts[0]["email"]

    result = {"account": account}

    sync = sync_inbox(account)
    result["sync"] = sync

    pre = eapi.preprocess(account)
    result["preprocess"] = pre

    if telegram.is_configured():
        result["telegram"] = telegram.send_summary(account)
    else:
        result["telegram"] = {"skipped": "not configured"}

    return result
