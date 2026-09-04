from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from mergescope.api.routes import router
from mergescope.core.config import get_settings
from mergescope.db.repository import ReviewRepository
from mergescope.integrations.github import GitHubClient
from mergescope.integrations.openai_review import OpenAIReviewer
from mergescope.services.reviews import ReviewService

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    repository = ReviewRepository(settings.resolved_database_path)
    await repository.initialize()
    github = GitHubClient(
        api_url=settings.github_api_url,
        token=settings.github_token,
        timeout_seconds=settings.github_timeout_seconds,
    )
    reviewer = (
        OpenAIReviewer(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            max_diff_chars=settings.max_diff_chars,
        )
        if settings.openai_api_key
        else None
    )
    app.state.repository = repository
    app.state.review_service = ReviewService(
        repository=repository,
        github=github,
        reviewer=reviewer,
        model=settings.openai_model,
        dry_run_only=settings.dry_run_only,
    )
    yield
    await github.close()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Docker-free AI pull-request review API",
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
