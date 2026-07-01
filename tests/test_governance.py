import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.governance import GovernancePolicy, PolicyAction
from marketing_machine.schemas import ContentBrief


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.policy = GovernancePolicy.from_json_file(Path(__file__).resolve().parents[1] / "config" / "governance-policy.json")

    def test_blocks_auto_publish(self):
        decision = self.policy.check_tool("auto_publish")
        self.assertEqual(decision.action, PolicyAction.DENY)

    def test_requires_human_approval_for_publish(self):
        decision = self.policy.check_tool("publish_to_postiz")
        self.assertEqual(decision.action, PolicyAction.REVIEW)

    def test_rejects_instagram_hashtag_spam(self):
        brief = ContentBrief(
            id="ig-001",
            campaign="K2",
            persona="GF Markus",
            channel="Instagram",
            format="reel",
            objective="Private-KI-Potenzialanalyse anbieten.",
            cta="Private-KI-Erstgespräch anfragen",
            proof_sources=["evidence"],
            utm={"utm_source": "instagram", "utm_medium": "organic", "utm_campaign": "k2"},
            hypothesis="Datensouveräne KI-Positionierung erzeugt qualifizierte Gespräche.",
            test_variable="hashtags",
            hashtags=["a", "b", "c", "d", "e", "f"],
        )
        self.assertIn("instagram posts must use no more than 5 hashtags", self.policy.check_brief(brief).reason)

    def test_rejects_english_marketing_copy_in_german_brief(self):
        brief = ContentBrief(
            id="de-mixed-001",
            campaign="K1 QA",
            persona="IT-Leiter Thomas",
            channel="LinkedIn",
            format="expert_post",
            objective="Promote a QA Risk Audit with proof-led copy.",
            cta="Book a QA Risk Audit",
            proof_sources=["Kampagnen/kampagne_1_consulting_qa.json"],
            utm={"utm_source": "linkedin", "utm_medium": "organic", "utm_campaign": "k1"},
            hypothesis="Proof-led QA content creates qualified buyer interest.",
            test_variable="offer",
            language="de-DE",
        )

        decision = self.policy.check_brief(brief)

        self.assertEqual(decision.action, PolicyAction.DENY)
        self.assertIn("German brief contains English wording", decision.reason)


if __name__ == "__main__":
    unittest.main()
