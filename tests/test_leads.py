import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.leads import build_lead_intake


def lead_payload(**overrides):
    payload = {
        "id": "lead-1",
        "source_content_id": "mock-approved-1",
        "campaign": "K1 QA Consulting",
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
            "utm_campaign": "k1_qa_risk_audit",
        },
    }
    payload.update(overrides)
    return payload


class LeadIntakeTests(unittest.TestCase):
    def test_verified_consent_lead_is_scored_and_routable(self):
        result = build_lead_intake(lead_payload(), source_verified=True)

        self.assertTrue(result["routing_allowed"])
        self.assertEqual(result["lead"]["next_action"], "sales_follow_up")
        self.assertGreaterEqual(result["lead"]["qualification_score"], 75)
        self.assertEqual(result["crm_payload"]["external_id"], "lead-1")
        self.assertEqual(result["mautic_payload"]["email"], "it-leitung@muster-gmbh.de")

    def test_missing_consent_is_stored_but_not_routed(self):
        result = build_lead_intake(lead_payload(consent_given=False), source_verified=True)

        self.assertFalse(result["routing_allowed"])
        self.assertEqual(result["lead"]["next_action"], "consent_required")
        self.assertEqual(result["crm_payload"], {})
        self.assertIn("consent missing", "; ".join(result["warnings"]))

    def test_unknown_source_requires_manual_source_review(self):
        result = build_lead_intake(lead_payload(), source_verified=False)

        self.assertFalse(result["routing_allowed"])
        self.assertEqual(result["lead"]["next_action"], "manual_source_review")
        self.assertIn("source_content_id was not found", "; ".join(result["warnings"]))

    def test_invalid_email_is_rejected(self):
        with self.assertRaises(ValueError):
            build_lead_intake(lead_payload(email="not-an-email"), source_verified=True)


if __name__ == "__main__":
    unittest.main()
