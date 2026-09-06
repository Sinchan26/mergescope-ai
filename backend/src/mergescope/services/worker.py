import asyncio
import logging

from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import ManualReviewRequest, ReviewJob, TriggerSource
from mergescope.services.reviews import ReviewService, StalePullRequestError

logger = logging.getLogger(__name__)


class ReviewWorker:
    def __init__(
        self,
        *,
        repository: ReviewRepository,
        review_service: ReviewService,
        poll_seconds: float,
        lease_seconds: int,
    ) -> None:
        self.repository = repository
        self.review_service = review_service
        self.poll_seconds = poll_seconds
        self.lease_seconds = lease_seconds
        self._wake = asyncio.Event()

    def notify(self) -> None:
        self._wake.set()

    async def run(self) -> None:
        while True:
            job = await self.repository.claim_next_job(self.lease_seconds)
            if job is None:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)
                except TimeoutError:
                    pass
                continue
            await self._process(job)

    async def _process(self, job: ReviewJob) -> None:
        try:
            review = await self.review_service.run_manual_review(
                ManualReviewRequest(pr_url=job.pr_url, force_rereview=False),
                expected_head_sha=job.head_sha,
                installation_id=job.installation_id,
                trigger_source=TriggerSource.webhook,
                job_id=job.id,
            )
            await self.repository.complete_job(job.id, review.id)
        except StalePullRequestError as exc:
            await self.repository.supersede_job(job.id, str(exc))
        except asyncio.CancelledError:
            await asyncio.shield(
                self.repository.fail_job(job, "Worker stopped before completion.", retryable=True)
            )
            raise
        except ValueError as exc:
            await self.repository.fail_job(job, str(exc), retryable=False)
        except Exception as exc:
            status = await self.repository.fail_job(job, str(exc), retryable=True)
            logger.warning("Review job %s moved to %s: %s", job.id, status, exc)
