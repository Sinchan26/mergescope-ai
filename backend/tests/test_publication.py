from pathlib import Path

import pytest
from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import PublicationStatus, ReviewRun, ReviewStatus
from mergescope.services.demo import demo_pull_request, demo_result
from mergescope.services.publication import PublicationError, PublicationService


class FakeGitHub:
    def __init__(self, head_sha: str = "demo-phase2-sha") -> None:
        self.head_sha = head_sha

    async def fetch_pull_request(self, url: str):
        pull_request = demo_pull_request()
        pull_request.url = url
        pull_request.head_sha = self.head_sha
        return pull_request


class FakeAppAuth:
    def __init__(self) -> None:
        self.requests = []

    async def request_as_installation(self, method, path, **kwargs):
        self.requests.append((method, path, kwargs))
        if method == "GET":
            return []
        return {"id": 7788}


def completed_review(review_id: str = "review-publish") -> ReviewRun:
    pull_request = demo_pull_request()
    return ReviewRun(
        id=review_id,
        repository=pull_request.repository,
        pr_number=pull_request.number,
        pr_url=pull_request.url,
        head_sha=pull_request.head_sha,
        title=pull_request.title,
        author=pull_request.author,
        status=ReviewStatus.completed,
        dry_run=True,
        result=demo_result(pull_request),
        issue_count=3,
    )


async def test_preview_and_publish_use_only_validated_inline_comments(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "reviews.db")
    await repository.initialize()
    review = completed_review()
    await repository.create(review)
    app_auth = FakeAppAuth()
    service = PublicationService(
        repository=repository,
        github=FakeGitHub(),  # type: ignore[arg-type]
        app_auth=app_auth,  # type: ignore[arg-type]
        publishing_enabled=True,
    )

    preview = service.preview(review)
    result = await service.publish(review.id)
    repeated = await service.publish(review.id)

    assert preview.can_publish is True
    assert len(preview.comments) == 3
    assert all(comment.side == "RIGHT" for comment in preview.comments)
    assert result.status is PublicationStatus.published
    assert result.github_review_id == 7788
    assert repeated.github_review_id == 7788
    assert len(app_auth.requests) == 2
    post_payload = app_auth.requests[1][2]["json"]
    assert post_payload["event"] == "COMMENT"
    assert post_payload["commit_id"] == review.head_sha
    assert "mergescope-review" in post_payload["body"]
    saved = await repository.get(review.id)
    assert saved is not None
    assert saved.publication_status is PublicationStatus.published


async def test_publish_blocks_disabled_demo_and_stale_reviews(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "reviews.db")
    await repository.initialize()
    review = completed_review("stale-review")
    await repository.create(review)
    disabled = PublicationService(
        repository=repository,
        github=FakeGitHub(),  # type: ignore[arg-type]
        app_auth=None,
        publishing_enabled=False,
    )
    assert disabled.preview(review).can_publish is False

    enabled = PublicationService(
        repository=repository,
        github=FakeGitHub("new-head"),  # type: ignore[arg-type]
        app_auth=FakeAppAuth(),  # type: ignore[arg-type]
        publishing_enabled=True,
    )
    with pytest.raises(PublicationError, match="changed"):
        await enabled.publish(review.id)

    saved = await repository.get(review.id)
    assert saved is not None
    assert saved.publication_status is PublicationStatus.stale
