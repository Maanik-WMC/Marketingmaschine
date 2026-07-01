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
        headers={"Content-Type": "application/json", "User-Agent": "wamocon-mock-pipeline-test/0.1"},
        method=method,
    )
    try:
        with urlopen(request, timeout=25) as response:
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


def content_payload(content_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": content_id,
        "campaign": "Mock QA Risk Audit",
        "persona": "IT-Leiter Thomas",
        "channel": "LinkedIn",
        "format": "expert_post",
        "language": "de-DE",
        "objective": "Den gesteuerten Content-Workflow mit einem QA-Risikoaudit prüfen.",
        "cta": "QA-Risikoaudit anfragen",
        "proof_sources": ["Kampagnen/kampagne_1_consulting_qa.json"],
        "utm": {
            "utm_source": "linkedin",
            "utm_medium": "organic",
            "utm_campaign": "mock_qa_risk_audit",
        },
        "hypothesis": "Nachweisbasierter QA-Content erzeugt qualifizierte Anfragen von IT-Leitern.",
        "test_variable": "mock_edge_case",
    }
    payload.update(overrides)
    return payload


def approval_payload(content_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content_id": content_id,
        "reviewer": "mock-test",
        "decision": "approved",
        "brand_score": 95,
        "fact_check_passed": True,
        "privacy_check_passed": True,
        "ai_disclosure_check_passed": True,
        "notes": "Mock approval. Scheduler must still keep draft-only final approval guard.",
    }
    payload.update(overrides)
    return payload


def lead_payload(content_id: str, lead_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": lead_id,
        "source_content_id": content_id,
        "campaign": "Mock QA Risk Audit",
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
            "utm_campaign": "mock_qa_risk_audit",
        },
    }
    payload.update(overrides)
    return payload


def state_url(base_url: str, content_id: str) -> str:
    return f"{base_url.rstrip('/')}/workflows/states/{content_id}"


