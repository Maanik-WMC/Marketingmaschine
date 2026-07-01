# Compliance Guardrails

## Non-Negotiable Rules

- No public post without human approval.
- No auto-publishing from AI.
- No customer, employee, or applicant content without consent.
- No ROI, security, compliance, or benchmark claim without proof.
- No private scraping or platform terms bypass.
- No secrets in prompts, logs, screenshots, or repo files.

## AI Act Readiness

Track whether content uses AI-generated:

- images
- video
- audio
- synthetic people
- synthetic customer-like screenshots
- automated reply drafts

Disclosure must be evaluated during review. The default internal rule is to track all AI-generated media, even when public disclosure is not required.

## GDPR And Consent

Consent is required for:

- employee stories
- applicant stories
- customer references
- screenshots that include personal data
- CRM follow-up and email nurturing

The Evidence Vault should store consent references, not raw sensitive documents.

## MCP And Tool Safety

MCP servers are deny-by-default.

Allowed servers must define:

- server id
- allowed tools
- blocked tools
- network boundary
- approval requirements

High-risk tools require review:

- publishing
- email sending
- CRM notes
- ComfyUI job submission
- cloud model calls

## Creative Supply Chain

For ComfyUI:

- pin workflows
- pin custom node versions
- pin model revisions
- restrict network access
- scan custom nodes before production use
- store workflow hash with output assets
