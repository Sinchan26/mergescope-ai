from pathlib import Path

import pytest
from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import (
    Approval,
    Category,
    ManualReviewRequest,
    PullRequestFile,
    PullRequestSnapshot,
    ReviewIssue,
    ReviewResult,
    ReviewStatus,
    Severity,
)
from mergescope.services.reviews import ReviewService


class FakeGitHub:
    async def fetch_pull_request(self, url: str) -> PullRequestSnapshot:
        return PullRequestSnapshot(
            repository="example/project",
            number=7,
            url=url,
            title="Protect empty input",
            author="developer",
            base_ref="main",
            head_ref="fix/empty-input",
            head_sha="abc123",
            files=[
                PullRequestFile(
                    filename="src/parser.py",
                    status="modified",
                    additions=3,
                    deletions=1,
                    changes=4,
                    patch="@@ -1 +1,3 @@",
                )
            ],
        )


class FakeReviewer:
    async def review(
        self, pull_request: PullRequestSnapshot, ticket_reference: str | None
    ) -> tuple[ReviewResult, int, int, int]:
        return (
            ReviewResult(
                summary="One actionable issue was found.",
                approval=Approval.comment,
                confidence=0.91,
                issues=[
                    ReviewIssue(
                        file_path="src/parser.py",
                        line_number=3,
                        severity=Severity.medium,
                        category=Category.testing,
                        title="Missing regression test",
                        message="The new empty-input behavior is not covered.",
                        evidence="The patch changes the guard without a test file change.",
                        suggestion="Add a test for empty input.",
                    ),
                    ReviewIssue(
                        file_path="invented.py",
                        severity=Severity.high,
                        category=Category.correctness,
                        title="Invented path",
                        message="This must be filtered.",
                        evidence="None.",
                        suggestion="None.",
                    ),
                ],
                positive_notes=["The guard is easy to read."],
                reviewed_files=["src/parser.py"],
                skipped_files=[],
            ),
            120,
            80,
            350,
        )


async def test_manual_review_is_persisted_and_invalid_paths_are_removed(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "reviews.db")
    await repository.initialize()
    service = ReviewService(
        repository=repository,
        github=FakeGitHub(),  # type: ignore[arg-type]
        reviewer=FakeReviewer(),  # type: ignore[arg-type]
        model="test-model",
        dry_run_only=True,
    )

    run = await service.run_manual_review(
        ManualReviewRequest(
            pr_url="https://github.com/example/project/pull/7",
            ticket_reference="LOCAL-7",
        )
    )

    assert run.status is ReviewStatus.completed
    assert run.repository == "example/project"
    assert run.issue_count == 1
    assert run.result is not None
    assert run.result.issues[0].file_path == "src/parser.py"
    assert (await repository.get(run.id)).status is ReviewStatus.completed  # type: ignore[union-attr]


async def test_openai_key_is_required_before_a_run_is_created(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "reviews.db")
    await repository.initialize()
    service = ReviewService(
        repository=repository,
        github=FakeGitHub(),  # type: ignore[arg-type]
        reviewer=None,
        model="test-model",
        dry_run_only=True,
    )

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        await service.run_manual_review(
            ManualReviewRequest(pr_url="https://github.com/example/project/pull/7")
        )

    assert (await repository.list()).total == 0
