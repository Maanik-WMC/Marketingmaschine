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


def request_messages(api_key: str, auth_style: str) -> dict[str, Any]:
    url = "https://api.moonshot.ai/anthropic/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "User-Agent": "wamocon-kimi-anthropic-probe/0.1",
    }
    if auth_style == "x-api-key":
        headers["x-api-key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": os.environ.get("KIMI_MODEL_NAME", "kimi-k2.7-code"),
        "max_tokens": 8,
        "messages": [{"role": "user", "content": "Reply with OK only."}],
    }
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
            return {
                "auth_style": auth_style,
                "ok": response.status == 200,
                "status": response.status,
                "response_id": body.get("id", ""),
            }
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:800]
        return {"auth_style": auth_style, "ok": False, "status": exc.code, "error": body}
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return {"auth_style": auth_style, "ok": False, "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Kimi Code Anthropic-compatible endpoint without printing keys.")
    parser.add_argument("--env-file", default="deploy/marketing-agent.generated.env")
    args = parser.parse_args()

    load_env_file(Path(args.env_file))
    api_key = os.environ.get("KIMI_API_KEY", "")
    if not api_key:
        print(json.dumps({"status": "failed", "error": "KIMI_API_KEY is not configured"}, indent=2))
        return 1
    results = [request_messages(api_key, "x-api-key"), request_messages(api_key, "bearer")]
    ok = any(result.get("ok") for result in results)
    print(json.dumps({"status": "ok" if ok else "failed", "results": results}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
