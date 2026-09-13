import hashlib
import logging
from uuid import uuid4

from mergescope.agents.review_graph import ReviewOrchestrator
from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import (
    ManualReviewRequest,
    PullRequestSnapshot,
    ReviewPolicy,
    ReviewRun,
    ReviewStatus,
    TriggerSource,
)
from mergescope.integrations.github import GitHubClient, parse_github_pr_url
from mergescope.services.demo import demo_pull_request, demo_result
from mergescope.services.diff_parser import parse_pull_request_patches
from mergescope.services.knowledge import KnowledgeRetriever
from mergescope.services.policies import PolicyRegistry

logger = logging.getLogger(__name__)


class StalePullRequestError(RuntimeError):
    pass


class ReviewService:
    def __init__(
        self,
        repository: ReviewRepository,
        github: GitHubClient,
        orchestrator: ReviewOrchestrator | None,
        retriever: KnowledgeRetriever,
        model: str,
        dry_run_only: bool,
        demo_mode_allowed: bool,
        prompt_version: str,
        policies: PolicyRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.github = github
        self.orchestrator = orchestrator
        self.retriever = retriever
        self.model = model
        self.dry_run_only = dry_run_only
        self.demo_mode_allowed = demo_mode_allowed
        self.prompt_version = prompt_version
        self.policies = policies

    async def run_manual_review(
        self,
        request: ManualReviewRequest,
        *,
        expected_head_sha: str | None = None,
        installation_id: int | None = None,
        trigger_source: TriggerSource = TriggerSource.manual,
        job_id: str | None = None,
    ) -> ReviewRun:
        if self.dry_run_only and not request.dry_run:
            raise ValueError("This milestone only supports dry-run reviews.")
        if request.demo_mode and not self.demo_mode_allowed:
            raise ValueError("Demo mode is disabled on this server.")
        if not request.demo_mode and self.orchestrator is None:
            raise ValueError("OPENAI_API_KEY is not configured on the server.")

        policy = ReviewPolicy()
        if not request.demo_mode and request.pr_url:
            owner, repository, _ = parse_github_pr_url(str(request.pr_url))
            repository_name = f"{owner}/{repository}"
            if self.policies:
                self.policies.require_allowed(repository_name)
                policy = self.policies.policy_for(repository_name)
            if policy.require_ticket_reference and not request.ticket_reference:
                raise ValueError(f"A ticket reference is required for {repository_name}.")

        run = ReviewRun(
            id=str(uuid4()),
            pr_url=(
                str(request.pr_url)
                if request.pr_url
                else "https://github.com/acme/payments-api/pull/128"
            ),
            status=ReviewStatus.queued,
            dry_run=True,
            ticket_reference=request.ticket_reference or None,
            model="demo-fixture" if request.demo_mode else self.model,
            prompt_version=self.prompt_version,
            demo_mode=request.demo_mode,
            trigger_source=TriggerSource.demo if request.demo_mode else trigger_source,
            job_id=job_id,
        )
        await self.repository.create(run)

        try:
            run.status = ReviewStatus.running
            await self.repository.save(run)
            pull_request = (
                demo_pull_request()
                if request.demo_mode
                else await self._fetch_pull_request(run.pr_url, installation_id)
            )
            if expected_head_sha and pull_request.head_sha != expected_head_sha:
                raise StalePullRequestError(
                    f"Webhook head {expected_head_sha[:12]} was superseded by "
                    f"{pull_request.head_sha[:12]}."
                )
            self._apply_pull_request(run, pull_request)
            run.cache_key = self._cache_key(pull_request, policy)
            documents = await self.repository.list_documents()
            context_key = ":".join(sorted(document.id for document in documents.items))
            run.cache_key = hashlib.sha256(
                f"{run.cache_key}:{context_key}:{run.ticket_reference or ''}".encode()
            ).hexdigest()

            if not request.demo_mode and not request.force_rereview:
                cached = await self.repository.find_cached(run.cache_key)
                if cached and cached.result:
                    run.result = cached.result.model_copy(deep=True)
                    run.issue_count = cached.issue_count
                    run.input_tokens = 0
                    run.output_tokens = 0
                    run.latency_ms = 0
                    run.cache_hit = True
                    run.cached_from_id = cached.id
                    run.status = ReviewStatus.completed
                    await self.repository.save(run)
                    return run

            if request.demo_mode:
                run.result = demo_result(pull_request)
                run.input_tokens = 0
                run.output_tokens = 0
                run.latency_ms = 0
            else:
                context_sources = await self._load_context(pull_request, installation_id)
                parsed_patches = parse_pull_request_patches(pull_request)
                result, input_tokens, output_tokens, latency_ms = await self.orchestrator.run(
                    pull_request,
                    context_sources,
                    parsed_patches,
                    run.ticket_reference,
                    policy,
                )
                run.result = result
                run.input_tokens = input_tokens
                run.output_tokens = output_tokens
                run.latency_ms = latency_ms

            run.issue_count = len(run.result.issues)
            run.status = ReviewStatus.completed
            await self.repository.save(run)
            return run
        except Exception as exc:
            run.status = ReviewStatus.failed
            run.error_message = str(exc)
            await self.repository.save(run)
            raise

    async def _load_context(self, pull_request: PullRequestSnapshot, installation_id: int | None):
        if installation_id is None:
            repository_sources = await self.github.fetch_repository_guidance(pull_request)
        else:
            repository_sources = await self.github.fetch_repository_guidance(
                pull_request, installation_id=installation_id
            )
        query = "\n".join(
            [pull_request.title, pull_request.body or ""]
            + [f"{file.filename}\n{(file.patch or '')[:1_000]}" for file in pull_request.files]
        )
        try:
            document_sources = await self.retriever.retrieve(query[:12_000])
        except Exception as exc:
            logger.warning("Knowledge retrieval skipped: %s", exc)
            document_sources = []
        return [*repository_sources, *document_sources]

    async def _fetch_pull_request(
        self, url: str, installation_id: int | None
    ) -> PullRequestSnapshot:
        if installation_id is None:
            return await self.github.fetch_pull_request(url)
        return await self.github.fetch_pull_request(url, installation_id=installation_id)

    def _cache_key(self, pull_request: PullRequestSnapshot, policy: ReviewPolicy) -> str:
        policy_fingerprint = hashlib.sha256(policy.model_dump_json().encode()).hexdigest()
        value = (
            f"{pull_request.repository}:{pull_request.number}:"
            f"{pull_request.head_sha}:{self.model}:{self.prompt_version}:{policy_fingerprint}"
        )
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _apply_pull_request(run: ReviewRun, pull_request: PullRequestSnapshot) -> None:
        run.repository = pull_request.repository
        run.pr_number = pull_request.number
        run.pr_url = pull_request.url
        run.head_sha = pull_request.head_sha
        run.title = pull_request.title
        run.author = pull_request.author
