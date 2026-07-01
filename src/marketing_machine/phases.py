from __future__ import annotations

from pathlib import Path
from typing import Mapping, Any


def build_phase_status(
    *,
    integrations: dict[str, Any],
    env: Mapping[str, str],
    workflows_dir: Path,
) -> dict[str, Any]:
    checks = {item.get("name"): item for item in integrations.get("checks", []) if isinstance(item, dict)}
    required_ok = bool(integrations.get("status") == "ok")
    local_model_ok = bool(checks.get("ollama", {}).get("ok") and checks.get("local_openai", {}).get("ok"))
    kimi_ok = bool(checks.get("kimi", {}).get("ok"))
    external_writes_enabled = _truthy(env.get("MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES", ""))
    write_targets = {
        "postiz": _has_target_config(env, "POSTIZ_CREATE_DRAFT_PATH", "POSTIZ_API_KEY"),
        "twenty": _has_target_config(env, "TWENTY_CREATE_CONTACT_PATH", "TWENTY_API_KEY"),
        "mautic": _has_target_config(env, "MAUTIC_CREATE_CONTACT_PATH", "MAUTIC_API_KEY"),
    }
    all_write_targets_ready = all(write_targets.values())

    analytics_workflows = {
        "72h": (workflows_dir / "analytics-72h.json").exists(),
        "7d": (workflows_dir / "analytics-7d.json").exists(),
        "14d": (workflows_dir / "analytics-14d.json").exists(),
        "30d": (workflows_dir / "analytics-30d.json").exists(),
    }

    phases = [
        _phase(
            "01_control_plane",
            "Control plane and UI",
            "complete" if required_ok else "blocked",
            [
                "FastAPI agent is deployed",
                "Browser console is available",
                "Recent states, leads, outbox, and status are queryable",
            ],
            [] if required_ok else ["Fix required service health before running campaign workflows"],
        ),
        _phase(
            "02_model_plane",
            "Local/private model plane",
            "complete" if local_model_ok else "partial",
            [
                "Ollama local model check is active",
                "OpenAI-compatible local endpoint check is active",
                "Local model remains primary for private work",
            ],
            [] if local_model_ok else ["Restore local Ollama and local OpenAI-compatible model health"],
        ),
        _phase(
            "03_cloud_backup",
            "Kimi optional cloud backup",
            "complete" if kimi_ok else "blocked",
            [
                "Kimi is optional and not required for the marketing flow",
                "Kimi key is configured" if checks.get("kimi", {}).get("configured") else "Kimi key is not configured",
            ],
            [] if kimi_ok else ["Use a valid Kimi Open Platform API key before relying on Kimi fallback"],
            critical=False,
        ),
        _phase(
            "04_content_workflow",
            "Content intake, proof gate, German draft, human approval",
            "complete",
            [
                "Manual brief intake is implemented",
                "Evidence sources are checked before drafting",
                "German-market language guard is active",
                "Approval requires brand, fact, privacy, and AI disclosure checks",
            ],
        ),
        _phase(
            "05_governance",
            "Governance and guardrails",
            "complete",
            [
                "No auto-publishing",
                "No public claims without proof",
                "Consent and privacy checks are enforced",
                "Instagram hashtag cap is enforced",
            ],
        ),
        _phase(
            "06_n8n_rhythm",
            "n8n operating rhythm",
            "complete" if all(analytics_workflows.values()) else "partial",
            [
                "Weekly rolling 30-day planning workflow exists",
                "72h, 7d, 14d, and 30d analytics workflow files are present",
            ],
            [] if all(analytics_workflows.values()) else ["Import or add missing analytics workflow JSON files in n8n"],
            metadata={"analytics_workflows": analytics_workflows},
        ),
        _phase(
            "07_analytics_loop",
            "Performance learning loop",
            "complete",
            [
                "72h early-signal review is implemented",
                "7d and 14d optimization decisions are implemented",
                "30d scale/stop business-value decision is implemented",
                "KPI records are stored for audit",
            ],
        ),
        _phase(
            "08_lead_plane",
            "Lead capture, scoring, and CRM payloads",
            "partial" if not (external_writes_enabled and all_write_targets_ready) else "complete",
            [
                "Lead intake is implemented",
                "Consent guard blocks CRM and nurture routing when consent is missing",
                "Twenty and Mautic payload contracts are prepared",
            ],
            [] if external_writes_enabled and all_write_targets_ready else [
                "Live CRM/Mautic writes remain disabled until exact API paths and tokens are configured"
            ],
            metadata={"write_targets_ready": write_targets, "external_writes_enabled": external_writes_enabled},
        ),
        _phase(
            "09_publishing_plane",
            "Postiz publishing handoff",
            "partial" if not (external_writes_enabled and write_targets["postiz"]) else "complete",
            [
                "Approved content creates draft-only scheduler payload",
                "Unapproved content cannot route to Postiz",
                "Postiz route is dry-run by default",
            ],
            [] if external_writes_enabled and write_targets["postiz"] else [
                "Live Postiz write remains disabled until POSTIZ_CREATE_DRAFT_PATH and POSTIZ_API_KEY are verified"
            ],
            metadata={"postiz_ready": write_targets["postiz"], "external_writes_enabled": external_writes_enabled},
        ),
        _phase(
            "10_creative_plane",
            "ComfyUI creative workflow",
            "partial",
            [
                "ComfyUI health is checked",
                "ComfyUI-ready creative briefs are generated",
                "Human visual approval is required",
            ],
            ["Actual ComfyUI job queue submission is intentionally not enabled yet"],
            critical=False,
        ),
        _phase(
            "11_langgraph_mcp",
            "LangGraph and MCP production hardening",
            "partial",
            [
                "LangGraph dependency and graph builder are present",
                "MCP allowlist and governance config are present",
            ],
            [
                "Durable LangGraph checkpoint execution is not yet the live API runtime",
                "MCP gateway enforcement is config-level, not a deployed gateway service yet",
            ],
            critical=False,
        ),
    ]

    critical = [phase for phase in phases if phase["critical"]]
    blocked_critical = [phase for phase in critical if phase["status"] == "blocked"]
    incomplete_critical = [phase for phase in critical if phase["status"] != "complete"]
    if blocked_critical:
        overall = "blocked"
    elif incomplete_critical:
        overall = "operational_with_blockers"
    else:
        overall = "operational"

    return {
        "status": overall,
        "summary": {
            "complete": sum(1 for phase in phases if phase["status"] == "complete"),
            "partial": sum(1 for phase in phases if phase["status"] == "partial"),
            "blocked": sum(1 for phase in phases if phase["status"] == "blocked"),
            "total": len(phases),
        },
        "phases": phases,
    }


def _phase(
    phase_id: str,
    name: str,
    status: str,
    evidence: list[str],
    next_actions: list[str] | None = None,
    *,
    critical: bool = True,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": phase_id,
        "name": name,
        "status": status,
        "critical": critical,
        "evidence": evidence,
        "next_actions": next_actions or [],
        "metadata": metadata or {},
    }


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _has_target_config(env: Mapping[str, str], path_key: str, token_key: str) -> bool:
    return bool(env.get(path_key, "").strip() and env.get(token_key, "").strip())
