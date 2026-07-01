from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ModelRoute:
    name: str
    provider: str
    temperature: float
    requires_network: bool = False
    requires_human_final_approval: bool = False


class ModelRouter:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    @classmethod
    def from_json_file(cls, path: str | Path) -> "ModelRouter":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def route(self, task_route: str) -> ModelRoute:
        data = self.config["routes"][task_route]
        return ModelRoute(
            name=task_route,
            provider=data["provider"],
            temperature=float(data.get("temperature", 0.0)),
            requires_network=bool(data.get("requires_network", False)),
            requires_human_final_approval=bool(data.get("requires_human_final_approval", False)),
        )
