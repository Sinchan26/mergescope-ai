from pathlib import Path

from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import ReviewRun, ReviewStatus


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
