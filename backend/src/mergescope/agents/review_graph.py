from typing import Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from mergescope.domain.models import (
    AgentReview,
    AgentRole,
    Approval,
    ContextSource,
    PullRequestSnapshot,
    ReviewPolicy,
    ReviewResult,
    SecurityReviewMode,
    SynthesizedReview,
)
from mergescope.services.diff_parser import ParsedPatch, validate_findings


class ReviewerClient(Protocol):
    async def review_as(
        self,
        role: AgentRole,
        pull_request: PullRequestSnapshot,
        context_sources: list[ContextSource],
        parsed_patches: dict[str, ParsedPatch],
        ticket_reference: str | None,
    ) -> tuple[AgentReview, int | None, int | None, int]: ...

    async def synthesize(
        self,
        pull_request: PullRequestSnapshot,
        reviews: dict[AgentRole, AgentReview],
    ) -> tuple[SynthesizedReview, int | None, int | None, int]: ...


class ReviewGraphState(TypedDict, total=False):
    pull_request: PullRequestSnapshot
    context_sources: list[ContextSource]
    parsed_patches: dict[str, ParsedPatch]
    ticket_reference: str | None
    agent_reviews: dict[AgentRole, AgentReview]
    synthesis: SynthesizedReview
    result: ReviewResult
    agents_run: list[AgentRole]
    input_tokens: int
    output_tokens: int
    latency_ms: int
    policy: ReviewPolicy


