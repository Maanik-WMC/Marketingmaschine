from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .content_generator import generate_public_copy
from .evidence import EvidenceVault
from .governance import AuditTrail, GovernancePolicy, PolicyAction
from .schemas import ApprovalRecord, ContentBrief, ContentStatus, ReviewDecision


@dataclass
class WorkflowState:
    brief: ContentBrief
    approval: ApprovalRecord | None = None
    errors: list[str] = field(default_factory=list)
    next_step: str = "orchestrator"
    requires_human_review: bool = False
    evidence_records: list[dict[str, object]] = field(default_factory=list)
    scheduler_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "brief": self.brief.to_dict(),
            "approval": self.approval.to_dict() if self.approval else None,
            "errors": self.errors,
            "next_step": self.next_step,
            "requires_human_review": self.requires_human_review,
            "evidence_records": self.evidence_records,
            "scheduler_payload": self.scheduler_payload,
        }


class MarketingWorkflow:
    """Deterministic workflow skeleton matching the planned LangGraph graph."""

    def __init__(
        self,
        policy: GovernancePolicy,
        audit: AuditTrail | None = None,
        evidence_vault: EvidenceVault | None = None,
    ) -> None:
        self.policy = policy
        self.audit = audit or AuditTrail()
        self.evidence_vault = evidence_vault

    def run_until_review(self, brief: ContentBrief) -> WorkflowState:
        state = WorkflowState(brief=brief)
        self._orchestrator(state)
        if state.errors:
            return state
        self._evidence_gate(state)
        if state.errors:
            return state
        self._draft_content(state)
        self._compliance_gate(state)
        return state

    def resume_after_review(self, state: WorkflowState, approval: ApprovalRecord) -> WorkflowState:
        state.approval = approval
        self.audit.log("compliance", "write_approval_record", PolicyAction.ALLOW.value, self.policy.name)
        if approval.is_publishable:
            state.brief.status = ContentStatus.READY_TO_SCHEDULE
            state.requires_human_review = False
            state.next_step = "scheduler"
            self._create_scheduler_payload(state)
            return state

        state.requires_human_review = False
        state.next_step = "revision"
        if approval.decision == ReviewDecision.REJECTED:
            state.brief.status = ContentStatus.BLOCKED
        else:
            state.brief.status = ContentStatus.REVISION_REQUESTED
        state.errors.append("human review did not approve publication")
        return state

    def _orchestrator(self, state: WorkflowState) -> None:
        decision = self.policy.check_tool("write_content_brief")
        self.audit.log("orchestrator", "write_content_brief", decision.action.value, self.policy.name, reason=decision.reason)
        if decision.action == PolicyAction.DENY:
            state.errors.append(decision.reason)
            state.brief.status = ContentStatus.BLOCKED
            return
        validation_errors = state.brief.validate()
        if validation_errors:
            state.errors.extend(validation_errors)
            state.brief.status = ContentStatus.BLOCKED
            return
        state.next_step = "evidence_gate"

    def _evidence_gate(self, state: WorkflowState) -> None:
        if not state.brief.proof_sources:
            state.errors.append("content cannot proceed without proof sources")
            state.brief.status = ContentStatus.NEEDS_EVIDENCE
            return
        if self.evidence_vault is not None:
            evidence_errors = self.evidence_vault.validate_proof_sources(state.brief.proof_sources)
            if evidence_errors:
                state.errors.extend(evidence_errors)
                state.brief.status = ContentStatus.BLOCKED
                state.next_step = "blocked"
                return
            state.evidence_records = self.evidence_vault.records_for(state.brief.proof_sources)
        self.audit.log("evidence-vault", "read_evidence_vault", PolicyAction.ALLOW.value, self.policy.name)
        state.next_step = "draft_content"

    def _draft_content(self, state: WorkflowState) -> None:
        generated = generate_public_copy(state.brief)
        state.brief.public_copy = generated.public_copy
        state.brief.review_notes = generated.review_notes
        state.brief.draft = (
            f"{generated.public_copy}\n\n"
            "Internal review notes:\n"
            + "\n".join(f"- {note}" for note in generated.review_notes)
        )
        state.brief.status = ContentStatus.DRAFTING
        state.next_step = "compliance_gate"
        self.audit.log("campaign-agent", "write_draft", PolicyAction.ALLOW.value, self.policy.name)

    def _compliance_gate(self, state: WorkflowState) -> None:
        content_decision = self.policy.check_content(state.brief.draft)
        self.audit.log("compliance", "write_approval_record", content_decision.action.value, self.policy.name, reason=content_decision.reason)
        if content_decision.action == PolicyAction.DENY:
            state.errors.append(content_decision.reason)
            state.brief.status = ContentStatus.BLOCKED
            state.next_step = "blocked"
            return
        brief_decision = self.policy.check_brief(state.brief)
        if brief_decision.action == PolicyAction.DENY:
            state.errors.append(brief_decision.reason)
            state.brief.status = ContentStatus.BLOCKED
            state.next_step = "blocked"
            return
        state.brief.status = ContentStatus.NEEDS_HUMAN_REVIEW
        state.requires_human_review = True
        state.next_step = "human_review"

    def _create_scheduler_payload(self, state: WorkflowState) -> None:
        decision = self.policy.check_tool("create_scheduler_payload")
        self.audit.log("scheduler", "create_scheduler_payload", decision.action.value, self.policy.name, reason=decision.reason)
        if decision.action == PolicyAction.DENY:
            state.errors.append(decision.reason)
            state.brief.status = ContentStatus.BLOCKED
            return
        state.scheduler_payload = {
            "content_id": state.brief.id,
            "campaign": state.brief.campaign,
            "channel": state.brief.channel,
            "format": state.brief.format,
            "status": "draft_only_requires_final_platform_approval",
            "utm": state.brief.utm,
            "copy": state.brief.public_copy or state.brief.draft,
            "review_notes": state.brief.review_notes,
            "evidence_records": state.evidence_records,
            "postiz_mode": "draft_only",
        }


def build_langgraph_app(policy: GovernancePolicy) -> Any:
    """Build the production LangGraph app when langgraph is installed.

    The stdlib workflow above keeps local tests dependency-free. Production deploys
    should install the `prod` extras and use this function for durable execution.
    """

    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError("Install production dependencies with `pip install -e .[prod]` to use LangGraph") from exc

    graph = StateGraph(dict)
    workflow = MarketingWorkflow(policy)

    def run_until_review_node(state: dict[str, Any]) -> dict[str, Any]:
        brief = state["brief"]
        result = workflow.run_until_review(brief)
        return result.to_dict()

    graph.add_node("run_until_review", run_until_review_node)
    graph.add_edge(START, "run_until_review")
    graph.add_edge("run_until_review", END)
    return graph.compile()
