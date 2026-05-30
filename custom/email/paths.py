"""
Container-independent state directory resolver.

The email feature runs in TWO containers that share the `hermes-home` volume:
  - webui  : HERMES_WEBUI_STATE_DIR=/home/hermeswebui/.hermes/webui
  - agent  : HERMES_HOME=/home/hermes/.hermes  → /home/hermes/.hermes/webui

Both map to the SAME physical volume, so resolving to "<hermes home>/webui" in
each container points at the SAME emails.db / email_accounts.json / .email_key.

We do NOT import `api.config` here because that module only exists in the webui
container — importing it in the agent process raises ModuleNotFoundError and
breaks every email tool.
"""
import os
from pathlib import Path


def state_dir() -> Path:
    # 1. Explicit webui state dir (set in the webui container)
    p = os.getenv("HERMES_WEBUI_STATE_DIR")
    if p:
        return Path(p)
    # 2. Agent / generic: <HERMES_HOME>/webui (shared volume)
    home = os.getenv("HERMES_HOME")
    if home:
        return Path(home) / "webui"
    # 3. Last resort
    return Path.home() / ".hermes" / "webui"