class ReviewOrchestrator:
    def __init__(self, client: ReviewerClient) -> None:
        self.client = client
        builder = StateGraph(ReviewGraphState)
        builder.add_node("code_reviewer", self._code_reviewer)
        builder.add_node("security_reviewer", self._security_reviewer)
        builder.add_node("testing_reviewer", self._testing_reviewer)
        builder.add_node("synthesizer", self._synthesizer)
        builder.add_node("validator", self._validator)
        builder.add_edge(START, "code_reviewer")
        builder.add_conditional_edges(
            "code_reviewer",
            self._after_code,
            {
                "security_reviewer": "security_reviewer",
                "testing_reviewer": "testing_reviewer",
                "synthesizer": "synthesizer",
            },
        )
        builder.add_conditional_edges(
            "security_reviewer",
            self._after_security,
            {"testing_reviewer": "testing_reviewer", "synthesizer": "synthesizer"},
        )
        builder.add_edge("testing_reviewer", "synthesizer")
        builder.add_edge("synthesizer", "validator")
        builder.add_edge("validator", END)
        self.graph = builder.compile()

    async def run(
        self,
        pull_request: PullRequestSnapshot,
        context_sources: list[ContextSource],
        parsed_patches: dict[str, ParsedPatch],
        ticket_reference: str | None,
        policy: ReviewPolicy | None = None,
    ) -> tuple[ReviewResult, int, int, int]:
        state = await self.graph.ainvoke(
            {
                "pull_request": pull_request,
                "context_sources": context_sources,
                "parsed_patches": parsed_patches,
                "ticket_reference": ticket_reference,
                "agent_reviews": {},
                "agents_run": [],
                "input_tokens": 0,
                "output_tokens": 0,
                "latency_ms": 0,
                "policy": policy or ReviewPolicy(),
            }
        )
        return (
            state["result"],
            state["input_tokens"],
            state["output_tokens"],
            state["latency_ms"],
        )

    async def _code_reviewer(self, state: ReviewGraphState) -> ReviewGraphState:
        return await self._run_reviewer(state, AgentRole.code)

    async def _security_reviewer(self, state: ReviewGraphState) -> ReviewGraphState:
        return await self._run_reviewer(state, AgentRole.security)

    async def _testing_reviewer(self, state: ReviewGraphState) -> ReviewGraphState:
        return await self._run_reviewer(state, AgentRole.testing)

    async def _run_reviewer(self, state: ReviewGraphState, role: AgentRole) -> ReviewGraphState:
        review, input_tokens, output_tokens, latency_ms = await self.client.review_as(
            role,
            state["pull_request"],
            state["context_sources"],
            state["parsed_patches"],
            state["ticket_reference"],
        )
        reviews = dict(state["agent_reviews"])
        reviews[role] = review
        return {
            "agent_reviews": reviews,
            "agents_run": [*state["agents_run"], role],
            "input_tokens": state["input_tokens"] + (input_tokens or 0),
            "output_tokens": state["output_tokens"] + (output_tokens or 0),
            "latency_ms": state["latency_ms"] + latency_ms,
        }

    def _after_code(
        self, state: ReviewGraphState
    ) -> Literal["security_reviewer", "testing_reviewer", "synthesizer"]:
        policy = state["policy"]
        if policy.security_review is SecurityReviewMode.always:
            return "security_reviewer"
        if policy.security_review is SecurityReviewMode.disabled:
            return "testing_reviewer" if policy.testing_review else "synthesizer"
        security_terms = (
            "auth",
            "token",
            "secret",
            "password",
            "permission",
            "sql",
            "query",
            "webhook",
            "crypto",
            "session",
            "cookie",
            "cors",
        )
        security_extensions = {".pem", ".key", ".env"}
        for file in state["pull_request"].files:
            lowered = f"{file.filename}\n{file.patch or ''}".lower()
            if any(term in lowered for term in security_terms):
                return "security_reviewer"
            if any(file.filename.lower().endswith(extension) for extension in security_extensions):
                return "security_reviewer"
        return "testing_reviewer" if policy.testing_review else "synthesizer"

    @staticmethod
    def _after_security(
        state: ReviewGraphState,
    ) -> Literal["testing_reviewer", "synthesizer"]:
        return "testing_reviewer" if state["policy"].testing_review else "synthesizer"

    async def _synthesizer(self, state: ReviewGraphState) -> ReviewGraphState:
        synthesis, input_tokens, output_tokens, latency_ms = await self.client.synthesize(
            state["pull_request"], state["agent_reviews"]
        )
        return {
            "synthesis": synthesis,
            "agents_run": [*state["agents_run"], AgentRole.synthesizer],
            "input_tokens": state["input_tokens"] + (input_tokens or 0),
            "output_tokens": state["output_tokens"] + (output_tokens or 0),
            "latency_ms": state["latency_ms"] + latency_ms,
        }

    def _validator(self, state: ReviewGraphState) -> ReviewGraphState:
        candidates = [
            (role, issue)
            for role, review in state["agent_reviews"].items()
            for issue in review.issues
        ]
        issues, rejected = validate_findings(candidates, state["parsed_patches"])
        policy = state["policy"]
        blocking_severities = set(policy.blocking_severities)
        blocking_categories = set(policy.blocking_categories)
        blocking = any(
            issue.severity in blocking_severities and issue.category in blocking_categories
            for issue in issues
        )
        approval = (
            Approval.request_changes
            if blocking
            else Approval.comment
            if issues
            else Approval.approve
        )
        synthesis = state["synthesis"]
        if synthesis.confidence < policy.minimum_confidence and approval is Approval.approve:
            approval = Approval.comment
        changed_paths = {file.filename for file in state["pull_request"].files}
        reviewed_files = [path for path in synthesis.reviewed_files if path in changed_paths]
        if not reviewed_files:
            reviewed_files = [file.filename for file in state["pull_request"].files if file.patch]
        skipped_files = sorted(
            {file.filename for file in state["pull_request"].files if not file.patch}
            | {path for path in synthesis.skipped_files if path in changed_paths}
        )
        result = ReviewResult(
            summary=synthesis.summary,
            approval=approval,
            confidence=max(0.0, min(1.0, synthesis.confidence)),
            issues=issues,
            positive_notes=synthesis.positive_notes,
            reviewed_files=sorted(set(reviewed_files)),
            skipped_files=skipped_files,
            agents_run=state["agents_run"],
            context_sources=state["context_sources"],
            rejected_issue_count=rejected,
        )
        return {"result": result}
