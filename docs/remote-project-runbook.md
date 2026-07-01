# Remote Project Runbook

## Location

The NVIDIA deployment should live under:

`/home/wamocon/lokal-ai-stack/marketing/wamocon-marketing-machine`

This project uses the already hosted services:

- n8n: `core-n8n` on Docker network `core-net`, host port `5678`
- ComfyUI: host process on `http://host.docker.internal:8188`
- Ollama/Qwen: host process on `http://host.docker.internal:11434`

## Start

```bash
cd /home/wamocon/lokal-ai-stack/marketing/wamocon-marketing-machine
docker compose -f deploy/docker-compose.existing-stack.yml up -d --build
```

## Health

```bash
curl http://127.0.0.1:8117/healthz
curl http://127.0.0.1:8117/integrations/status
```

## Import n8n Workflows

Copy workflow JSON files to the mounted n8n files directory:

`/home/wamocon/lokal-ai/data/n8n-files/wamocon-marketing-machine/workflows`

Then import from inside n8n:

```bash
docker exec core-n8n n8n import:workflow --separate --input=/data/files/wamocon-marketing-machine/workflows
```

Imported workflows are inactive by default. Activate them manually in n8n after checking credentials and routes.

## Manual Intake Payload

POST to the n8n webhook or directly to the agent:

```json
{
  "id": "k5-app-proof-001",
  "campaign": "K5 App Development",
  "persona": "IT-Leiter Thomas",
  "channel": "LinkedIn",
  "format": "expert_post",
  "language": "de-DE",
  "objective": "App-Portfolio als Nachweis für einen App-Modernisierungscheck nutzen.",
  "cta": "App-Modernisierungscheck anfragen",
  "proof_sources": ["Kampagnen/kampagne_5_app_entwicklung.json"],
  "utm": {
    "utm_source": "linkedin",
    "utm_medium": "organic",
    "utm_campaign": "k5_app_modernization"
  },
  "hypothesis": "Konkrete App-Beispiele erzeugen bessere B2B-Anfragen als generische Softwaretexte.",
  "test_variable": "proof_asset"
}
```

## Human Approval Payload

```json
{
  "content_id": "k5-app-proof-001",
  "reviewer": "human-reviewer",
  "decision": "approved",
  "brand_score": 92,
  "fact_check_passed": true,
  "privacy_check_passed": true,
  "ai_disclosure_check_passed": true,
  "notes": "Approved for draft scheduling."
}
```

The scheduler payload remains draft-only. No automated public publish is allowed.