def run(base_url: str, n8n_url: str = "") -> dict[str, Any]:
    stamp = int(time.time())
    checks: list[str] = []
    created_ids: list[str] = []
    created_lead_ids: list[str] = []

    integrations = request_json("GET", base_url, "/integrations/status")
    assert_true(integrations.get("status") == "ok", f"required integrations are not ok: {integrations}")
    optional = {item["name"]: item for item in integrations.get("optional", [])}
    for name in ("postiz", "twenty", "mautic"):
        assert_true(optional.get(name, {}).get("ok") is True, f"{name} is not available: {optional.get(name)}")
    checks.append("required and growth-tool integrations")

    missing_proof = request_json(
        "POST",
        base_url,
        "/workflows/create-content",
        content_payload(f"mock-missing-proof-{stamp}", proof_sources=[]),
    )
    created_ids.append(f"mock-missing-proof-{stamp}")
    assert_true(missing_proof["state"]["brief"]["status"] == "blocked", f"missing proof was not blocked: {missing_proof}")
    checks.append("missing proof source is blocked")

    hashtag_spam = request_json(
        "POST",
        base_url,
        "/workflows/create-content",
        content_payload(
            f"mock-hashtag-spam-{stamp}",
            channel="Instagram",
            hashtags=["qa", "ki", "b2b", "testing", "automation", "software"],
            utm={"utm_source": "instagram", "utm_medium": "organic", "utm_campaign": "mock_ig"},
        ),
    )
    created_ids.append(f"mock-hashtag-spam-{stamp}")
    assert_true(hashtag_spam["state"]["brief"]["status"] == "blocked", f"hashtag spam was not blocked: {hashtag_spam}")
    checks.append("instagram hashtag spam is blocked")

    weak_id = f"mock-weak-approval-{stamp}"
    created_ids.append(weak_id)
    weak_created = request_json("POST", base_url, "/workflows/create-content", content_payload(weak_id))
    assert_true(weak_created["state"]["next_step"] == "human_review", f"weak approval setup failed: {weak_created}")
    weak_approval = request_json("POST", base_url, "/workflows/approve-content", approval_payload(weak_id, brand_score=89))
    assert_true(weak_approval["state"]["next_step"] == "revision", f"weak approval reached scheduler: {weak_approval}")
    assert_true(not weak_approval["state"].get("scheduler_payload"), f"weak approval created scheduler payload: {weak_approval}")
    checks.append("weak approval cannot schedule")

    approved_id = f"mock-approved-{stamp}"
    created_ids.append(approved_id)
    approved_created = request_json("POST", base_url, "/workflows/create-content", content_payload(approved_id))
    assert_true(approved_created["state"]["next_step"] == "human_review", f"approval setup failed: {approved_created}")
    approved = request_json("POST", base_url, "/workflows/approve-content", approval_payload(approved_id))
    assert_true(approved["state"]["next_step"] == "scheduler", f"approved content did not reach scheduler: {approved}")
    assert_true(
        approved["state"]["scheduler_payload"]["status"] == "draft_only_requires_final_platform_approval",
        f"scheduler final approval guard missing: {approved}",
    )
    assert_true(
        "LinkedIn-Entwurf" in approved["state"]["scheduler_payload"].get("copy", ""),
        f"approved scheduler payload does not contain generated German public copy: {approved}",
    )
    assert_true(
        bool(approved["state"]["scheduler_payload"].get("evidence_records")),
        f"approved scheduler payload does not contain proof metadata: {approved}",
    )
    checks.append("approved content creates guarded scheduler payload")
    checks.append("generated public copy is visible in scheduler draft")

    postiz_route = request_json(
        "POST",
        base_url,
        "/workflows/route-scheduler-draft",
        {"content_id": approved_id, "target": "postiz", "dry_run": True},
    )
    assert_true(postiz_route.get("status") == "prepared", f"Postiz draft route was not prepared: {postiz_route}")
    assert_true(postiz_route.get("route", {}).get("payload", {}).get("status") == "draft", f"Postiz route payload is not draft: {postiz_route}")
    checks.append("approved draft is prepared for Postiz through dry-run outbox")

    blocked_postiz_route = request_json(
        "POST",
        base_url,
        "/workflows/route-scheduler-draft",
        {"content_id": weak_id, "target": "postiz", "dry_run": True},
    )
    assert_true(blocked_postiz_route.get("status") == "blocked", f"weak content route was not blocked: {blocked_postiz_route}")
    checks.append("unapproved draft cannot route to Postiz")

    scored_lead_id = f"mock-lead-{stamp}"
    created_lead_ids.append(scored_lead_id)
    scored_lead = request_json("POST", base_url, "/workflows/lead-intake", lead_payload(approved_id, scored_lead_id))
    assert_true(scored_lead.get("status") == "accepted", f"lead intake failed: {scored_lead}")
    assert_true(scored_lead.get("routing_allowed") is True, f"qualified lead did not route: {scored_lead}")
    assert_true(scored_lead.get("lead", {}).get("next_action") == "sales_follow_up", f"qualified lead action wrong: {scored_lead}")
    assert_true(scored_lead.get("lead", {}).get("qualification_score", 0) >= 75, f"qualified lead score too low: {scored_lead}")
    assert_true(bool(scored_lead.get("crm_payload")), f"CRM payload missing for qualified lead: {scored_lead}")
    checks.append("qualified lead is scored and prepared for CRM follow-up")

    twenty_route = request_json(
        "POST",
        base_url,
        "/workflows/route-lead",
        {"lead_id": scored_lead_id, "target": "twenty", "dry_run": True},
    )
    assert_true(twenty_route.get("status") == "prepared", f"Twenty route was not prepared: {twenty_route}")
    assert_true(twenty_route.get("route", {}).get("payload", {}).get("external_id") == scored_lead_id, f"Twenty payload missing lead ID: {twenty_route}")
    checks.append("qualified lead is prepared for Twenty through dry-run outbox")

    no_consent_lead_id = f"mock-lead-no-consent-{stamp}"
    created_lead_ids.append(no_consent_lead_id)
    no_consent = request_json(
        "POST",
        base_url,
        "/workflows/lead-intake",
        lead_payload(approved_id, no_consent_lead_id, consent_given=False),
    )
    assert_true(no_consent.get("status") == "accepted", f"no-consent lead was not accepted for audit: {no_consent}")
    assert_true(no_consent.get("routing_allowed") is False, f"no-consent lead routed incorrectly: {no_consent}")
    assert_true(no_consent.get("lead", {}).get("next_action") == "consent_required", f"no-consent action wrong: {no_consent}")
    assert_true(no_consent.get("crm_payload") == {}, f"no-consent CRM payload should be empty: {no_consent}")
    checks.append("missing consent blocks CRM and marketing routing")

    blocked_lead_route = request_json(
        "POST",
        base_url,
        "/workflows/route-lead",
        {"lead_id": no_consent_lead_id, "target": "twenty", "dry_run": True},
    )
    assert_true(blocked_lead_route.get("status") == "blocked", f"no-consent lead route was not blocked: {blocked_lead_route}")
    checks.append("no-consent lead cannot route to Twenty")

    analytics_cases = [
        (
            "72h weak signal iterates",
            {"review_window": "72h", "impressions": 120, "clicks": 0, "comments_from_target_buyers": 0},
            "iterate",
        ),
        (
            "7d clicks without leads fixes landing page",
            {"review_window": "7d", "impressions": 1200, "clicks": 50, "leads": 0},
            "fix_landing_page",
        ),
        (
            "14d reach without buyer signal fixes audience or offer",
            {"review_window": "14d", "impressions": 1500, "clicks": 0, "leads": 0, "comments_from_target_buyers": 0},
            "fix_audience_or_offer",
        ),
        (
            "30d qualified signal scales",
            {"review_window": "30d", "impressions": 2000, "qualified_leads": 3},
            "scale",
        ),
        (
            "30d no business value stops",
            {"review_window": "30d", "impressions": 2000, "qualified_leads": 0, "booked_calls": 0},
            "stop",
        ),
    ]
    for label, payload, expected in analytics_cases:
        result = request_json("POST", base_url, "/workflows/analytics-review", {"content_id": approved_id, **payload})
        assert_true(result.get("action") == expected, f"{label} expected {expected}, got {result}")
        checks.append(label)

    if n8n_url:
        n8n_id = f"mock-n8n-{stamp}"
        created_ids.append(n8n_id)
        intake = request_json("POST", n8n_url, "/webhook/wamocon-marketing/content-intake", content_payload(n8n_id))
        assert_true(intake["state"]["next_step"] == "human_review", f"n8n intake did not pause: {intake}")
        n8n_approval = request_json("POST", n8n_url, "/webhook/wamocon-marketing/approve-content", approval_payload(n8n_id))
        assert_true(n8n_approval["state"]["next_step"] == "scheduler", f"n8n approval did not schedule: {n8n_approval}")
        checks.append("n8n manual intake and approval webhooks")

    return {
        "checks": checks,
        "created_content_ids": created_ids,
        "created_lead_ids": created_lead_ids,
        "fresh_result_urls": {content_id: state_url(base_url, content_id) for content_id in created_ids},
        "lead_list_url": f"{base_url.rstrip('/')}/workflows/leads",
        "outbox_url": f"{base_url.rstrip('/')}/workflows/outbox",
        "ui_url": f"{base_url.rstrip('/')}/ui",
        "approved_content_id": approved_id,
        "approved_state_url": state_url(base_url, approved_id),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run mock edge-case tests against the deployed WAMOCON pipeline.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8117")
    parser.add_argument("--n8n-url", default="")
    args = parser.parse_args()

    result = run(args.base_url, args.n8n_url)
    print(json.dumps({"status": "ok", **result}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(1)
