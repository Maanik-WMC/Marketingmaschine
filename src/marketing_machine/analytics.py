from __future__ import annotations

from dataclasses import dataclass

from .schemas import OptimizationAction, PerformanceRecord


@dataclass
class OptimizationDecision:
    action: OptimizationAction
    reason: str


def evaluate_performance(record: PerformanceRecord) -> OptimizationDecision:
    if record.review_window == "72h":
        if record.impressions < 250 and record.clicks == 0 and record.comments_from_target_buyers == 0:
            return OptimizationDecision(OptimizationAction.ITERATE, "weak early signal; test stronger hook or thumbnail")
        return OptimizationDecision(OptimizationAction.WAIT_FOR_MORE_DATA, "early signal exists; wait for weekly read")

    if record.review_window in {"7d", "14d"}:
        if record.clicks > 0 and record.leads == 0:
            return OptimizationDecision(OptimizationAction.FIX_LANDING_PAGE, "clicks without leads indicate landing-page or offer friction")
        if record.comments_from_target_buyers == 0 and record.leads == 0 and record.impressions >= 1000:
            return OptimizationDecision(OptimizationAction.FIX_AUDIENCE_OR_OFFER, "reach without buyer signal indicates audience or offer mismatch")
        if record.qualified_leads > 0 or record.booked_calls > 0:
            return OptimizationDecision(OptimizationAction.SCALE, "qualified commercial signal detected")
        if record.review_window == "14d":
            return OptimizationDecision(OptimizationAction.STOP, "no useful business signal after 14 days")

    if record.review_window == "30d":
        if record.qualified_leads >= 3 or record.booked_calls >= 1 or record.pipeline_value_eur > 0:
            return OptimizationDecision(OptimizationAction.SCALE, "30-day business value threshold met")
        return OptimizationDecision(OptimizationAction.STOP, "30-day test did not produce qualified business value")

    return OptimizationDecision(OptimizationAction.WAIT_FOR_MORE_DATA, "review window not decisive")
