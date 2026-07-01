# Deployment Stack

## Core Local Stack

Use `deploy/docker-compose.core.yml` for the first internal deployment:

- Postgres for records and audit log
- Redis for queue mode
- n8n in queue mode
- n8n worker
- marketing-agent API

This compose file is a starting template. Replace default passwords and `N8N_ENCRYPTION_KEY` through a secret manager before production.

## Local Model Serving

Use the DGX/local GPU host for Qwen:

```bash
deploy/local-model/vllm-qwen.example.sh
```

Production requirements:

- pin model revision
- monitor GPU memory and request latency
- expose OpenAI-compatible endpoint internally only
- do not send private prompts to cloud fallback by default

## n8n

Use queue mode for reliability:

- one main n8n service
- one or more workers
- Redis queue
- Postgres database

Import workflow templates from:

- `deploy/n8n/workflows/weekly-planning.json`
- `deploy/n8n/workflows/analytics-72h.json`

## Publishing

Use Postiz or Metricool.

The Scheduler Agent creates draft payloads only. Humans approve the final scheduled item in the publishing tool.

## Lead Stack

Recommended open-source path:

- Mautic for landing forms, segments, email nurturing, and lead scoring
- Twenty for CRM and sales follow-up

Alternative:

- HubSpot for CRM and marketing automation

All leads must include campaign, offer, persona, UTM, and source content id.
