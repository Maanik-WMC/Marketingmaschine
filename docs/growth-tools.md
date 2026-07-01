# Growth Tools

The marketing machine can connect to Postiz, Twenty, and Mautic, but these are intentionally deployed as optional profiles.

Reason: the NVIDIA host is already running a large local-AI stack. Postiz adds Temporal and Elasticsearch; Twenty adds a worker plus Postgres/Redis; Mautic adds MySQL, web, cron, and worker containers. Start one profile at a time and verify memory before enabling the next one.

## Profiles

- `postiz`: social scheduling candidate, exposed at `http://127.0.0.1:4007`.
- `twenty`: CRM candidate, exposed at `http://127.0.0.1:4019`.
- `mautic`: marketing automation candidate, exposed at `http://127.0.0.1:4020`.

## Start One Tool

Create a private env file from `deploy/growth-tools.env.example`, fill generated secrets, then run one profile:

```bash
docker compose --env-file deploy/growth-tools.generated.env -f deploy/docker-compose.growth-tools.yml --profile twenty up -d
```

Use the same pattern for `postiz` or `mautic`.

## Verify

```bash
curl -sS http://127.0.0.1:8117/integrations/status
python3 scripts/smoke_api.py --base-url http://127.0.0.1:8117 --n8n-url http://127.0.0.1:5678
```

The marketing agent reports Postiz, Twenty, and Mautic as optional integrations. Core readiness only depends on n8n, ComfyUI, and the local Qwen model.

## Guardrails

- Do not connect social accounts until legal/business approval is clear.
- Keep public app ports behind reverse proxy/auth before external exposure.
- Keep registration disabled after setup unless a controlled onboarding process exists.
- Store generated secrets only in private host env files, not in Git.
- Keep AI publishing gated by human approval; these apps are schedulers/CRMs, not autonomous publishers.
