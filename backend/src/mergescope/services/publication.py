from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import (
    PublicationComment,
    PublicationPreview,
    PublicationResult,
    PublicationStatus,
    ReviewRun,
    ReviewStatus,
)
from mergescope.integrations.github import GitHubClient, GitHubError
from mergescope.integrations.github_app import GitHubAppAuth, GitHubAppError
from mergescope.services.policies import PolicyRegistry

MAX_INLINE_COMMENTS = 50


class PublicationError(ValueError):
    pass


class PublicationService:
    def __init__(
        self,
        *,
        repository: ReviewRepository,
        github: GitHubClient,
        app_auth: GitHubAppAuth | None,
        publishing_enabled: bool,
        policies: PolicyRegistry | None = None,
        user_auth=None,
    ) -> None:
        self.repository = repository
        self.github = github
        self.app_auth = app_auth
        self.publishing_enabled = publishing_enabled
        self.policies = policies
        self.user_auth = user_auth

    def preview(self, review: ReviewRun) -> PublicationPreview:
        reasons: list[str] = []
        if review.status is not ReviewStatus.completed or review.result is None:
            reasons.append("The review must complete successfully before publishing.")
        if review.demo_mode:
            reasons.append("Demo reviews cannot be published.")
        if not self.publishing_enabled:
            reasons.append("GitHub publishing is disabled by server configuration.")
        if self.app_auth is None and self.user_auth is None:
            reasons.append("GitHub App authentication is not configured.")
        if not review.repository or review.pr_number is None or not review.head_sha:
            reasons.append("The review is missing GitHub pull-request metadata.")
        max_inline_comments = MAX_INLINE_COMMENTS
        if self.policies and review.repository:
            policy = self.policies.policy_for(review.repository)
            max_inline_comments = policy.max_inline_comments
            if not policy.publish_comments:
                reasons.append("Comment publishing is disabled by this repository's policy.")
        if review.publication_status is PublicationStatus.published:
            reasons.append("This review has already been published.")
        if review.publication_status is PublicationStatus.stale:
            reasons.append("This review is stale. Run a fresh review before publishing.")
        if (
            review.publication_status is PublicationStatus.publishing
            and review.updated_at > datetime.now(UTC) - timedelta(minutes=5)
        ):
            reasons.append("Publication is already in progress.")

        comments = []
        if review.result:
            comments = [
                PublicationComment(
                    path=issue.file_path,
                    line=issue.line_number,
                    body=self._comment_body(issue),
                )
                for issue in review.result.issues
                if issue.line_validated and issue.line_number is not None
            ][:max_inline_comments]
        return PublicationPreview(
            review_id=review.id,
            commit_sha=review.head_sha,
            body=self._summary_body(review, max_inline_comments),
            comments=comments,
            can_publish=not reasons,
            blocking_reasons=reasons,
            already_published=review.publication_status is PublicationStatus.published,
        )

    async def publish(self, review_id: str) -> PublicationResult:
        review = await self.repository.get(review_id)
        if review is None:
            raise PublicationError("Review not found.")
        if review.publication_status is PublicationStatus.published:
            return self._result(review, "This review was already published.")
        preview = self.preview(review)
        if not preview.can_publish:
            raise PublicationError(" ".join(preview.blocking_reasons))
        if (
            (self.app_auth is None and self.user_auth is None)
            or not review.repository
            or review.pr_number is None
        ):
            raise PublicationError("GitHub App authentication is not configured.")

        claimed = await self.repository.begin_publication(review.id)
        if claimed is None:
            latest_state = await self.repository.get(review.id)
            if latest_state and latest_state.publication_status is PublicationStatus.published:
                return self._result(latest_state, "This review was already published.")
            raise PublicationError("Publication is already in progress or this review is stale.")
        review = claimed
        try:
            latest = await self.github.fetch_pull_request(review.pr_url)
            if latest.head_sha != review.head_sha:
                review.publication_status = PublicationStatus.stale
                await self.repository.save(review)
                raise PublicationError(
                    "The pull request changed after this review. "
                    "Run a fresh review before publishing."
                )

            owner, repository = review.repository.split("/", 1)
            marker = self._marker(review)
            existing = await self._request(
                "GET",
                f"/repos/{owner}/{repository}/pulls/{review.pr_number}/reviews",
                owner=owner,
                repository=repository,
                params={"per_page": 100},
            )
            previous = next(
                (
                    item
                    for item in existing
                    if isinstance(item, dict) and marker in str(item.get("body") or "")
                ),
                None,
            )
            if previous:
                return await self._mark_published(
                    review, int(previous["id"]), "Recovered publish state."
                )

            payload = {
                "commit_id": review.head_sha,
                "body": f"{preview.body}\n\n{marker}",
                "event": "COMMENT",
                "comments": [comment.model_dump() for comment in preview.comments],
            }
            created = await self._request(
                "POST",
                f"/repos/{owner}/{repository}/pulls/{review.pr_number}/reviews",
                owner=owner,
                repository=repository,
                json=payload,
            )
            return await self._mark_published(
                review, int(created["id"]), "Review comments published to GitHub."
            )
        except PublicationError:
            raise
        except HTTPException:
            review.publication_status = PublicationStatus.failed
            await self.repository.save(review)
            raise
        except (GitHubAppError, GitHubError, KeyError, TypeError, ValueError) as exc:
            review.publication_status = PublicationStatus.failed
            await self.repository.save(review)
            raise PublicationError(str(exc)) from exc

    async def _request(self, method, path, **kwargs):
        if self.user_auth is not None:
            return await self.user_auth.request_as_user(method, path, **kwargs)
        return await self.app_auth.request_as_installation(method, path, **kwargs)

    async def _mark_published(
        self, review: ReviewRun, github_review_id: int, message: str
    ) -> PublicationResult:
        review.publication_status = PublicationStatus.published
        review.github_review_id = github_review_id
        review.published_at = datetime.now(UTC)
        await self.repository.save(review)
        return self._result(review, message)

    @staticmethod
    def _result(review: ReviewRun, message: str) -> PublicationResult:
        return PublicationResult(
            review_id=review.id,
            status=review.publication_status,
            github_review_id=review.github_review_id,
            published_at=review.published_at,
            message=message,
        )

    @staticmethod
    def _summary_body(review: ReviewRun, max_inline_comments: int) -> str:
        if review.result is None:
            return "MergeScope AI review is not available."
        approval = review.result.approval.value.replace("_", " ").title()
        count = len(review.result.issues)
        truncation = (
            f"\n\nOnly the first {max_inline_comments} findings are included inline."
            if count > max_inline_comments
            else ""
        )
        return (
            "## MergeScope AI review\n\n"
            f"**Verdict:** {approval} · **Validated findings:** {count}\n\n"
            f"{PublicationService._safe_text(review.result.summary)}{truncation}"
        )

    @staticmethod
    def _comment_body(issue) -> str:
        severity = issue.severity.value.upper()
        agent = issue.agent.value.replace("_", " ")
        return (
            f"### {severity}: {PublicationService._safe_text(issue.title)}\n\n"
            f"{PublicationService._safe_text(issue.message)}\n\n"
            f"**Evidence:** {PublicationService._safe_text(issue.evidence)}\n\n"
            f"**Suggested change:** {PublicationService._safe_text(issue.suggestion)}\n\n"
            f"_MergeScope {agent}; changed line verified._"
        )[:5_000]

    @staticmethod
    def _marker(review: ReviewRun) -> str:
        return f"<!-- mergescope-review:{review.id}:{review.head_sha} -->"

    @staticmethod
    def _safe_text(value: str) -> str:
        return value.replace("@", "@\u200b")
