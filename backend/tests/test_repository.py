from pathlib import Path

from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import PublicationStatus, ReviewRun, ReviewStatus


async def test_review_run_round_trip(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "reviews.db")
    await repository.initialize()
    run = ReviewRun(
        id="review-1",
        pr_url="https://github.com/example/project/pull/7",
        status=ReviewStatus.queued,
        dry_run=True,
        ticket_reference="LOCAL-7",
    )

    await repository.create(run)
    saved = await repository.get(run.id)

    assert saved is not None
    assert saved.id == "review-1"
    assert saved.ticket_reference == "LOCAL-7"
    assert (await repository.list()).total == 1


async def test_publication_claim_is_atomic(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "reviews.db")
    await repository.initialize()
    run = ReviewRun(
        id="review-publish-claim",
        pr_url="https://github.com/example/project/pull/7",
        status=ReviewStatus.completed,
        dry_run=True,
    )
    await repository.create(run)

    first = await repository.begin_publication(run.id)
    second = await repository.begin_publication(run.id)

    assert first is not None
    assert first.publication_status is PublicationStatus.publishing
    assert second is None
