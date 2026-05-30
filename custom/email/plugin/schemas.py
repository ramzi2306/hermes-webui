"""Tool schemas — what the LLM sees when calling email tools."""

SCHEMAS = [
    {
        "name": "email_list_accounts",
        "description": "List Ramzi's configured email accounts.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "email_fetch_inbox",
        "description": "Fetch emails from Ramzi's inbox via Himalaya. Returns threads with subject, sender, body, date.",
        "parameters": {
            "type": "object",
            "properties": {
                "account_email": {"type": "string", "description": "Email account (e.g. contact@ramzi.digital)"},
                "folder": {"type": "string", "description": "Folder. Default: INBOX", "default": "INBOX"},
                "limit": {"type": "integer", "description": "Max emails. Default: 50", "default": 50},
            },
            "required": ["account_email"],
        },
    },
    {
        "name": "email_send",
        "description": "Send an email on behalf of Ramzi after approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "account_email": {"type": "string"},
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "reply_to_id": {"type": "string", "description": "Message-ID to reply to"},
            },
            "required": ["account_email", "to", "subject", "body"],
        },
    },
    {
        "name": "email_draft_reply",
        "description": "Generate a draft reply for an email using AI.",
        "parameters": {
            "type": "object",
            "properties": {
                "email_subject": {"type": "string"},
                "from_name": {"type": "string"},
                "from_email": {"type": "string"},
                "email_body": {"type": "string"},
                "instruction": {"type": "string", "default": ""},
            },
            "required": ["email_subject", "from_name", "from_email", "email_body"],
        },
    },
    # ── UI Control Tools ──────────────────────────────────────────────────────
    {
        "name": "email_show_card",
        "description": "Push an approval card to Ramzi's WebUI dashboard. Call this after drafting a reply. Ramzi will see the card and approve/reject.",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string", "description": "Unique thread identifier"},
                "from_name": {"type": "string"},
                "from_email": {"type": "string"},
                "subject": {"type": "string"},
                "ai_summary": {"type": "string", "description": "Your 1-2 sentence summary of the email"},
                "draft": {"type": "string", "description": "Your drafted reply"},
                "urgency": {"type": "string", "enum": ["urgent", "normal", "low"], "default": "normal"},
            },
            "required": ["thread_id", "from_name", "from_email", "subject", "ai_summary", "draft"],
        },
    },
    {
        "name": "email_update_queue",
        "description": "Update the full queue displayed in Ramzi's WebUI. Call after triage to show all pending items.",
        "parameters": {
            "type": "object",
            "properties": {
                "threads": {
                    "type": "array",
                    "description": "List of thread objects with id, subject, from_name, urgency, ai_summary",
                    "items": {"type": "object"},
                }
            },
            "required": ["threads"],
        },
    },
    {
        "name": "email_notify",
        "description": "Push a notification to Ramzi's WebUI.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "urgency": {"type": "string", "enum": ["urgent", "normal", "low"], "default": "normal"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "email_await_approval",
        "description": "Wait for Ramzi to approve or reject the draft in the WebUI. Returns his decision. Always call this after email_show_card.",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string"},
                "timeout": {"type": "number", "description": "Max wait time in seconds. Default: 86400 (24h)", "default": 86400},
            },
            "required": ["thread_id"],
        },
    },
    {
        "name": "email_update_draft",
        "description": "Update the draft shown in WebUI after Ramzi gives redirect instructions.",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string"},
                "new_draft": {"type": "string"},
            },
            "required": ["thread_id", "new_draft"],
        },
    },
    {
        "name": "email_mark_done",
        "description": "Mark a thread as done in the WebUI queue.",
        "parameters": {
            "type": "object",
            "properties": {
                "thread_id": {"type": "string"},
                "action": {"type": "string", "enum": ["approved", "rejected", "archived"], "default": "approved"},
            },
            "required": ["thread_id"],
        },
    },
]


# ── Management API tool schemas ───────────────────────────────────────────────
_S = lambda **p: {"type": "object", "properties": p}
SCHEMAS += [
    {"name": "email_preprocess", "description": "Group all stored emails for an account into threads (idempotent). Run once after syncing.",
     "parameters": _S(account={"type": "string"}), "required": ["account"]},
    {"name": "email_list_threads", "description": "List all threads for an account with their emails (id, type incoming/outgoing, from, subject, date, body), drafts, in current order.",
     "parameters": _S(account={"type": "string"}), "required": ["account"]},
    {"name": "email_get_original", "description": "Get the ORIGINAL (immutable) content of an email by id — even if it has been reworked.",
     "parameters": _S(email_id={"type": "integer"}), "required": ["email_id"]},
    {"name": "email_rework", "description": "Replace the DISPLAYED content of an email with a cleaned/summarized version. The original is preserved; the UI shows a 'reworked' badge. Use to make messy/long emails readable.",
     "parameters": _S(email_id={"type": "integer"}, text={"type": "string", "description": "The reworked/summarized body to display"}), "required": ["email_id", "text"]},
    {"name": "email_restore", "description": "Revert a reworked email back to its original content.",
     "parameters": _S(email_id={"type": "integer"}), "required": ["email_id"]},
    {"name": "email_rename_thread", "description": "Set a clear AI-chosen title for a thread.",
     "parameters": _S(thread_id={"type": "string"}, title={"type": "string"}), "required": ["thread_id", "title"]},
    {"name": "email_reorder_threads", "description": "Set the top-to-bottom order of threads. Pass thread_ids in desired order (most important first).",
     "parameters": _S(account={"type": "string"}, order={"type": "array", "items": {"type": "string"}}), "required": ["account", "order"]},
    {"name": "email_move_email", "description": "Move an email into a thread at a position (regroup conversations).",
     "parameters": _S(email_id={"type": "integer"}, thread_id={"type": "string"}, position={"type": "integer", "default": 0}), "required": ["email_id", "thread_id"]},
    {"name": "email_reorder_emails", "description": "Set the order of emails within a thread. Pass email ids in desired order.",
     "parameters": _S(thread_id={"type": "string"}, order={"type": "array", "items": {"type": "integer"}}), "required": ["thread_id", "order"]},
    {"name": "email_create_thread", "description": "Create a new empty thread with a title.",
     "parameters": _S(account={"type": "string"}, title={"type": "string"}, position={"type": "integer", "default": 0}), "required": ["account", "title"]},
    {"name": "email_save_draft", "description": "Save an UNSENT draft reply attached to a thread. Shown dotted in the UI. Does NOT send.",
     "parameters": _S(account={"type": "string"}, thread_id={"type": "string"}, body={"type": "string"}, to={"type": "string"}, subject={"type": "string"}, draft_id={"type": "string", "description": "Pass to update an existing draft"}), "required": ["account", "thread_id", "body"]},
    {"name": "email_delete_draft", "description": "Delete a draft.",
     "parameters": _S(draft_id={"type": "string"}), "required": ["draft_id"]},
]
