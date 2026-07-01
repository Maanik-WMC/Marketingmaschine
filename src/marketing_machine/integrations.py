from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def check_url(name: str, url: str, *, required: bool = False) -> dict[str, Any]:
    try:
        request = Request(url, headers={"User-Agent": "wamocon-marketing-machine/0.1"})
        with urlopen(request, timeout=5) as response:
            return {"name": name, "ok": True, "required": required, "status": response.status, "url": url}
    except (OSError, HTTPError, URLError) as exc:
        return {"name": name, "ok": False, "required": required, "url": url, "error": str(exc)}


def check_ollama_model(base_url: str, model_name: str, *, required: bool = False) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        request = Request(url, headers={"User-Agent": "wamocon-marketing-machine/0.1"})
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            models = sorted(item.get("name", "") for item in payload.get("models", []) if item.get("name"))
            model_present = not model_name or model_name in models
            return {
                "name": "ollama",
                "ok": response.status == 200 and model_present,
                "required": required,
                "status": response.status,
                "url": url,
                "model": model_name,
                "model_present": model_present,
                "available_models": models,
            }
    except (OSError, HTTPError, URLError, json.JSONDecodeError) as exc:
        return {"name": "ollama", "ok": False, "required": required, "url": url, "model": model_name, "error": str(exc)}


def check_openai_compatible_models(
    name: str,
    base_url: str,
    api_key: str,
    model_name: str = "",
    *,
    required: bool = False,
) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    if not base_url:
        return {"name": name, "ok": False, "required": required, "configured": False, "error": "base URL not configured"}
    if not api_key:
        return {
            "name": name,
            "ok": False,
            "required": required,
            "configured": False,
            "url": f"{base_url}/models",
            "model": model_name,
            "error": "API key not configured",
        }

    url = f"{base_url}/models"
    try:
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "wamocon-marketing-machine/0.1",
            },
        )
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
            models = sorted(item.get("id", "") for item in payload.get("data", []) if item.get("id"))
            model_present = not model_name or model_name in models
            return {
                "name": name,
                "ok": response.status == 200 and model_present,
                "required": required,
                "configured": True,
                "status": response.status,
                "url": url,
                "model": model_name,
                "model_present": model_present,
                "available_models": models,
            }
    except (OSError, HTTPError, URLError, json.JSONDecodeError) as exc:
        return {
            "name": name,
            "ok": False,
            "required": required,
            "configured": True,
            "url": url,
            "model": model_name,
            "error": str(exc),
        }
