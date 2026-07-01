from __future__ import annotations

import argparse
import os
from pathlib import Path


def update_env(path: Path, updates: dict[str, str]) -> None:
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    lines: list[str] = []

    for line in existing:
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            lines.append(line)
            continue
        key, _value = line.split("=", 1)
        key = key.strip()
        if key in updates:
            lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            lines.append(line)

    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description="Update selected .env keys without printing secret values.")
    parser.add_argument("env_file")
    parser.add_argument("assignments", nargs="+", help="KEY=VALUE pairs to set.")
    args = parser.parse_args()

    updates: dict[str, str] = {}
    for assignment in args.assignments:
        if "=" not in assignment:
            raise SystemExit(f"invalid assignment: {assignment}")
        key, value = assignment.split("=", 1)
        updates[key] = value

    update_env(Path(args.env_file), updates)
    print(f"updated {len(updates)} keys in {args.env_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
