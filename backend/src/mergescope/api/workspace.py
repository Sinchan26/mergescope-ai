"""Request-scoped services; never fall back to the legacy shared workspace."""

import asyncio
from typing import Annotated

import aiosqlite
from fastapi import Depends, HTTPException, Request

from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import ReviewList
from mergescope.integrations.github import GitHubClient
from mergescope.services.auth import AuthService, Session, require_session
from mergescope.services.evaluations import EvaluationService
from mergescope.services.knowledge import KnowledgeRetriever, KnowledgeService
from mergescope.services.publication import PublicationService
from mergescope.services.reviews import ReviewService


class UserRepository(ReviewRepository):
    def __init__(self, path, accessible: dict[str, int]):
        super().__init__(path)
        self.accessible = accessible

    async def initialize(self):
        await super().initialize()
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("""CREATE TABLE IF NOT EXISTS review_repository_bindings
                (review_id TEXT PRIMARY KEY, repository_id INTEGER NOT NULL)""")
            await db.commit()

    async def bind(self, review):
        repo_id = self.accessible.get((review.repository or "").lower())
        if not review.demo_mode and repo_id is not None:
            async with aiosqlite.connect(self.database_path) as db:
                await db.execute(
                    "INSERT OR IGNORE INTO review_repository_bindings VALUES (?, ?)",
                    (review.id, repo_id),
                )
                await db.commit()

    async def create(self, review):
        await super().create(review)
        await self.bind(review)

    async def save(self, review):
        await super().save(review)
        await self.bind(review)

    async def get(self, review_id):
        review = await super().get(review_id)
        if review and not review.demo_mode:
            async with aiosqlite.connect(self.database_path) as db:
                cursor = await db.execute(
                    "SELECT repository_id FROM review_repository_bindings WHERE review_id = ?",
                    (review_id,),
                )
                row = await cursor.fetchone()
            if not row or row[0] != self.accessible.get((review.repository or "").lower()):
                return None
        return review

    async def find_cached(self, cache_key):
        cached = await super().find_cached(cache_key)
        return await self.get(cached.id) if cached else None

    async def list(self, limit=25, offset=0):
        # Filter before pagination/counting, so revoked repositories leak no metadata.
        clauses = (
            " OR ".join("(lower(repository) = ? AND b.repository_id = ?)" for _ in self.accessible)
            or "0"
        )
        where = (
            "demo_mode = 1 OR EXISTS (SELECT 1 FROM review_repository_bindings b "
            f"WHERE b.review_id = review_runs.id AND ({clauses}))"
        )
        values = tuple(value for pair in sorted(self.accessible.items()) for value in pair)
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"SELECT * FROM review_runs WHERE {where} "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (*values, limit, offset),
            )
            rows = await cursor.fetchall()
            cursor = await db.execute(f"SELECT COUNT(*) FROM review_runs WHERE {where}", values)
            total = (await cursor.fetchone())[0]
        return ReviewList(items=[self._review_from_row(row) for row in rows], total=total)


class UserGitHubClient(GitHubClient):
    def __init__(self, auth: AuthService, session: Session, expected=None):
        settings = auth.settings
        super().__init__(
            settings.github_api_url,
            None,
            settings.github_timeout_seconds,
            api_version=settings.github_api_version,
        )
        self.auth = auth
        self.session = session
        self.expected = expected

    async def authorize(self, owner, repository):
        # Refresh and recheck immediately before GitHub reads/writes; no PAT or bot fallback.
        self.session = await self.auth.session(self.session.key)
        accessible = await self.auth.repositories(self.session)
        current = {repo["full_name"].lower(): repo["id"] for repo in accessible}
        name = f"{owner}/{repository}".lower()
        if name not in current or (
            self.expected is not None and self.expected.get(name) != current[name]
        ):
            raise HTTPException(
                403, "This repository is not available to your GitHub account and App installation."
            )

    async def _repository_headers(self, owner, repository, installation_id):
        await self.authorize(owner, repository)
        return {"Authorization": f"Bearer {self.session.token}"}

    async def request_as_user(self, method, path, *, owner, repository, **kwargs):
        await self.authorize(owner, repository)
        return await self.auth.api(self.session.token, method, path, **kwargs)

    async def _get(self, path, params=None, headers=None):
        return await self.auth.api(self.session.token, "GET", path, params=params)


async def workspace(request: Request, session: Annotated[Session, Depends(require_session)]):
    state = request.app.state
    settings = state.auth.settings
    if request.url.path.endswith("/webhooks/github"):
        raise HTTPException(410, "Webhooks are disabled. Use the signed-in manual review workflow.")
    accessible = {
        repo["full_name"].lower(): repo["id"] for repo in await state.auth.repositories(session)
    }
    path = (
        settings.resolved_database_path.parent
        / f"{settings.resolved_database_path.stem}-users"
        / f"{session.user_id}.db"
    )
    repository = UserRepository(path, accessible)
    async with state.workspace_init_lock:
        if session.user_id not in state.initialized_users:
            await repository.initialize()
            path.chmod(0o600)
            state.initialized_users.add(session.user_id)
    github = UserGitHubClient(state.auth, session, expected=accessible)
    request.state.repository = repository
    request.state.knowledge_service = KnowledgeService(
        repository=repository,
        embedder=state.embedder,
        embedding_model=settings.openai_embedding_model,
        max_document_bytes=settings.max_document_bytes,
    )
    request.state.review_service = ReviewService(
        repository=repository,
        github=github,
        orchestrator=state.orchestrator,
        retriever=KnowledgeRetriever(repository=repository, embedder=state.embedder),
        model=settings.openai_model,
        dry_run_only=settings.dry_run_only,
        demo_mode_allowed=settings.demo_mode_allowed,
        prompt_version=settings.prompt_version,
        policies=state.policy_registry,
    )
    request.state.publication_service = PublicationService(
        repository=repository,
        github=github,
        app_auth=None,
        user_auth=github,
        publishing_enabled=settings.github_publishing_enabled,
        policies=state.policy_registry,
    )
    request.state.evaluation_service = EvaluationService(
        repository=repository,
        orchestrator=state.orchestrator,
        dataset_path=settings.resolved_evaluation_dataset_path,
        model=settings.openai_model,
        prompt_version=settings.prompt_version,
        input_cost_per_million=settings.openai_input_cost_per_million,
        output_cost_per_million=settings.openai_output_cost_per_million,
    )
    try:
        yield
    finally:
        await github.close()


def initialize_workspaces(app):
    app.state.workspace_init_lock = asyncio.Lock()
    app.state.initialized_users = set()
