from uuid import uuid4

from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import ManualReviewRequest, ReviewRun, ReviewStatus
from mergescope.integrations.github import GitHubClient
from mergescope.integrations.openai_review import OpenAIReviewer


class ReviewService:
    def __init__(
        self,
        repository: ReviewRepository,
        github: GitHubClient,
        reviewer: OpenAIReviewer | None,
        model: str,
        dry_run_only: bool,
    ) -> None:
        self.repository = repository
        self.github = github
        self.reviewer = reviewer
        self.model = model
        self.dry_run_only = dry_run_only

    async def run_manual_review(self, request: ManualReviewRequest) -> ReviewRun:
        if self.dry_run_only and not request.dry_run:
            raise ValueError("This milestone only supports dry-run reviews.")
        if self.reviewer is None:
            raise ValueError("OPENAI_API_KEY is not configured on the server.")

        run = ReviewRun(
            id=str(uuid4()),
            pr_url=str(request.pr_url),
            status=ReviewStatus.queued,
            dry_run=True,
            ticket_reference=request.ticket_reference or None,
            model=self.model,
        )
        await self.repository.create(run)

        try:
            run.status = ReviewStatus.running
            await self.repository.save(run)
            pull_request = await self.github.fetch_pull_request(run.pr_url)
            run.repository = pull_request.repository
            run.pr_number = pull_request.number
            run.head_sha = pull_request.head_sha
            run.title = pull_request.title
            run.author = pull_request.author

            result, input_tokens, output_tokens, latency_ms = await self.reviewer.review(
                pull_request, run.ticket_reference
            )
            changed_paths = {file.filename for file in pull_request.files}
            result.issues = [issue for issue in result.issues if issue.file_path in changed_paths]
            run.result = result
            run.issue_count = len(result.issues)
            run.input_tokens = input_tokens
            run.output_tokens = output_tokens
            run.latency_ms = latency_ms
            run.status = ReviewStatus.completed
            await self.repository.save(run)
            return run
        except Exception as exc:
            run.status = ReviewStatus.failed
            run.error_message = str(exc)
            await self.repository.save(run)
            raise
