"""
Telegram delivery for the email manager — uses the EXISTING Hermes gateway bot
(the one already configured via `hermes setup gateway`). No separate bot token.

Messages are sent with the `hermes send` CLI, which routes through the
configured gateway/platform. This runs inside the agent container where the
gateway + hermes CLI live.
"""
import subprocess


def is_configured() -> bool:
    # The gateway owns Telegram config; assume available. Errors surface on send.
    return True


def _hermes_send(text: str) -> dict:
    """Send a message via the configured Hermes gateway (Telegram)."""
    attempts = [
        ["hermes", "send", "--platform", "telegram", text],
        ["hermes", "send", "telegram", text],
        ["hermes", "send", "--telegram", text],
        ["hermes", "send", text],
    ]
    last = ""
    for cmd in attempts:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                return {"ok": True}
            last = (r.stderr or r.stdout or "").strip()
        except FileNotFoundError:
            last = "hermes CLI not found (run from the agent container)"
            break
        except Exception as e:
            last = str(e)
    return {"error": last or "hermes send failed"}


def send_message(text: str, **_) -> dict:
    return _hermes_send(text)


def send_summary(account: str) -> dict:
    """Build a mailbox summary grouped by urgency and send via the gateway."""
    from custom.email import api as eapi
    threads = eapi.list_threads(account)
    if not threads:
        return _hermes_send("📭 Mailbox: no threads yet — run a sync.")

    urgent, normal, low = [], [], []
    for t in threads:
        line = f"• {t['title']} — {(t.get('participants') or [''])[0]}"
        if t["position"] < 3:
            urgent.append(line)
        elif t["position"] < 10:
            normal.append(line)
        else:
            low.append(line)

    parts = [f"📬 Mailbox summary — {len(threads)} threads"]
    if urgent:
        parts.append("\n🔴 Top priority\n" + "\n".join(urgent[:8]))
    if normal:
        parts.append("\n🟡 Normal\n" + "\n".join(normal[:8]))
    if low:
        parts.append(f"\n⚪ Low / newsletters: {len(low)}")
    pending = sum(len(t.get("drafts", [])) for t in threads)
    if pending:
        parts.append(f"\n📝 {pending} draft(s) waiting for approval in the WebUI.")
    return _hermes_send("\n".join(parts))
