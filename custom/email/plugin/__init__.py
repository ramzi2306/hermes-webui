"""Email plugin — registers all email + UI control tools with Hermes."""
from .schemas import SCHEMAS
from . import tools as _tools

_HANDLER_MAP = {
    "email_list_accounts": _tools.email_list_accounts,
    "email_fetch_inbox": _tools.email_fetch_inbox,
    "email_send": _tools.email_send,
    "email_draft_reply": _tools.email_draft_reply,
    "email_show_card": _tools.email_show_card,
    "email_update_queue": _tools.email_update_queue,
    "email_notify": _tools.email_notify,
    "email_await_approval": _tools.email_await_approval,
    "email_update_draft": _tools.email_update_draft,
    "email_mark_done": _tools.email_mark_done,
}


def register(ctx):
    """Called by Hermes at startup."""
    for schema in SCHEMAS:
        handler = _HANDLER_MAP.get(schema["name"])
        if handler:
            ctx.register_tool(schema["name"], schema, handler)
