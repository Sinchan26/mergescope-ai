import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from mergescope.agents.review_graph import ReviewOrchestrator
from mergescope.api.auth_routes import router as auth_router
from mergescope.api.routes import router
from mergescope.api.workspace import initialize_workspaces
from mergescope.core.config import get_settings
from mergescope.core.logging import bind_correlation_id, configure_logging
from mergescope.integrations.embeddings import OpenAIEmbedder
from mergescope.integrations.openai_review import OpenAIReviewClient
from mergescope.services.auth import AuthService
from mergescope.services.policies import PolicyRegistry

settings = get_settings()
configure_logging(settings.log_level, json_logs=settings.log_json)
logger = logging.getLogger(__name__)
# Our middleware logs paths without OAuth callback query strings. Uvicorn's
# default access logger would log the one-time authorization code and state.
logging.getLogger("uvicorn.access").disabled = True


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.auth = AuthService(settings)
    await app.state.auth.initialize()
    initialize_workspaces(app)
    app.state.policy_registry = PolicyRegistry(
        path=settings.resolved_review_policies_path,
        allowed_repositories=settings.allowed_repository_set,
    )
    app.state.embedder = (
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
    app.state.orchestrator = ReviewOrchestrator(review_client) if review_client else None
    # Do not open the legacy DB, initialize bot credentials, or start a webhook
    # worker. Browser requests only enter per-user workspaces.
    try:
        yield
    finally:
        await app.state.auth.close()


app = FastAPI(
    title=settings.app_name,
    version="0.5.0",
    description="User-scoped, Docker-free pull-request reviews",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    started = perf_counter()
    with bind_correlation_id(request.headers.get("X-Request-ID")) as request_id:
        context = {"event": "http_request", "method": request.method, "path": request.url.path}
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("HTTP request failed.", extra=context)
            raise
        response.headers["X-Request-ID"] = request_id
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith(settings.api_prefix):
            response.headers["Cache-Control"] = "no-store"
        logger.info(
            "HTTP request completed.",
            extra={
                **context,
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - started) * 1000),
            },
        )
        return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_origin.rstrip("/")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=[
        "Content-Type",
        "X-MergeScope-CSRF",
        "X-MergeScope-Evaluation-Token",
        "X-Request-ID",
    ],
)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(router, prefix=settings.api_prefix)


@app.get(f"{settings.api_prefix}/health")
async def health():
    return {"status": "ok"}


frontend_dist = settings.resolved_frontend_dist_path
if frontend_dist.joinpath("index.html").exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")
