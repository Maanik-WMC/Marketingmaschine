# Postiz Integration

Use Postiz as a self-hosted social scheduling candidate.

Production rule:

- Agents may create draft scheduler payloads only.
- Publishing remains blocked until the approval record is publishable.
- Sensitive comments and replies are drafted only; humans approve public replies.

Expected payload fields:

- `content_id`
- `channel`
- `copy`
- `asset_refs`
- `utm`
- `approval_record_id`
- `scheduled_at`
- `status=draft`

Do not store real API keys in this repo. Use a secret manager.
