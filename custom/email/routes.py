"""
Email Routes — custom extension for Hermes WebUI
All email API endpoints isolated here for easy upstream merges
"""
import json
import time


def register_get(parsed, handler, j, bad):
    """Handle GET /api/email/* routes. Returns True if handled."""

    # ── SSE stream — browser subscribes for live agent updates ───────────────
    if parsed.path == "/api/email/events":
        try:
            from custom.email.ui_server import subscribe_to_events, unsubscribe
            import queue as _queue

            q = subscribe_to_events()
            handler.send_response(200)
            handler.send_header("Content-Type", "text/event-stream")
            handler.send_header("Cache-Control", "no-cache")
            handler.send_header("Connection", "keep-alive")
            handler.send_header("Access-Control-Allow-Origin", "*")
            handler.end_headers()

            # Send current state immediately on connect
            from custom.email.ui_server import email_get_state
            state = email_get_state()
            data = json.dumps({"type": "state_sync", "data": state}).encode()
            handler.wfile.write(f"data: {data.decode()}\n\n".encode())
            handler.wfile.flush()

            # Stream events until client disconnects
            try:
                while True:
                    try:
                        payload = q.get(timeout=25)
                        handler.wfile.write(f"data: {payload}\n\n".encode())
                        handler.wfile.flush()
                    except _queue.Empty:
                        # Heartbeat
                        handler.wfile.write(b": ping\n\n")
                        handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                unsubscribe(q)
            return True
        except Exception as e:
            return bad(handler, str(e), status=500)

    # ── Get full state (for page refresh) ────────────────────────────────────
    if parsed.path == "/api/email/state":
        try:
            from custom.email.ui_server import email_get_state
            return j(handler, email_get_state())
        except Exception as e:
            return bad(handler, str(e), status=500)

    if parsed.path == "/api/email/accounts":
        try:
            from custom.email.handler import load_email_accounts
            accounts = load_email_accounts()
            safe = [{k: v for k, v in a.items() if k != "password"} for a in accounts]
            return j(handler, {"accounts": safe})
        except Exception as e:
            return bad(handler, str(e), status=500)

    # ── Management API: threads (GET) ─────────────────────────────────────────
    if parsed.path == "/api/email/threads":
        try:
            from urllib.parse import parse_qs
            from custom.email import api as eapi
            q = parse_qs(parsed.query or "")
            account = (q.get("account") or [""])[0]
            return j(handler, {"threads": eapi.list_threads(account)})
        except Exception as e:
            return bad(handler, str(e), status=500)

    if parsed.path == "/api/email/original":
        try:
            from urllib.parse import parse_qs
            from custom.email import api as eapi
            q = parse_qs(parsed.query or "")
            eid = int((q.get("id") or ["0"])[0])
            return j(handler, eapi.get_original(eid))
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
        # Read from local store (instant). Does NOT hit IMAP — use /sync for that.
        try:
            from custom.email.handler import get_stored_emails, get_last_sync
            acct = body.get("account_email")
            emails = get_stored_emails(acct, int(body.get("limit", 200)))
            return j(handler, {"emails": emails, "last_sync": get_last_sync(acct)})
        except Exception as e:
            return bad(handler, str(e), status=500)

    if parsed.path == "/api/email/sync":
        # Trigger incremental IMAP sync (INBOX + Sent) into local store.
        try:
            from custom.email.handler import sync_inbox, get_stored_emails, get_last_sync
            acct = body.get("account_email")
            result = sync_inbox(acct, body.get("max_per_folder"))
            return j(handler, {
                "sync": result,
                "emails": get_stored_emails(acct, int(body.get("limit", 200))),
                "last_sync": get_last_sync(acct),
            })
        except Exception as e:
            return bad(handler, str(e), status=500)

    if parsed.path == "/api/email/send":
        try:
            from custom.email.handler import send_email, get_account_decrypted
            account = get_account_decrypted(body.get("account_email"))
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

    # ── Right-column agent chat ───────────────────────────────────────────────
    if parsed.path == "/api/email/chat":
        try:
            from custom.email.handler import agent_chat
            reply = agent_chat(
                thread=body.get("thread", []),
                history=body.get("history", []),
                message=body.get("message", ""),
                profile=body.get("profile"),
                scope=body.get("scope", "thread"),
            )
            return j(handler, {"reply": reply})
        except Exception as e:
            return bad(handler, str(e), status=500)

    if parsed.path == "/api/email/summarize":
        try:
            from custom.email.handler import summarize_thread
            summary = summarize_thread(body.get("thread", []), body.get("profile"))
            return j(handler, {"summary": summary})
        except Exception as e:
            return bad(handler, str(e), status=500)

    if parsed.path == "/api/email/settings":
        try:
            from custom.email.handler import _email_settings, _save_email_settings
            if body.get("save"):
                _save_email_settings(body.get("settings", {}))
                return j(handler, {"ok": True})
            return j(handler, _email_settings())
        except Exception as e:
            return bad(handler, str(e), status=500)

    # ── Management API (POST) — the agent + UI drive these ────────────────────
    if parsed.path.startswith("/api/email/mgmt/"):
        try:
            from custom.email import api as eapi
            action = parsed.path[len("/api/email/mgmt/"):]
            if action == "preprocess":
                return j(handler, eapi.preprocess(body.get("account", "")))
            if action == "rework":
                return j(handler, eapi.rework_email(int(body["email_id"]), body.get("text", "")))
            if action == "restore":
                return j(handler, eapi.restore_email(int(body["email_id"])))
            if action == "rename-thread":
                return j(handler, eapi.rename_thread(body["thread_id"], body.get("title", "")))
            if action == "reorder-threads":
                return j(handler, eapi.reorder_threads(body.get("account", ""), body.get("order", [])))
            if action == "set-thread-position":
                return j(handler, eapi.set_thread_position(body["thread_id"], int(body.get("position", 0))))
            if action == "move-email":
                return j(handler, eapi.move_email(int(body["email_id"]), body["thread_id"], int(body.get("position", 0))))
            if action == "reorder-emails":
                return j(handler, eapi.reorder_emails(body["thread_id"], body.get("order", [])))
            if action == "create-thread":
                return j(handler, eapi.create_thread(body.get("account", ""), body.get("title", "New thread"), int(body.get("position", 0))))
            if action == "save-draft":
                return j(handler, eapi.save_draft(body.get("account", ""), body.get("thread_id", ""), body.get("body", ""), body.get("to", ""), body.get("subject", ""), body.get("draft_id")))
            if action == "delete-draft":
                return j(handler, eapi.delete_draft(body["draft_id"]))
            return bad(handler, f"unknown mgmt action: {action}", status=404)
        except KeyError as e:
            return bad(handler, f"missing field: {e}", status=400)
        except Exception as e:
            return bad(handler, str(e), status=500)

    # ── Approval endpoints (Ramzi clicks Approve/Reject in browser) ───────────
    if parsed.path == "/api/email/approve":
        try:
            from custom.email.ui_server import resolve_approval, email_mark_done
            thread_id = body.get("thread_id", "")
            resolve_approval(thread_id, "approved")
            email_mark_done(thread_id, "approved")
            return j(handler, {"ok": True})
        except Exception as e:
            return bad(handler, str(e), status=500)

    if parsed.path == "/api/email/reject":
        try:
            from custom.email.ui_server import resolve_approval, email_mark_done
            thread_id = body.get("thread_id", "")
            instruction = body.get("instruction", "")
            resolve_approval(thread_id, "rejected", instruction)
            email_mark_done(thread_id, "rejected")
            return j(handler, {"ok": True})
        except Exception as e:
            return bad(handler, str(e), status=500)

    if parsed.path == "/api/email/redirect":
        """Ramzi gives agent new instruction — agent rewrites draft."""
        try:
            from custom.email.ui_server import resolve_approval
            thread_id = body.get("thread_id", "")
            instruction = body.get("instruction", "")
            resolve_approval(thread_id, "redirect", instruction)
            return j(handler, {"ok": True})
        except Exception as e:
            return bad(handler, str(e), status=500)

    # ── Agent pushes UI updates via these endpoints ────────────────────────────
    if parsed.path == "/api/email/agent/show-card":
        try:
            from custom.email.ui_server import email_show_card
            return j(handler, email_show_card(**body))
        except Exception as e:
            return bad(handler, str(e), status=500)

    if parsed.path == "/api/email/agent/update-queue":
        try:
            from custom.email.ui_server import email_update_queue
            return j(handler, email_update_queue(body.get("threads", [])))
        except Exception as e:
            return bad(handler, str(e), status=500)

    if parsed.path == "/api/email/agent/notify":
        try:
            from custom.email.ui_server import email_notify
            return j(handler, email_notify(body.get("message", ""), body.get("urgency", "normal")))
        except Exception as e:
            return bad(handler, str(e), status=500)

    if parsed.path == "/api/email/agent/update-draft":
        try:
            from custom.email.ui_server import email_update_draft
            return j(handler, email_update_draft(body.get("thread_id", ""), body.get("draft", "")))
        except Exception as e:
            return bad(handler, str(e), status=500)

    return False
