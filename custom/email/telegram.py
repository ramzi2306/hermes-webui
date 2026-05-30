"""
Telegram integration for the email manager.
- Sends mailbox summaries to Ramzi's Telegram.
- Token + chat_id are stored in email_settings.json (set via WebUI settings).
No external deps — uses the Telegram Bot HTTP API via urllib.
"""
import json
import os
import urllib.request
import urllib.parse


def _settings() -> dict:
    from custom.email.handler import _email_settings
    return _email_settings()


def _tg_config() -> tuple:
    s = _settings()
    return s.get("telegram_bot_token", ""), s.get("telegram_chat_id", "")


def is_configured() -> bool:
    token, chat_id = _tg_config()
    return bool(token and chat_id)


def send_message(text: str, parse_mode: str = "HTML", reply_markup: dict = None) -> dict:
    """Send a message to the configured Telegram chat."""
    token, chat_id = _tg_config()
    if not token or not chat_id:
        return {"error": "Telegram not configured (set bot token + chat id in Email settings)"}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text[:4000], "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    data = urllib.parse.urlencode(payload).encode()
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read().decode("utf-8"))
            return {"ok": res.get("ok", False), "result": res.get("result", {})}
    except Exception as e:
        return {"error": str(e)}


def send_summary(account: str) -> dict:
    """Build and send a mailbox summary grouped by urgency."""
    from custom.email import api as eapi
    threads = eapi.list_threads(account)
    if not threads:
        return send_message("📭 <b>Mailbox</b>\nNo threads yet — run a sync.")

    urgent, normal, low = [], [], []
    for t in threads:
        last = t["emails"][-1] if t["emails"] else {}
        line = f"• <b>{_esc(t['title'])}</b> — {_esc((t.get('participants') or [''])[0])}"
        # urgency heuristic from position bucket (agent controls order)
        if t["position"] < 3:
            urgent.append(line)
        elif t["position"] < 10:
            normal.append(line)
        else:
            low.append(line)

    parts = [f"📬 <b>Mailbox summary</b> — {len(threads)} threads\n"]
    if urgent:
        parts.append("🔴 <b>Top priority</b>\n" + "\n".join(urgent[:8]))
    if normal:
        parts.append("\n🟡 <b>Normal</b>\n" + "\n".join(normal[:8]))
    if low:
        parts.append(f"\n⚪ <b>Low / newsletters</b>: {len(low)}")
    pending_drafts = sum(len(t.get("drafts", [])) for t in threads)
    if pending_drafts:
        parts.append(f"\n📝 <b>{pending_drafts} draft(s)</b> waiting for approval in the WebUI.")
    return send_message("\n".join(parts))


def _esc(s: str) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
