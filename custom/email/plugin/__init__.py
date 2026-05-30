"""Email plugin — registers all email + management + UI tools with Hermes.

Runs inside the AGENT container. The `custom` package is bundled into
<HERMES_HOME>/custom by install_plugins.py; ensure that dir is importable.
"""
import os
import sys


def _ensure_custom_on_path():
    candidates = []
    home = os.getenv("HERMES_HOME")
    if home:
        candidates.append(home)                       # <home>/custom/email
        candidates.append(os.path.dirname(home))      # in case home is a profile
    candidates.append(os.path.expanduser("~/.hermes"))
    # Also walk up from this file: plugins/email/__init__.py → look for ../../custom
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.dirname(os.path.dirname(here)))  # <base> when at <base>/plugins/email
    for base in candidates:
        if base and os.path.isdir(os.path.join(base, "custom", "email")) and base not in sys.path:
            sys.path.insert(0, base)
            return base
    return None


_ensure_custom_on_path()

from .schemas import SCHEMAS  # noqa: E402
from . import tools as _tools  # noqa: E402


def register(ctx):
    """Called by Hermes at startup. Auto-wires every schema to its handler."""
    for schema in SCHEMAS:
        name = schema["name"]
        handler = getattr(_tools, name, None)
        if handler:
            ctx.register_tool(name, schema, handler)
