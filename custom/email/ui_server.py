"""
Email UI Server — Real-time bridge between Hermes Agent and Browser
The agent calls these functions to control what Ramzi sees in the WebUI.
The browser subscribes to SSE stream to receive live updates.
"""

import json
import queue
import time
import threading
from typing import Optional

# ── In-memory state store ─────────────────────────────────────────────────────
_state = {
    "queue": [],        # List of pending approval items
    "done": [],         # Recently completed items
    "active_card": None,  # Currently shown urgent card
    "last_sync": None,
}

_state_lock = threading.Lock()
_event_queues: list[queue.Queue] = []  # One per connected browser tab
_event_queues_lock = threading.Lock()


# ── Event broadcasting ────────────────────────────────────────────────────────

def _broadcast(event_type: str, data: dict):
    """Push an event to all connected browser tabs via SSE."""
    payload = json.dumps({"type": event_type, "data": data, "ts": time.time()})
    with _event_queues_lock:
        dead = []
        for q in _event_queues:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _event_queues.remove(q)


def subscribe_to_events() -> queue.Queue:
    """Browser calls this to get its own SSE queue."""
    q = queue.Queue(maxsize=100)
    with _event_queues_lock:
        _event_queues.append(q)
    return q


def unsubscribe(q: queue.Queue):
    """Browser disconnects."""
    with _event_queues_lock:
        if q in _event_queues:
            _event_queues.remove(q)


# ── Agent tools (called by Hermes) ───────────────────────────────────────────

def email_show_card(
    thread_id: str,
    from_name: str,
    from_email: str,
    subject: str,
    ai_summary: str,
    draft: str,
    urgency: str = "normal",
    raw_emails: Optional[list] = None,
) -> dict:
    """
    Show an approval card in the WebUI.
    Agent calls this when it has a draft ready for Ramzi's approval.
    """
    card = {
        "id": thread_id,
        "from_name": from_name,
        "from_email": from_email,
        "subject": subject,
        "ai_summary": ai_summary,
        "draft": draft,
        "urgency": urgency,
        "emails": raw_emails or [],
        "status": "pending",
        "created_at": time.time(),
    }
    with _state_lock:
        # Add to queue if not already there
        existing = next((i for i in _state["queue"] if i["id"] == thread_id), None)
        if existing:
            existing.update(card)
        else:
            _state["queue"].insert(0 if urgency == "urgent" else len(_state["queue"]), card)
        if urgency == "urgent":
            _state["active_card"] = card

    _broadcast("card_shown", card)
    return {"ok": True, "thread_id": thread_id}


def email_update_queue(threads: list) -> dict:
    """
    Update the full queue display.
    Agent calls this after triage to show all pending items.
    """
    with _state_lock:
        _state["queue"] = threads
        _state["last_sync"] = time.time()
    _broadcast("queue_updated", {"queue": threads, "last_sync": _state["last_sync"]})
    return {"ok": True}


def email_notify(message: str, urgency: str = "normal") -> dict:
    """
    Push a notification to the browser.
    """
    _broadcast("notification", {"message": message, "urgency": urgency, "ts": time.time()})
    return {"ok": True}


def email_mark_done(thread_id: str, action: str = "approved") -> dict:
    """
    Mark a thread as done (approved/rejected).
    Moves it from pending queue to done list.
    """
    with _state_lock:
        item = next((i for i in _state["queue"] if i["id"] == thread_id), None)
        if item:
            item["status"] = action
            item["completed_at"] = time.time()
            _state["queue"] = [i for i in _state["queue"] if i["id"] != thread_id]
            _state["done"].insert(0, item)
            _state["done"] = _state["done"][:50]  # Keep last 50
        if _state.get("active_card", {}) and _state["active_card"].get("id") == thread_id:
            _state["active_card"] = None

    _broadcast("thread_done", {"thread_id": thread_id, "action": action})
    return {"ok": True}


def email_update_draft(thread_id: str, new_draft: str) -> dict:
    """
    Update the draft for a thread (after Ramzi redirects the agent).
    """
    with _state_lock:
        item = next((i for i in _state["queue"] if i["id"] == thread_id), None)
        if item:
            item["draft"] = new_draft
            item["draft_updated_at"] = time.time()

    _broadcast("draft_updated", {"thread_id": thread_id, "draft": new_draft})
    return {"ok": True}


def email_get_state() -> dict:
    """Return full current state (for browser reconnect/refresh)."""
    with _state_lock:
        return {
            "queue": _state["queue"],
            "done": _state["done"][:20],
            "active_card": _state["active_card"],
            "last_sync": _state["last_sync"],
        }


# ── Approval wait mechanism ───────────────────────────────────────────────────

_approval_events: dict[str, threading.Event] = {}
_approval_results: dict[str, dict] = {}


def email_await_approval(thread_id: str, timeout: float = 86400.0) -> dict:
    """
    Block until Ramzi approves or rejects.
    Agent calls this after show_card(), waits for Ramzi's decision.
    Returns: {"action": "approved"|"rejected", "instruction": str}
    """
    event = threading.Event()
    _approval_events[thread_id] = event
    try:
        signaled = event.wait(timeout=timeout)
        if not signaled:
            return {"action": "timeout", "instruction": ""}
        return _approval_results.pop(thread_id, {"action": "timeout", "instruction": ""})
    finally:
        _approval_events.pop(thread_id, None)


def resolve_approval(thread_id: str, action: str, instruction: str = "") -> bool:
    """
    Called when Ramzi clicks Approve/Reject in the browser.
    Unblocks the waiting agent.
    """
    _approval_results[thread_id] = {"action": action, "instruction": instruction}
    event = _approval_events.get(thread_id)
    if event:
        event.set()
        return True
    return False
