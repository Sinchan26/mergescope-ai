from pathlib import Path

import pytest
from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import (
    AgentRole,
    Approval,
    ContextSource,
    ManualReviewRequest,
    PullRequestFile,
    PullRequestSnapshot,
    ReviewResult,
    ReviewStatus,
)
from mergescope.services.policies import PolicyRegistry, RepositoryNotAllowedError
from mergescope.services.reviews import ReviewService, StalePullRequestError


class FakeGitHub:
    fetch_calls = 0

    async def fetch_pull_request(self, url: str) -> PullRequestSnapshot:
        self.fetch_calls += 1
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
                    additions=1,
                    deletions=0,
                    changes=1,
                    patch="@@ -2,1 +2,2 @@\n value = read()\n+validate(value)",
                )
            ],
        )

    async def fetch_repository_guidance(
        self, pull_request: PullRequestSnapshot
    ) -> list[ContextSource]:
        return [
            ContextSource(
                source_id="repository:AGENTS.md",
                name="AGENTS.md",
                source_type="repository_guidance",
                excerpt="Validate all external input.",
            )
        ]


class FakeRetriever:
    async def retrieve(self, query: str) -> list[ContextSource]:
        return []


class FakeOrchestrator:
    calls = 0

    async def run(
        self, pull_request, context_sources, parsed_patches, ticket_reference, policy=None
    ):
        self.calls += 1
        return (
            ReviewResult(
                summary="The change is safe to merge.",
                approval=Approval.approve,
                confidence=0.9,
                issues=[],
                positive_notes=["Input validation is explicit."],
                reviewed_files=["src/parser.py"],
                skipped_files=[],
                agents_run=[AgentRole.code, AgentRole.testing, AgentRole.synthesizer],
                context_sources=context_sources,
            ),
            120,
            80,
            350,
        )


def build_service(
    tmp_path: Path, orchestrator=None, policies=None
) -> tuple[ReviewService, ReviewRepository]:
    repository = ReviewRepository(tmp_path / "reviews.db")
    service = ReviewService(
        repository=repository,
        github=FakeGitHub(),  # type: ignore[arg-type]
        orchestrator=orchestrator,
        retriever=FakeRetriever(),  # type: ignore[arg-type]
        model="test-model",
        dry_run_only=True,
        demo_mode_allowed=True,
        prompt_version="test-v1",
        policies=policies,
    )
    return service, repository


async def test_manual_review_is_persisted_and_reused_from_cache(tmp_path: Path) -> None:
    orchestrator = FakeOrchestrator()
    service, repository = build_service(tmp_path, orchestrator)
    await repository.initialize()
    request = ManualReviewRequest(pr_url="https://github.com/example/project/pull/7")

    first = await service.run_manual_review(request)
    second = await service.run_manual_review(request)

    assert first.status is ReviewStatus.completed
    assert first.repository == "example/project"
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.cached_from_id == first.id
    assert second.input_tokens == 0
    assert orchestrator.calls == 1
    assert (await repository.list()).total == 2


async def test_force_rereview_bypasses_cache(tmp_path: Path) -> None:
    orchestrator = FakeOrchestrator()
    service, repository = build_service(tmp_path, orchestrator)
    await repository.initialize()
    await service.run_manual_review(
        ManualReviewRequest(pr_url="https://github.com/example/project/pull/7")
    )

    rerun = await service.run_manual_review(
        ManualReviewRequest(pr_url="https://github.com/example/project/pull/7", force_rereview=True)
    )

    assert rerun.cache_hit is False
    assert orchestrator.calls == 2


async def test_demo_review_needs_no_github_or_openai_configuration(tmp_path: Path) -> None:
    service, repository = build_service(tmp_path, orchestrator=None)
    await repository.initialize()

    run = await service.run_manual_review(ManualReviewRequest(demo_mode=True))

    assert run.status is ReviewStatus.completed
    assert run.demo_mode is True
    assert run.model == "demo-fixture"
    assert run.result is not None
    assert AgentRole.security in run.result.agents_run
    assert all(issue.line_validated for issue in run.result.issues)


async def test_openai_key_is_required_before_a_live_run_is_created(tmp_path: Path) -> None:
    service, repository = build_service(tmp_path, orchestrator=None)
    await repository.initialize()

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        await service.run_manual_review(
            ManualReviewRequest(pr_url="https://github.com/example/project/pull/7")
        )

    assert (await repository.list()).total == 0


async def test_expected_webhook_head_rejects_superseded_pull_request(tmp_path: Path) -> None:
    service, repository = build_service(tmp_path, FakeOrchestrator())
    await repository.initialize()

    with pytest.raises(StalePullRequestError, match="superseded"):
        await service.run_manual_review(
            ManualReviewRequest(pr_url="https://github.com/example/project/pull/7"),
            expected_head_sha="older-head",
        )

    runs = await repository.list()
    assert runs.total == 1
    assert runs.items[0].status is ReviewStatus.failed


async def test_disallowed_manual_repository_is_rejected_before_run_creation(
    tmp_path: Path,
) -> None:
    policies = PolicyRegistry(
        path=tmp_path / "missing-policy.json",
        allowed_repositories={"allowed/project"},
    )
    service, repository = build_service(tmp_path, FakeOrchestrator(), policies)
    await repository.initialize()

    with pytest.raises(RepositoryNotAllowedError, match="not present"):
        await service.run_manual_review(
            ManualReviewRequest(pr_url="https://github.com/example/project/pull/7")
        )

    assert (await repository.list()).total == 0
