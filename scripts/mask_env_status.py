from __future__ import annotations

import argparse
from pathlib import Path


SECRET_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CLIENT_SECRET")


def is_secret_key(key: str) -> bool:
    upper = key.upper()
    return any(marker in upper for marker in SECRET_MARKERS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Show .env key presence without printing secret values.")
    parser.add_argument("env_file")
    args = parser.parse_args()

    path = Path(args.env_file)
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or "=" not in raw:
            continue
        key, raw_value = raw.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        state = "set" if value else "empty"
        shown = "***" if value and is_secret_key(key) else state
        issue = "has surrounding spaces" if raw_value != value else ""
        print("|".join((key, state, shown, issue)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
