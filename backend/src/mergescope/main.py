import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from mergescope.agents.review_graph import ReviewOrchestrator
from mergescope.api.routes import router
from mergescope.core.config import get_settings
from mergescope.db.repository import ReviewRepository
from mergescope.integrations.embeddings import OpenAIEmbedder
from mergescope.integrations.github import GitHubClient
from mergescope.integrations.github_app import GitHubAppAuth
from mergescope.integrations.openai_review import OpenAIReviewClient
from mergescope.services.knowledge import KnowledgeRetriever, KnowledgeService
from mergescope.services.publication import PublicationService
from mergescope.services.reviews import ReviewService
from mergescope.services.webhooks import WebhookService
from mergescope.services.worker import ReviewWorker

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    repository = ReviewRepository(settings.resolved_database_path)
    await repository.initialize()
    private_key = settings.resolved_github_private_key
    app_auth = (
        GitHubAppAuth(
            app_id=settings.github_app_id,
            private_key=private_key,
            api_url=settings.github_api_url,
            api_version=settings.github_api_version,
            timeout_seconds=settings.github_timeout_seconds,
        )
        if settings.github_app_id and private_key
        else None
    )
    github = GitHubClient(
        api_url=settings.github_api_url,
        token=settings.github_token,
        timeout_seconds=settings.github_timeout_seconds,
        app_auth=app_auth,
        api_version=settings.github_api_version,
    )
    embedder = (
        OpenAIEmbedder(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
            dimensions=settings.embedding_dimensions,
        )
        if settings.openai_api_key
        else None
    )
    review_client = (
        OpenAIReviewClient(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            max_diff_chars=settings.max_diff_chars,
        )
        if settings.openai_api_key
        else None
    )
    knowledge_service = KnowledgeService(
        repository=repository,
        embedder=embedder,
        embedding_model=settings.openai_embedding_model,
        max_document_bytes=settings.max_document_bytes,
    )
    retriever = KnowledgeRetriever(repository=repository, embedder=embedder)
    app.state.repository = repository
    app.state.knowledge_service = knowledge_service
    review_service = ReviewService(
        repository=repository,
        github=github,
        orchestrator=ReviewOrchestrator(review_client) if review_client else None,
        retriever=retriever,
        model=settings.openai_model,
        dry_run_only=settings.dry_run_only,
        demo_mode_allowed=settings.demo_mode_allowed,
        prompt_version=settings.prompt_version,
    )
    worker = ReviewWorker(
        repository=repository,
        review_service=review_service,
        poll_seconds=settings.worker_poll_seconds,
        lease_seconds=settings.worker_lease_seconds,
    )
    app.state.review_service = review_service
    app.state.review_worker = worker
    app.state.webhook_service = WebhookService(
        repository=repository,
        secret=settings.github_webhook_secret,
        prompt_version=settings.prompt_version,
        max_attempts=settings.worker_max_attempts,
        max_body_bytes=settings.webhook_max_bytes,
        notify_worker=worker.notify,
    )
    app.state.publication_service = PublicationService(
        repository=repository,
        github=github,
        app_auth=app_auth,
        publishing_enabled=bool(
            settings.github_publishing_enabled and settings.publish_confirmation_token
        ),
    )
    worker_task = asyncio.create_task(worker.run()) if settings.worker_enabled else None
    try:
        yield
    finally:
        if worker_task:
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task
        await github.close()
        if app_auth:
            await app_auth.close()


app = FastAPI(
    title=settings.app_name,
    version="0.3.0",
    description="Grounded, Docker-free pull-request review and GitHub workflow API",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_prefix)

frontend_dist = settings.resolved_frontend_dist_path
if frontend_dist.joinpath("index.html").exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")
