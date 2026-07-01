from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(method: str, base_url: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "wamocon-smoke-test/0.1"},
        method=method,
    )
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def make_content_payload(content_id: str) -> dict[str, Any]:
    return {
        "id": content_id,
        "campaign": "Smoke Test QA Risk Audit",
        "persona": "IT-Leiter Thomas",
        "channel": "LinkedIn",
        "format": "expert_post",
        "language": "de-DE",
        "objective": "Den gesteuerten WAMOCON-Content-Workflow mit einem QA-Risikoaudit prüfen.",
        "cta": "QA-Risikoaudit anfragen",
        "proof_sources": ["Kampagnen/kampagne_1_consulting_qa.json"],
        "utm": {
            "utm_source": "linkedin",
            "utm_medium": "organic",
            "utm_campaign": "smoke_test_qa_risk_audit",
        },
        "hypothesis": "Ein nachweisbasierter QA-Beitrag erzeugt qualifizierte Anfragen von IT-Leitern.",
        "test_variable": "smoke_test",
    }


def make_approval_payload(content_id: str) -> dict[str, Any]:
    return {
        "content_id": content_id,
        "reviewer": "smoke-test",
        "decision": "approved",
        "brand_score": 95,
        "fact_check_passed": True,
        "privacy_check_passed": True,
        "ai_disclosure_check_passed": True,
        "notes": "Smoke-test approval. Do not publish without final human review in the scheduler.",
    }


def make_lead_payload(content_id: str, lead_id: str) -> dict[str, Any]:
    return {
        "id": lead_id,
        "source_content_id": content_id,
        "campaign": "Smoke Test QA Risk Audit",
        "offer": "QA-Risikoaudit",
        "persona": "IT-Leiter Thomas",
        "contact_name": "Max Mustermann",
        "company": "Muster GmbH",
        "email": "it-leitung@muster-gmbh.de",
        "message": "Wir möchten einen QA-Risikoaudit Termin anfragen.",
        "consent_given": True,
        "utm": {
            "utm_source": "linkedin",
            "utm_medium": "organic",
            "utm_campaign": "smoke_test_qa_risk_audit",
        },
    }


