import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.governance import GovernancePolicy
from marketing_machine.routing import route_lead, route_scheduler_draft
from marketing_machine.storage import JsonStore


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JsonStore(Path(self.tmp.name))
        self.policy = GovernancePolicy(
            name="test-policy",
            allowed_tools=["create_postiz_draft", "route_twenty_lead", "route_mautic_lead"],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def save_ready_state(self, content_id="content-1"):
        self.store.save_state(
            {
                "brief": {
                    "id": content_id,
                    "campaign": "K1 QA",
                    "persona": "IT-Leiter Thomas",
                    "channel": "LinkedIn",
                    "format": "expert_post",
                    "status": "ready_to_schedule",
                    "updated_at": "2026-07-01T00:00:00+00:00",
                },
                "next_step": "scheduler",
                "requires_human_review": False,
                "scheduler_payload": {
                    "status": "draft_only_requires_final_platform_approval",
                    "copy": "LinkedIn-Entwurf\n\nTest",
                    "utm": {"utm_source": "linkedin"},
                    "evidence_records": [{"id": "proof-1"}],
                    "postiz_mode": "draft_only",
                },
            }
        )

    def test_scheduler_draft_dry_run_prepares_postiz_payload(self):
        self.save_ready_state()

        result = route_scheduler_draft(store=self.store, policy=self.policy, content_id="content-1")

        self.assertEqual(result["status"], "prepared")
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["target"], "postiz")
        self.assertEqual(result["payload"]["status"], "draft")
        self.assertTrue(result["payload"]["metadata"]["final_platform_approval_required"])

    def test_scheduler_route_blocks_unapproved_content(self):
        self.store.save_state(
            {
                "brief": {
                    "id": "content-2",
                    "campaign": "K1 QA",
                    "persona": "IT-Leiter Thomas",
                    "channel": "LinkedIn",
                    "status": "needs_human_review",
                    "updated_at": "2026-07-01T00:00:00+00:00",
                },
                "next_step": "human_review",
                "requires_human_review": True,
                "scheduler_payload": {},
            }
        )

        result = route_scheduler_draft(store=self.store, policy=self.policy, content_id="content-2")

        self.assertEqual(result["status"], "blocked")
        self.assertIn("not approved", result["reason"])

    def test_lead_dry_run_prepares_twenty_payload(self):
        self.store.append_lead(
            {
                "lead": {"id": "lead-1", "next_action": "sales_follow_up"},
                "routing_allowed": True,
                "crm_payload": {"external_id": "lead-1"},
                "mautic_payload": {"email": "it-leitung@example.com"},
            }
        )

        result = route_lead(store=self.store, policy=self.policy, lead_id="lead-1", target="twenty")

        self.assertEqual(result["status"], "prepared")
        self.assertEqual(result["payload"]["external_id"], "lead-1")

    def test_lead_route_blocks_non_routable_lead(self):
        self.store.append_lead(
            {
                "lead": {"id": "lead-2", "next_action": "consent_required"},
                "routing_allowed": False,
                "crm_payload": {},
                "mautic_payload": {},
            }
        )

        result = route_lead(store=self.store, policy=self.policy, lead_id="lead-2", target="twenty")

        self.assertEqual(result["status"], "blocked")
        self.assertIn("not routable", result["reason"])


if __name__ == "__main__":
    unittest.main()
