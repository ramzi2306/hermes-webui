"""Email plugin — registers all email + management + UI tools with Hermes."""
from .schemas import SCHEMAS
from . import tools as _tools


def register(ctx):
    """Called by Hermes at startup. Auto-wires every schema to its handler."""
    for schema in SCHEMAS:
        name = schema["name"]
        handler = getattr(_tools, name, None)
        if handler:
            ctx.register_tool(name, schema, handler)
