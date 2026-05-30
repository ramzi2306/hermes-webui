"""Email plugin — registers email tools with Hermes agent."""

from .schemas import SCHEMAS
from . import tools as _tools


def register(ctx):
    """Called by Hermes at startup to register all email tools."""

    handler_map = {
        "email_list_accounts": _tools.email_list_accounts,
        "email_fetch_inbox": _tools.email_fetch_inbox,
        "email_send": _tools.email_send,
        "email_draft_reply": _tools.email_draft_reply,
    }

    for schema in SCHEMAS:
        handler = handler_map.get(schema["name"])
        if handler:
            ctx.register_tool(schema["name"], schema, handler)
