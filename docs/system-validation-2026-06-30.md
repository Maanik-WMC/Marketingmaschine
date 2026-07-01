# System Validation - 2026-06-30

## Result

The WAMOCON marketing pipeline is running and the core automation flow passes through both localhost and LAN proxy access.

The LAN n8n webhook proxy was retested after routing the network-access proxy through the host-published n8n port. Both smoke and mock edge-case tests now pass from the workstation LAN URL.

Kimi is wired as an optional cloud backup, but the current key is not accepted by Moonshot/Kimi and returns `401 Invalid Authentication`.

## LAN URLs

| Component | URL | State |
| --- | --- | --- |
| Marketing console | `http://192.168.178.75:18117/ui` | OK |
| Marketing agent API | `http://192.168.178.75:18117` | OK |
| n8n | `http://192.168.178.75:15678` | OK |
| Postiz | `http://192.168.178.75:14007` | Registration page |
| Twenty CRM | `http://192.168.178.75:14019` | UI loads |
| Mautic | `http://192.168.178.75:14020` | Installer page |
| ComfyUI | `http://192.168.178.75:18188` | OK |
| Grafana | `http://192.168.178.75:13030` | Login page |
| Existing WAMOCON dashboard | `http://192.168.178.75:9090` | Existing service |

Current model/creative routing:

- ComfyUI: `http://10.100.104.2:8188`
- Ollama/Qwen: `http://10.100.104.2:11434`
- Required local model: `qwen3.6:35b`

## Tests Run

Unit tests:

```bash
python3 -m unittest discover -s tests
```

Result: 16 passing tests.

UI endpoint:

```text
http://192.168.178.75:18117/ui
```

Result: HTTP 200, title `WAMOCON Marketing Console`.

Recent states endpoint:

```text
http://192.168.178.75:18117/workflows/states?limit=3
```

Result: HTTP 200.

Smoke test:

```bash
python3 scripts/smoke_api.py --base-url http://127.0.0.1:8117 --n8n-url http://127.0.0.1:5678
python scripts/smoke_api.py --base-url http://192.168.178.75:18117 --n8n-url http://192.168.178.75:15678
```

Result: passed for local and LAN paths.

Mock edge-case test:

```bash
python3 scripts/mock_pipeline_test.py --base-url http://127.0.0.1:8117 --n8n-url http://127.0.0.1:5678
python scripts/mock_pipeline_test.py --base-url http://192.168.178.75:18117 --n8n-url http://192.168.178.75:15678
```

Result: passed for local and LAN paths.

Covered cases:

- Missing proof source is blocked.
- Instagram hashtag spam is blocked.
- Weak approval cannot schedule.
- Approved content creates only a guarded draft scheduler payload.
- Approved scheduler payload contains generated public post copy.
- 72-hour weak signal triggers iteration.
- 7-day clicks without leads triggers landing-page fix.
- 14-day reach without buyer signal triggers audience/offer fix.
- 30-day qualified lead signal triggers scale.
- 30-day no-business-value signal triggers stop.
- n8n manual intake and approval webhooks work.

## Test Data Cleanup

Old mock and smoke data can be removed without touching real campaign IDs:

```bash
python3 scripts/cleanup_test_data.py --root runtime-data --apply
```

The cleanup script only removes content IDs starting with `mock-`, `smoke-`, or `ui-test-`, and filters matching JSONL performance/event records.

## First-Time Setup Values

Do not use fake owner credentials for production setup. Enter real WAMOCON owner credentials in the browser.

Postiz registration:

- URL: `http://192.168.178.75:14007/auth`
- Fields detected: `company`, `email`, `password`
- After creating the owner account, set `POSTIZ_DISABLE_REGISTRATION=true` in `deploy/growth-tools.generated.env` and restart the Postiz profile.

Mautic installer:

- URL: `http://192.168.178.75:14020/installer`
- First detected field: `install_check_step[site_url]`
- Use site URL: `http://192.168.178.75:14020`
- Database values are already in `deploy/growth-tools.generated.env`; do not copy them into docs or chat.

Twenty CRM:

- URL: `http://192.168.178.75:14019`
- UI loads and health check passes.
- Complete owner/workspace setup in the browser with real owner details.

n8n:

- URL: `http://192.168.178.75:15678`
- Webhook automation works.
- Use existing n8n owner credentials if already configured.

Marketing Console:

- URL: `http://192.168.178.75:18117/ui`
- Use `Intake` for campaign briefs.
- Use `Approval` for human approval.
- Use `Analytics` for 72h, 7d, 14d, and 30d KPI reviews.
- Use `Creative` for ComfyUI-ready visual briefs.

## Kimi

Configured file:

```text
deploy/marketing-agent.generated.env
```

The key should only exist in this private generated file, not in `*.example` files.

Current result:

```text
https://api.moonshot.ai/v1/models -> 401 Invalid Authentication
https://api.moonshot.cn/v1/models -> 401 Invalid Authentication
```

Action required: rotate or reissue a valid Moonshot/Kimi API key, then restart the marketing agent.

## Operational Note

Nvidia-1 is improved after model/creative routing to Nvidia-2, but swap is still mostly full:

- Nvidia-1: about 22 GiB available RAM during final validation; swap mostly used.
- Nvidia-2: about 57 GiB available RAM during final validation; swap essentially unused.
- Marketing agent container: about 39 MiB RAM.
- n8n container: about 346 MiB RAM.

For stable production, keep heavy model and ComfyUI work on Nvidia-2, keep Nvidia-1 as the control/workflow plane, and avoid keeping unnecessary large-context models loaded forever on Nvidia-1.
