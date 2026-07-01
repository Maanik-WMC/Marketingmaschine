from __future__ import annotations

import json
import os
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .governance import GovernancePolicy, PolicyAction
from .schemas import ContentStatus, utc_now
from .storage import JsonStore


def route_scheduler_draft(
    *,
    store: JsonStore,
    policy: GovernancePolicy,
    content_id: str,
    target: str = "postiz",
    dry_run: bool = True,
) -> dict[str, Any]:
    if target != "postiz":
        return outbox_record(
            kind="scheduler_draft",
            target=target,
            source_id=content_id,
            payload={},
            status="blocked",
            dry_run=dry_run,
            reason=f"unsupported scheduler target: {target}",
        )

    decision = policy.check_tool("create_postiz_draft")
    if decision.action != PolicyAction.ALLOW:
        return outbox_record(
            kind="scheduler_draft",
            target=target,
            source_id=content_id,
            payload={},
            status="blocked",
            dry_run=dry_run,
            reason=decision.reason,
        )

    state = store.load_state(content_id)
    brief = state.get("brief", {})
    scheduler_payload = state.get("scheduler_payload", {})
    if brief.get("status") != ContentStatus.READY_TO_SCHEDULE.value or state.get("next_step") != "scheduler":
        return outbox_record(
            kind="scheduler_draft",
            target=target,
            source_id=content_id,
            payload={},
            status="blocked",
            dry_run=dry_run,
            reason="content is not approved and ready for scheduler",
        )
    if scheduler_payload.get("status") != "draft_only_requires_final_platform_approval":
        return outbox_record(
            kind="scheduler_draft",
            target=target,
            source_id=content_id,
            payload={},
            status="blocked",
            dry_run=dry_run,
            reason="scheduler payload is missing draft-only approval guard",
        )

    payload = {
        "title": f"{brief.get('campaign', 'WAMOCON')} - {content_id}",
        "content": scheduler_payload.get("copy", ""),
        "status": "draft",
        "platform": brief.get("channel", "LinkedIn"),
        "campaign": brief.get("campaign", ""),
        "persona": brief.get("persona", ""),
        "utm": scheduler_payload.get("utm", {}),
        "metadata": {
            "content_id": content_id,
            "postiz_mode": scheduler_payload.get("postiz_mode", "draft_only"),
            "evidence_records": scheduler_payload.get("evidence_records", []),
            "final_platform_approval_required": True,
        },
    }
    return send_or_prepare(
        kind="scheduler_draft",
        target="postiz",
        source_id=content_id,
        payload=payload,
        dry_run=dry_run,
        endpoint_env="POSTIZ_CREATE_DRAFT_PATH",
        base_url_env="POSTIZ_BASE_URL",
        token_env=("POSTIZ_API_KEY", "POSTIZ_API_TOKEN"),
    )


