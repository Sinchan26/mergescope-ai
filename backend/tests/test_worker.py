from pathlib import Path

from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import JobStatus, ReviewJob, ReviewRun, ReviewStatus
from mergescope.services.reviews import StalePullRequestError
from mergescope.services.worker import ReviewWorker


class FakeReviewService:
    def __init__(self, *, stale: bool = False) -> None:
        self.stale = stale

    async def run_manual_review(self, request, **kwargs):
        if self.stale:
            raise StalePullRequestError("Webhook head was superseded.")
        return ReviewRun(
            id="review-from-worker",
            pr_url=str(request.pr_url),
            status=ReviewStatus.completed,
            dry_run=True,
        )


def job(identifier: str, head_sha: str) -> ReviewJob:
    return ReviewJob(
        id=identifier,
        idempotency_key=f"key-{head_sha}",
        delivery_id=f"delivery-{identifier}",
        repository="example/project",
        pr_number=7,
        pr_url="https://github.com/example/project/pull/7",
        head_sha=head_sha,
    )


async def test_worker_completes_and_supersedes_persisted_jobs(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "reviews.db")
    await repository.initialize()
    first = job("job-1", "head-1")
    await repository.enqueue_webhook_job(first, "pull_request", "synchronize")
    claimed = await repository.claim_next_job(300)
    assert claimed is not None
    worker = ReviewWorker(
        repository=repository,
        review_service=FakeReviewService(),  # type: ignore[arg-type]
        poll_seconds=1,
        lease_seconds=300,
    )

    await worker._process(claimed)

    completed = (await repository.list_jobs()).items[0]
    assert completed.status is JobStatus.completed
    assert completed.review_id == "review-from-worker"

    second = job("job-2", "head-2")
    await repository.enqueue_webhook_job(second, "pull_request", "synchronize")
    stale_claim = await repository.claim_next_job(300)
    assert stale_claim is not None
    stale_worker = ReviewWorker(
        repository=repository,
        review_service=FakeReviewService(stale=True),  # type: ignore[arg-type]
        poll_seconds=1,
        lease_seconds=300,
    )

    await stale_worker._process(stale_claim)

    jobs = {item.id: item for item in (await repository.list_jobs()).items}
    assert jobs["job-2"].status is JobStatus.superseded
