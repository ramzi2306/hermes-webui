"""Tool schemas — what the LLM sees when calling email tools."""

SCHEMAS = [
    {
        "name": "email_list_accounts",
        "description": "List Ramzi's configured email accounts.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "email_fetch_inbox",
        "description": "Fetch emails from Ramzi's inbox. Returns list with subject, sender, body, date.",
        "parameters": {
            "type": "object",
            "properties": {
                "account_email": {
                    "type": "string",
                    "description": "Email account to fetch from (e.g. contact@ramzi.digital)",
                },
                "folder": {
                    "type": "string",
                    "description": "Folder to fetch from. Default: INBOX",
                    "default": "INBOX",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of emails to return. Default: 20",
                    "default": 20,
                },
            },
            "required": ["account_email"],
        },
    },
    {
        "name": "email_send",
        "description": "Send an email on behalf of Ramzi.",
        "parameters": {
            "type": "object",
            "properties": {
                "account_email": {
                    "type": "string",
                    "description": "Sender account (e.g. contact@ramzi.digital)",
                },
                "to": {
                    "type": "string",
                    "description": "Recipient email address",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Email body text",
                },
                "reply_to_id": {
                    "type": "string",
                    "description": "Message-ID to reply to (optional)",
                },
            },
            "required": ["account_email", "to", "subject", "body"],
        },
    },
    {
        "name": "email_draft_reply",
        "description": "Generate a draft reply for an email using AI. Returns the draft text.",
        "parameters": {
            "type": "object",
            "properties": {
                "email_subject": {"type": "string", "description": "Subject of the email to reply to"},
                "from_name": {"type": "string", "description": "Sender's name"},
                "from_email": {"type": "string", "description": "Sender's email address"},
                "email_body": {"type": "string", "description": "Body of the email to reply to"},
                "instruction": {
                    "type": "string",
                    "description": "How to reply (e.g. 'decline politely', 'ask for more details')",
                    "default": "",
                },
            },
            "required": ["email_subject", "from_name", "from_email", "email_body"],
        },
    },
]