def route_lead(
    *,
    store: JsonStore,
    policy: GovernancePolicy,
    lead_id: str,
    target: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    tool_name = "route_twenty_lead" if target == "twenty" else "route_mautic_lead" if target == "mautic" else "route_lead"
    decision = policy.check_tool(tool_name)
    if decision.action != PolicyAction.ALLOW:
        return outbox_record(
            kind="lead",
            target=target,
            source_id=lead_id,
            payload={},
            status="blocked",
            dry_run=dry_run,
            reason=decision.reason,
        )

    lead_result = store.load_lead(lead_id)
    lead = lead_result.get("lead", {})
    if not lead_result.get("routing_allowed"):
        return outbox_record(
            kind="lead",
            target=target,
            source_id=lead_id,
            payload={},
            status="blocked",
            dry_run=dry_run,
            reason=f"lead is not routable: {lead.get('next_action', 'unknown')}",
        )

    if target == "twenty":
        payload = lead_result.get("crm_payload", {})
        return send_or_prepare(
            kind="lead",
            target="twenty",
            source_id=lead_id,
            payload=payload,
            dry_run=dry_run,
            endpoint_env="TWENTY_CREATE_CONTACT_PATH",
            base_url_env="TWENTY_BASE_URL",
            token_env=("TWENTY_API_KEY", "TWENTY_API_TOKEN"),
        )
    if target == "mautic":
        payload = lead_result.get("mautic_payload", {})
        return send_or_prepare(
            kind="lead",
            target="mautic",
            source_id=lead_id,
            payload=payload,
            dry_run=dry_run,
            endpoint_env="MAUTIC_CREATE_CONTACT_PATH",
            base_url_env="MAUTIC_BASE_URL",
            token_env=("MAUTIC_API_KEY", "MAUTIC_API_TOKEN"),
        )

    return outbox_record(
        kind="lead",
        target=target,
        source_id=lead_id,
        payload={},
        status="blocked",
        dry_run=dry_run,
        reason=f"unsupported lead target: {target}",
    )


def send_or_prepare(
    *,
    kind: str,
    target: str,
    source_id: str,
    payload: dict[str, Any],
    dry_run: bool,
    endpoint_env: str,
    base_url_env: str,
    token_env: tuple[str, ...],
) -> dict[str, Any]:
    writes_enabled = external_writes_enabled()
    base_url = os.environ.get(base_url_env, "").strip()
    endpoint_path = os.environ.get(endpoint_env, "").strip()
    token_name, token = first_env_value(token_env)

    if dry_run:
        return outbox_record(
            kind=kind,
            target=target,
            source_id=source_id,
            payload=payload,
            status="prepared",
            dry_run=True,
            reason="dry run: external write was not attempted",
            config=config_summary(writes_enabled, base_url, endpoint_path, token_name, token),
        )
    if not writes_enabled:
        return outbox_record(
            kind=kind,
            target=target,
            source_id=source_id,
            payload=payload,
            status="prepared",
            dry_run=True,
            reason="external writes are disabled; set MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES=true to send",
            config=config_summary(writes_enabled, base_url, endpoint_path, token_name, token),
        )
    if not base_url or not endpoint_path or not token:
        return outbox_record(
            kind=kind,
            target=target,
            source_id=source_id,
            payload=payload,
            status="prepared",
            dry_run=True,
            reason="external write config incomplete; base URL, endpoint path, and token are required",
            config=config_summary(writes_enabled, base_url, endpoint_path, token_name, token),
        )

    try:
        response = post_json(f"{base_url.rstrip('/')}/{endpoint_path.lstrip('/')}", payload, token)
        return outbox_record(
            kind=kind,
            target=target,
            source_id=source_id,
            payload=payload,
            status="sent",
            dry_run=False,
            response=response,
            config=config_summary(writes_enabled, base_url, endpoint_path, token_name, token),
        )
    except (OSError, HTTPError, URLError, json.JSONDecodeError) as exc:
        return outbox_record(
            kind=kind,
            target=target,
            source_id=source_id,
            payload=payload,
            status="failed",
            dry_run=False,
            reason=str(exc),
            config=config_summary(writes_enabled, base_url, endpoint_path, token_name, token),
        )


def post_json(url: str, payload: dict[str, Any], token: str) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "wamocon-marketing-machine/0.1",
        },
    )
    with urlopen(request, timeout=15) as response:
        raw = response.read().decode("utf-8")
        return {"status": response.status, "body": json.loads(raw) if raw else {}}


def outbox_record(
    *,
    kind: str,
    target: str,
    source_id: str,
    payload: dict[str, Any],
    status: str,
    dry_run: bool,
    reason: str = "",
    response: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"route-{uuid.uuid4().hex[:12]}",
        "kind": kind,
        "target": target,
        "source_id": source_id,
        "status": status,
        "dry_run": dry_run,
        "reason": reason,
        "payload": payload,
        "response": response or {},
        "config": config or {},
        "created_at": utc_now(),
    }


def external_writes_enabled() -> bool:
    return os.environ.get("MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES", "").strip().lower() in {"1", "true", "yes", "on"}


def first_env_value(names: tuple[str, ...]) -> tuple[str, str]:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return name, value
    return names[0], ""


def config_summary(
    writes_enabled: bool,
    base_url: str,
    endpoint_path: str,
    token_name: str,
    token: str,
) -> dict[str, Any]:
    return {
        "writes_enabled": writes_enabled,
        "base_url_configured": bool(base_url),
        "endpoint_path_configured": bool(endpoint_path),
        "token_env": token_name,
        "token_configured": bool(token),
    }