def test_agent_api(base_url: str, stamp: int) -> list[str]:
    checks: list[str] = []

    health = request_json("GET", base_url, "/healthz")
    assert_true(health.get("status") == "ok", f"healthz failed: {health}")
    checks.append("agent health")

    integrations = request_json("GET", base_url, "/integrations/status")
    assert_true(integrations.get("status") == "ok", f"integrations not ok: {integrations}")
    checks.append("n8n, ComfyUI, Ollama integration status")

    weekly = request_json("POST", base_url, "/workflows/weekly-planning", {})
    assert_true(weekly.get("status") == "accepted", f"weekly planning failed: {weekly}")
    assert_true(len(weekly.get("created", [])) >= 3, f"weekly planning created too few items: {weekly}")
    checks.append("rolling weekly planning")

    content_id = f"smoke-direct-{stamp}"
    created = request_json("POST", base_url, "/workflows/create-content", make_content_payload(content_id))
    assert_true(created.get("content_id") == content_id, f"create-content returned wrong id: {created}")
    assert_true(created.get("state", {}).get("next_step") == "human_review", f"content did not pause: {created}")
    checks.append("direct content creation with human-review pause")

    approval = request_json("POST", base_url, "/workflows/approve-content", make_approval_payload(content_id))
    state = approval.get("state", {})
    assert_true(state.get("next_step") == "scheduler", f"approval did not advance to scheduler: {approval}")
    assert_true(state.get("brief", {}).get("status") == "ready_to_schedule", f"approval status wrong: {approval}")
    assert_true(state.get("scheduler_payload", {}).get("status") == "draft_only_requires_final_platform_approval", f"scheduler guard missing: {approval}")
    assert_true("LinkedIn-Entwurf" in state.get("scheduler_payload", {}).get("copy", ""), f"scheduler copy missing German public post draft: {approval}")
    assert_true(bool(state.get("scheduler_payload", {}).get("evidence_records")), f"scheduler proof metadata missing: {approval}")
    checks.append("direct approval and guarded scheduler payload")

    route = request_json(
        "POST",
        base_url,
        "/workflows/route-scheduler-draft",
        {"content_id": content_id, "target": "postiz", "dry_run": True},
    )
    assert_true(route.get("status") == "prepared", f"Postiz draft route was not prepared: {route}")
    assert_true(route.get("route", {}).get("dry_run") is True, f"Postiz draft route did not stay dry-run: {route}")
    checks.append("approved scheduler draft prepares Postiz outbox route")

    lead = request_json("POST", base_url, "/workflows/lead-intake", make_lead_payload(content_id, f"smoke-lead-{stamp}"))
    assert_true(lead.get("status") == "accepted", f"lead intake failed: {lead}")
    assert_true(lead.get("routing_allowed") is True, f"lead was not routable: {lead}")
    assert_true(lead.get("lead", {}).get("next_action") == "sales_follow_up", f"lead action wrong: {lead}")
    assert_true(bool(lead.get("crm_payload")), f"CRM payload missing: {lead}")
    checks.append("lead intake scoring and CRM payload contract")

    lead_route = request_json(
        "POST",
        base_url,
        "/workflows/route-lead",
        {"lead_id": f"smoke-lead-{stamp}", "target": "twenty", "dry_run": True},
    )
    assert_true(lead_route.get("status") == "prepared", f"Twenty lead route was not prepared: {lead_route}")
    assert_true(lead_route.get("route", {}).get("dry_run") is True, f"Twenty lead route did not stay dry-run: {lead_route}")
    checks.append("qualified lead prepares Twenty outbox route")

    creative = request_json(
        "POST",
        base_url,
        "/workflows/comfyui-brief",
        {"campaign": "K5 App Development", "headline": "Proof beats promises"},
    )
    assert_true(creative.get("status") == "draft_created", f"ComfyUI brief failed: {creative}")
    assert_true(creative.get("comfyui_brief", {}).get("review_required") is True, f"creative review guard missing: {creative}")
    checks.append("ComfyUI creative brief contract")

    analytics = request_json(
        "POST",
        base_url,
        "/workflows/analytics-review",
        {
            "content_id": content_id,
            "review_window": "72h",
            "impressions": 1200,
            "saves": 14,
            "shares": 4,
            "comments_from_target_buyers": 2,
            "profile_visits": 45,
            "clicks": 38,
            "leads": 0,
            "qualified_leads": 0,
            "booked_calls": 0,
            "landing_page_visits": 38,
            "landing_page_conversions": 0,
        },
    )
    assert_true(analytics.get("status") == "evaluated", f"analytics failed: {analytics}")
    assert_true(bool(analytics.get("action")), f"analytics action missing: {analytics}")
    checks.append("72-hour analytics decision")

    return checks


def test_n8n_webhooks(n8n_url: str, stamp: int) -> list[str]:
    checks: list[str] = []
    content_id = f"smoke-n8n-{stamp}"

    created = request_json("POST", n8n_url, "/webhook/wamocon-marketing/content-intake", make_content_payload(content_id))
    assert_true(created.get("content_id") == content_id, f"n8n intake returned wrong id: {created}")
    assert_true(created.get("state", {}).get("next_step") == "human_review", f"n8n intake did not pause: {created}")
    checks.append("n8n manual intake webhook")

    approval = request_json("POST", n8n_url, "/webhook/wamocon-marketing/approve-content", make_approval_payload(content_id))
    state = approval.get("state", {})
    assert_true(state.get("next_step") == "scheduler", f"n8n approval did not advance: {approval}")
    assert_true(state.get("brief", {}).get("status") == "ready_to_schedule", f"n8n approval status wrong: {approval}")
    checks.append("n8n approval webhook")

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the WAMOCON Marketing-Maschine API and optional n8n webhooks.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8117", help="Marketing agent base URL.")
    parser.add_argument("--n8n-url", default="", help="Optional n8n base URL for webhook checks.")
    args = parser.parse_args()

    stamp = int(time.time())
    checks = test_agent_api(args.base_url, stamp)
    if args.n8n_url:
        checks.extend(test_n8n_webhooks(args.n8n_url, stamp))

    print(json.dumps({"status": "ok", "checks": checks}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(1)
