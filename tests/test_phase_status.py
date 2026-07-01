import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.phases import build_phase_status


class PhaseStatusTests(unittest.TestCase):
    def test_phase_status_marks_core_operational_and_write_planes_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflows = Path(tmp)
            for name in ("analytics-72h.json", "analytics-7d.json", "analytics-14d.json", "analytics-30d.json"):
                (workflows / name).write_text("{}", encoding="utf-8")
            integrations = {
                "status": "ok",
                "checks": [
                    {"name": "ollama", "ok": True},
                    {"name": "local_openai", "ok": True},
                    {"name": "kimi", "ok": False, "configured": True},
                ],
            }

            result = build_phase_status(
                integrations=integrations,
                env={"MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "false"},
                workflows_dir=workflows,
            )

        self.assertEqual(result["status"], "operational_with_blockers")
        phases = {phase["id"]: phase for phase in result["phases"]}
        self.assertEqual(phases["02_model_plane"]["status"], "complete")
        self.assertEqual(phases["06_n8n_rhythm"]["status"], "complete")
        self.assertEqual(phases["08_lead_plane"]["status"], "partial")
        self.assertEqual(phases["09_publishing_plane"]["status"], "partial")
        self.assertFalse(phases["03_cloud_backup"]["critical"])

    def test_n8n_analytics_phase_files_exist_and_target_all_review_windows(self):
        root = Path(__file__).resolve().parents[1]
        expected = {
            "analytics-72h.json": "72h",
            "analytics-7d.json": "7d",
            "analytics-14d.json": "14d",
            "analytics-30d.json": "30d",
        }

        for filename, review_window in expected.items():
            with self.subTest(filename=filename):
                path = root / "deploy" / "n8n" / "workflows" / filename
                data = json.loads(path.read_text(encoding="utf-8"))
                encoded = json.dumps(data)
                self.assertIn("/workflows/analytics-review", encoded)
                self.assertIn(review_window, encoded)


if __name__ == "__main__":
    unittest.main()
