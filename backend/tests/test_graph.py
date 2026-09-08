from mergescope.agents.review_graph import ReviewOrchestrator
from mergescope.domain.models import (
    AgentReview,
    AgentReviewIssue,
    AgentRole,
    Approval,
    Category,
    PullRequestFile,
    PullRequestSnapshot,
    ReviewPolicy,
    SecurityReviewMode,
    Severity,
    SynthesizedReview,
)
from mergescope.services.diff_parser import parse_pull_request_patches


class FakeReviewClient:
    roles: list[AgentRole]

    def __init__(self) -> None:
        self.roles = []

    async def review_as(
        self, role, pull_request, context_sources, parsed_patches, ticket_reference
    ):
        self.roles.append(role)
        issues = []
        if role is AgentRole.code:
            issues.append(self._issue(999, Severity.medium, Category.correctness, "Outside diff"))
        if role is AgentRole.security:
            issues.append(self._issue(11, Severity.high, Category.security, "Unsafe auth switch"))
        return AgentReview(summary=f"{role} complete", issues=issues, positive_notes=[]), 10, 5, 7

    async def synthesize(self, pull_request, reviews):
        return (
            SynthesizedReview(
                summary="The authentication change needs attention.",
                approval=Approval.approve,
                confidence=1.4,
                positive_notes=[],
                reviewed_files=["src/auth.py", "invented.py"],
                skipped_files=[],
            ),
            8,
            4,
            6,
        )

    @staticmethod
    def _issue(line, severity, category, title):
        return AgentReviewIssue(
            file_path="src/auth.py",
            line_number=line,
            severity=severity,
            category=category,
            title=title,
            message="This changes the authentication boundary.",
            evidence="The new flag disables the secure path.",
            suggestion="Keep secure authentication enabled.",
        )


def pull_request(filename: str = "src/auth.py") -> PullRequestSnapshot:
    return PullRequestSnapshot(
        repository="example/project",
        number=4,
        url="https://github.com/example/project/pull/4",
        title="Change authentication flow",
        author="developer",
        base_ref="main",
        head_ref="feature/auth",
        head_sha="sha-4",
        files=[
            PullRequestFile(
                filename=filename,
                status="modified",
                additions=1,
                deletions=0,
                changes=1,
                patch="@@ -10,2 +10,3 @@\n context\n+secure = False\n old",
            )
        ],
    )


async def test_graph_routes_security_and_validator_owns_final_verdict() -> None:
    client = FakeReviewClient()
    pr = pull_request()

    result, input_tokens, output_tokens, latency_ms = await ReviewOrchestrator(client).run(
        pr, [], parse_pull_request_patches(pr), None
    )

    assert client.roles == [AgentRole.code, AgentRole.security, AgentRole.testing]
    assert result.agents_run == [
        AgentRole.code,
        AgentRole.security,
        AgentRole.testing,
        AgentRole.synthesizer,
    ]
    assert result.approval is Approval.request_changes
    assert result.confidence == 1.0
    assert result.rejected_issue_count == 1
    assert len(result.issues) == 1
    assert result.reviewed_files == ["src/auth.py"]
    assert (input_tokens, output_tokens, latency_ms) == (38, 19, 27)


async def test_graph_skips_security_for_non_sensitive_change() -> None:
    client = FakeReviewClient()
    pr = pull_request("src/format.py")
    pr.title = "Format display name"
    pr.files[0].patch = "@@ -10,2 +10,3 @@\n context\n+name = name.strip()\n old"

    result, *_ = await ReviewOrchestrator(client).run(pr, [], parse_pull_request_patches(pr), None)

    assert client.roles == [AgentRole.code, AgentRole.testing]
    assert AgentRole.security not in result.agents_run


async def test_graph_policy_can_skip_optional_specialists() -> None:
    client = FakeReviewClient()
    pr = pull_request()
    policy = ReviewPolicy(
        security_review=SecurityReviewMode.disabled,
        testing_review=False,
    )

    result, *_ = await ReviewOrchestrator(client).run(
        pr, [], parse_pull_request_patches(pr), None, policy
    )

    assert client.roles == [AgentRole.code]
    assert result.agents_run == [AgentRole.code, AgentRole.synthesizer]
