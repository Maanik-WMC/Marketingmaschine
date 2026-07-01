import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.analytics import evaluate_performance
from marketing_machine.schemas import OptimizationAction, PerformanceRecord


class AnalyticsTests(unittest.TestCase):
    def test_clicks_without_leads_fix_landing_page(self):
        decision = evaluate_performance(
            PerformanceRecord(content_id="c1", review_window="7d", impressions=1000, clicks=50, leads=0)
        )
        self.assertEqual(decision.action, OptimizationAction.FIX_LANDING_PAGE)

    def test_qualified_lead_scales(self):
        decision = evaluate_performance(
            PerformanceRecord(content_id="c1", review_window="14d", impressions=1000, clicks=20, leads=2, qualified_leads=1)
        )
        self.assertEqual(decision.action, OptimizationAction.SCALE)

    def test_no_signal_after_14_days_stops(self):
        decision = evaluate_performance(
            PerformanceRecord(content_id="c1", review_window="14d", impressions=100, clicks=0, leads=0)
        )
        self.assertEqual(decision.action, OptimizationAction.STOP)


if __name__ == "__main__":
    unittest.main()
