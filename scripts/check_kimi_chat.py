from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def check_chat(base_url: str, api_key: str, model: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Answer with only OK."},
            {"role": "user", "content": "Connection test."},
        ],
        "max_tokens": 8,
    }
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "wamocon-kimi-chat-probe/0.1",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
            return {
                "base_url": base_url,
                "model": model,
                "ok": response.status == 200,
                "status": response.status,
                "response_id": body.get("id", ""),
            }
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:800]
        return {"base_url": base_url, "model": model, "ok": False, "status": exc.code, "error": body}
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return {"base_url": base_url, "model": model, "ok": False, "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Kimi chat completion without printing the API key.")
    parser.add_argument("--env-file", default="deploy/marketing-agent.generated.env")
    args = parser.parse_args()

    load_env_file(Path(args.env_file))
    base_url = os.environ.get("KIMI_BASE_URL", "https://api.moonshot.ai/v1")
    api_key = os.environ.get("KIMI_API_KEY", "")
    model = os.environ.get("KIMI_MODEL_NAME", "kimi-k2.7-code")
    if not api_key:
        print(json.dumps({"status": "failed", "error": "KIMI_API_KEY is not configured"}, indent=2))
        return 1
    result = check_chat(base_url, api_key, model)
    print(json.dumps({"status": "ok" if result.get("ok") else "failed", "result": result}, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
