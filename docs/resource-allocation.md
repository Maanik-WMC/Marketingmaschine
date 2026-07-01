# Resource Allocation

Last checked: 2026-06-30

## Current split

- Nvidia-1 (`spark-f752`) is the control plane.
  - Runs the marketing agent, n8n, Postiz, Mautic, Twenty, monitoring, and existing local stack services.
  - Marketing agent is small: about 40 MiB RAM.
  - Local Ollama models are not kept loaded for the marketing agent.
- Nvidia-2 (`spark-651f`) is the model and creative worker.
  - Runs Ollama on `10.100.104.2:11434`.
  - Runs ComfyUI on `10.100.104.2:8188`.
  - Keeps `qwen3.6:35b` available for private marketing work.
  - `gemma4:31b` is kept on demand, not permanently warm.

## Marketing agent routing

The marketing agent reads these values from `deploy/marketing-agent.generated.env` on Nvidia-1:

```env
COMFYUI_BASE_URL=http://10.100.104.2:8188
OLLAMA_BASE_URL=http://10.100.104.2:11434
LOCAL_OPENAI_BASE_URL=http://10.100.104.2:11434/v1
LOCAL_OPENAI_API_KEY=ollama
LOCAL_MODEL_NAME=qwen3.6:35b
```

Do not put real API keys in `.env.example` files.

## Why

Nvidia-1 previously had both `qwen3.6:35b` and `gemma4:31b` loaded with `262144` context and `Forever` keep-alive. That pinned a large amount of unified memory and filled swap. Routing the marketing agent to Nvidia-2 prevents it from reloading those large model sessions on Nvidia-1.

## Checks

Run these from the project root on Nvidia-1:

```bash
python3 scripts/smoke_api.py --base-url http://127.0.0.1:8117 --n8n-url http://127.0.0.1:5678
curl -fsS http://127.0.0.1:8117/integrations/status | python3 -m json.tool
```

Run these from any host with SSH access:

```bash
ssh Nvidia-1-Main "free -h; ollama ps"
ssh Nvidia-2 "free -h; ollama ps"
```
