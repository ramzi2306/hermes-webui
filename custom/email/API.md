# Email Management API

A local API + agent toolset for organizing Ramzi's mailbox. State lives in
SQLite (`STATE_DIR/emails.db`). The Hermes agent drives it via tools; the WebUI
renders the result.

## Data model

### email
| field | meaning |
|-------|---------|
| `id` | integer primary key |
| `type` | `incoming` (received) or `outgoing` (sent) |
| `from_name`, `from_email`, `to`, `subject`, `date`, `timestamp` | metadata |
| original body | immutable (`body_text` / `body_html`) — never overwritten |
| `body` | the DISPLAYED body — original, or the reworked version if reworked |
| `is_reworked` | true when the agent replaced the display body |

### thread
Ordered array of emails. `thread_id`, `title` (agent-set), `position` (sort
order, lower = top). Emails carry a `thread_pos` within the thread.

### draft
Unsent reply: `draft_id`, `thread_id`, `to`, `subject`, `body`. Saving never sends.

## REST endpoints

Read:
- `GET /api/email/threads?account=<email>` → `{threads:[{thread_id,title,position,emails:[…],drafts:[…],participants:[…]}]}`
- `GET /api/email/original?id=<email_id>` → immutable original `{body_text,body_html,…}`

Mutate (`POST /api/email/mgmt/<action>`):
| action | body |
|--------|------|
| `preprocess` | `{account}` — build threads from synced emails |
| `rework` | `{email_id, text}` — set reworked display body |
| `restore` | `{email_id}` — revert to original |
| `rename-thread` | `{thread_id, title}` |
| `reorder-threads` | `{account, order:[thread_id…]}` |
| `set-thread-position` | `{thread_id, position}` |
| `move-email` | `{email_id, thread_id, position}` |
| `reorder-emails` | `{thread_id, order:[email_id…]}` |
| `create-thread` | `{account, title, position}` |
| `save-draft` | `{account, thread_id, body, to, subject, draft_id?}` |
| `delete-draft` | `{draft_id}` |

Sync / send (existing):
- `POST /api/email/sync` `{account_email}` — incremental IMAP pull (INBOX + Sent)
- `POST /api/email/send` `{account_email, to, subject, body, reply_to_message_id}` — actually sends

## Agent tools (1:1 with the API)

`email_fetch_inbox`, `email_preprocess`, `email_list_threads`, `email_get_original`,
`email_rework`, `email_restore`, `email_rename_thread`, `email_reorder_threads`,
`email_move_email`, `email_reorder_emails`, `email_create_thread`,
`email_save_draft`, `email_delete_draft`, `email_send`.

See `skill/SKILL.md` for the recommended workflow.
