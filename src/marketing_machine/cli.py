from __future__ import annotations

import json
import sys
from pathlib import Path

from .evidence import EvidenceVault
from .governance import GovernancePolicy
from .schemas import ApprovalRecord, ContentBrief, ReviewDecision
from .storage import JsonStore
from .workflow import MarketingWorkflow


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def demo() -> int:
    policy = GovernancePolicy.from_json_file(repo_root() / "config" / "governance-policy.json")
    evidence = EvidenceVault.from_json_file(repo_root() / "config" / "evidence-vault.json")
    workflow = MarketingWorkflow(policy, evidence_vault=evidence)
    brief = ContentBrief(
        id="demo-k5-app-review-001",
        campaign="K5 App Development",
        persona="IT-Leiter Thomas",
        channel="LinkedIn",
        format="expert_post",
        objective="App-Portfolio als Nachweis für einen App-Modernisierungscheck nutzen.",
        cta="App-Modernisierungscheck anfragen",
        proof_sources=["Kampagnen/kampagne_5_app_entwicklung.json"],
        utm={
            "utm_source": "linkedin",
            "utm_medium": "organic",
            "utm_campaign": "k5_app_review",
        },
        hypothesis="Konkrete App-Beispiele erzeugen bessere B2B-Anfragen als generische Softwaretexte.",
        test_variable="offer",
    )
    state = workflow.run_until_review(brief)
    approval = ApprovalRecord(
        content_id=brief.id,
        reviewer="human-reviewer@example.invalid",
        decision=ReviewDecision.APPROVED,
        brand_score=92,
        fact_check_passed=True,
        privacy_check_passed=True,
        ai_disclosure_check_passed=True,
        notes="Demo approval record.",
    )
    approved_state = workflow.resume_after_review(state, approval)
    print(json.dumps(approved_state.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cleanup_test_data(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    confirmed = "--confirm" in argv and "delete-test-data" in argv
    if not dry_run and not confirmed:
        print(
            json.dumps(
                {
                    "status": "refused",
                    "reason": "pass --confirm delete-test-data to delete mock/smoke test data",
                },
                indent=2,
            )
        )
        return 2
    summary = JsonStore().cleanup_test_data(dry_run=dry_run)
    print(json.dumps({"status": "ok", "summary": summary}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if not argv or argv[0] == "demo":
        return demo()
    if argv[0] == "cleanup-test-data":
        return cleanup_test_data(argv[1:])
    print("Usage: python -m marketing_machine.cli demo|cleanup-test-data", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
