from mergescope.domain.models import (
    AgentReviewIssue,
    AgentRole,
    Approval,
    Category,
    ContextSource,
    PullRequestFile,
    PullRequestSnapshot,
    ReviewResult,
    Severity,
)
from mergescope.services.diff_parser import parse_pull_request_patches, validate_findings


def demo_pull_request() -> PullRequestSnapshot:
    return PullRequestSnapshot(
        repository="acme/payments-api",
        number=128,
        url="https://github.com/acme/payments-api/pull/128",
        title="Add retry support to payment capture",
        author="demo-developer",
        base_ref="main",
        head_ref="feature/capture-retries",
        head_sha="demo-phase2-sha",
        body="Retries transient capture failures and adds webhook handling.",
        files=[
            PullRequestFile(
                filename="src/payments.py",
                status="modified",
                additions=4,
                deletions=0,
                changes=4,
                patch=(
                    "@@ -40,3 +40,7 @@ async def capture(payload):\n"
                    '     payment_id = payload["payment_id"]\n'
                    "+    for attempt in range(3):\n"
                    "+        result = await provider.capture(payment_id)\n"
                    "+        if result.ok:\n"
                    "+            return result\n"
                    "     raise CaptureError(payment_id)"
                ),
            ),
            PullRequestFile(
                filename="src/webhooks.py",
                status="modified",
                additions=2,
                deletions=0,
                changes=2,
                patch=(
                    "@@ -17,2 +17,4 @@ async def payment_webhook(request):\n"
                    "+    payload = await request.json()\n"
                    "+    await process_event(payload)\n"
                    "     return Response(status_code=204)"
                ),
            ),
        ],
    )


def demo_result(pull_request: PullRequestSnapshot) -> ReviewResult:
    candidates = [
        (
            AgentRole.code,
            AgentReviewIssue(
                file_path="src/payments.py",
                line_number=42,
                severity=Severity.high,
                category=Category.correctness,
                title="Retries repeat a non-idempotent capture",
                message=(
                    "Each attempt can create a second capture when the provider times out after "
                    "success."
                ),
                evidence="The loop retries provider.capture without an idempotency key.",
                suggestion="Generate a stable idempotency key and reuse it across every attempt.",
            ),
        ),
        (
            AgentRole.security,
            AgentReviewIssue(
                file_path="src/webhooks.py",
                line_number=18,
                severity=Severity.high,
                category=Category.security,
                title="Webhook signature is not verified",
                message="Untrusted callers can submit payment events directly to the handler.",
                evidence=(
                    "The added code parses and processes the body before authenticating the sender."
                ),
                suggestion=(
                    "Verify the provider signature against the raw request body "
                    "before parsing JSON."
                ),
            ),
        ),
        (
            AgentRole.testing,
            AgentReviewIssue(
                file_path="src/payments.py",
                line_number=41,
                severity=Severity.medium,
                category=Category.testing,
                title="Retry exhaustion is not covered",
                message=(
                    "The new three-attempt behavior needs a regression test for repeated failures."
                ),
                evidence=(
                    "The implementation adds a retry loop without a corresponding test-file change."
                ),
                suggestion="Assert three calls and the final CaptureError for persistent failures.",
            ),
        ),
    ]
    issues, rejected = validate_findings(candidates, parse_pull_request_patches(pull_request))
    return ReviewResult(
        summary=(
            "The retry and webhook changes introduce two merge-blocking trust-boundary problems "
            "and need targeted regression coverage."
        ),
        approval=Approval.request_changes,
        confidence=0.96,
        issues=issues,
        positive_notes=["The retry count is bounded and the control flow is easy to follow."],
        reviewed_files=[file.filename for file in pull_request.files],
        skipped_files=[],
        agents_run=[
            AgentRole.code,
            AgentRole.security,
            AgentRole.testing,
            AgentRole.synthesizer,
        ],
        context_sources=[
            ContextSource(
                source_id="demo:payments-standard",
                name="Payment Integration Standard.md",
                source_type="knowledge_document",
                excerpt="Capture retries must reuse a stable provider idempotency key.",
                relevance_score=0.94,
            ),
            ContextSource(
                source_id="demo:agents",
                name="AGENTS.md",
                source_type="repository_guidance",
                excerpt="All webhook handlers must validate signatures before parsing payloads.",
                relevance_score=1.0,
            ),
        ],
        rejected_issue_count=rejected,
    )
