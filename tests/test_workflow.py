import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.evidence import EvidenceVault
from marketing_machine.governance import GovernancePolicy
from marketing_machine.schemas import ApprovalRecord, ContentBrief, ContentStatus, ReviewDecision
from marketing_machine.workflow import MarketingWorkflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        policy = GovernancePolicy.from_json_file(root / "config" / "governance-policy.json")
        evidence = EvidenceVault.from_json_file(root / "config" / "evidence-vault.json")
        self.workflow = MarketingWorkflow(policy, evidence_vault=evidence)

    def make_brief(self):
        return ContentBrief(
            id="k1-qa-001",
            campaign="K1 QA",
            persona="IT-Leiter Thomas",
            channel="LinkedIn",
            format="expert_post",
            objective="QA-Risikoaudit mit senioriger Testexpertise anbieten.",
            cta="QA-Risikoaudit anfragen",
            proof_sources=["Kampagnen/kampagne_1_consulting_qa.json"],
            utm={"utm_source": "linkedin", "utm_medium": "organic", "utm_campaign": "k1_qa_audit"},
            hypothesis="Nachweisbasierter QA-Content erzeugt qualifizierte Anfragen von IT-Leitern.",
            test_variable="offer",
        )

    def test_workflow_pauses_for_human_review(self):
        state = self.workflow.run_until_review(self.make_brief())
        self.assertTrue(state.requires_human_review)
        self.assertEqual(state.next_step, "human_review")
        self.assertEqual(state.brief.status, ContentStatus.NEEDS_HUMAN_REVIEW)
        self.assertIn("LinkedIn-Entwurf", state.brief.public_copy)
        self.assertTrue(state.brief.review_notes)

    def test_approved_review_creates_scheduler_payload(self):
        state = self.workflow.run_until_review(self.make_brief())
        approval = ApprovalRecord(
            content_id=state.brief.id,
            reviewer="reviewer@example.invalid",
            decision=ReviewDecision.APPROVED,
            brand_score=95,
            fact_check_passed=True,
            privacy_check_passed=True,
            ai_disclosure_check_passed=True,
        )
        result = self.workflow.resume_after_review(state, approval)
        self.assertEqual(result.brief.status, ContentStatus.READY_TO_SCHEDULE)
        self.assertEqual(result.next_step, "scheduler")
        self.assertEqual(result.scheduler_payload["status"], "draft_only_requires_final_platform_approval")
        self.assertEqual(result.scheduler_payload["copy"], result.brief.public_copy)
        self.assertEqual(result.scheduler_payload["postiz_mode"], "draft_only")
        self.assertEqual(result.scheduler_payload["evidence_records"][0]["id"], "Kampagnen/kampagne_1_consulting_qa.json")

    def test_missing_proof_stops_before_drafting(self):
        brief = self.make_brief()
        brief.proof_sources = []
        state = self.workflow.run_until_review(brief)
        self.assertEqual(state.brief.status, ContentStatus.BLOCKED)
        self.assertIn("at least one proof source is required", state.errors)

    def test_unknown_proof_source_stops_before_drafting(self):
        brief = self.make_brief()
        brief.proof_sources = ["Kampagnen/unapproved_claim.json"]

        state = self.workflow.run_until_review(brief)

        self.assertEqual(state.brief.status, ContentStatus.BLOCKED)
        self.assertIn("proof source is not in approved evidence vault", "; ".join(state.errors))

    def test_weak_approval_routes_to_revision_not_scheduler(self):
        state = self.workflow.run_until_review(self.make_brief())
        approval = ApprovalRecord(
            content_id=state.brief.id,
            reviewer="reviewer@example.invalid",
            decision=ReviewDecision.APPROVED,
            brand_score=89,
            fact_check_passed=True,
            privacy_check_passed=True,
            ai_disclosure_check_passed=True,
        )
        result = self.workflow.resume_after_review(state, approval)
        self.assertEqual(result.brief.status, ContentStatus.REVISION_REQUESTED)
        self.assertEqual(result.next_step, "revision")
        self.assertEqual(result.scheduler_payload, {})

    def test_rejected_approval_blocks_content(self):
        state = self.workflow.run_until_review(self.make_brief())
        approval = ApprovalRecord(
            content_id=state.brief.id,
            reviewer="reviewer@example.invalid",
            decision=ReviewDecision.REJECTED,
            brand_score=95,
            fact_check_passed=True,
            privacy_check_passed=True,
            ai_disclosure_check_passed=True,
        )
        result = self.workflow.resume_after_review(state, approval)
        self.assertEqual(result.brief.status, ContentStatus.BLOCKED)
        self.assertEqual(result.next_step, "revision")
        self.assertEqual(result.scheduler_payload, {})


if __name__ == "__main__":
    unittest.main()
