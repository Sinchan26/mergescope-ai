import secrets
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)

from mergescope.core.config import Settings, get_settings
from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import (
    EvaluationDatasetSummary,
    EvaluationRun,
    EvaluationRunList,
    HealthResponse,
    KnowledgeDocument,
    KnowledgeDocumentList,
    ManualReviewRequest,
    PublicationPreview,
    PublicationResult,
    PublicConfig,
    PublishReviewRequest,
    RepositoryPolicySummary,
    ReviewJobList,
    ReviewList,
    ReviewRun,
    RunEvaluationRequest,
    WebhookReceipt,
)
from mergescope.integrations.github import GitHubError
from mergescope.integrations.openai_review import OpenAIReviewError
from mergescope.services.evaluations import EvaluationError, EvaluationService
from mergescope.services.knowledge import KnowledgeService
from mergescope.services.policies import PolicyRegistry
from mergescope.services.publication import PublicationError, PublicationService
from mergescope.services.reviews import ReviewService
from mergescope.services.webhooks import WebhookError, WebhookService

router = APIRouter()


def get_repository(request: Request) -> ReviewRepository:
    return request.app.state.repository


def get_review_service(request: Request) -> ReviewService:
    return request.app.state.review_service


def get_knowledge_service(request: Request) -> KnowledgeService:
    return request.app.state.knowledge_service


def get_webhook_service(request: Request) -> WebhookService:
    return request.app.state.webhook_service


def get_publication_service(request: Request) -> PublicationService:
    return request.app.state.publication_service


def get_evaluation_service(request: Request) -> EvaluationService:
    return request.app.state.evaluation_service


def get_policy_registry(request: Request) -> PolicyRegistry:
    return request.app.state.policy_registry


RepositoryDep = Annotated[ReviewRepository, Depends(get_repository)]
ReviewServiceDep = Annotated[ReviewService, Depends(get_review_service)]
KnowledgeServiceDep = Annotated[KnowledgeService, Depends(get_knowledge_service)]
WebhookServiceDep = Annotated[WebhookService, Depends(get_webhook_service)]
PublicationServiceDep = Annotated[PublicationService, Depends(get_publication_service)]
EvaluationServiceDep = Annotated[EvaluationService, Depends(get_evaluation_service)]
PolicyRegistryDep = Annotated[PolicyRegistry, Depends(get_policy_registry)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("/health", response_model=HealthResponse)
async def health(
    repository: RepositoryDep,
    settings: SettingsDep,
    policies: PolicyRegistryDep,
    evaluations: EvaluationServiceDep,
) -> HealthResponse:
    database_ready = await repository.ping()
    return HealthResponse(
        status="ready" if database_ready else "degraded",
        database="connected" if database_ready else "unavailable",
        openai_configured=bool(settings.openai_api_key),
        github_configured=bool(settings.github_token or settings.github_app_ready),
        github_app_configured=settings.github_app_ready,
        webhook_configured=bool(settings.github_webhook_secret),
        worker_enabled=settings.worker_enabled,
        pending_jobs=await repository.pending_job_count() if database_ready else 0,
        publishing_enabled=bool(
            settings.github_publishing_enabled and settings.publish_confirmation_token
        ),
        allowlist_enabled=policies.allowlist_enabled,
        policy_file_configured=policies.policy_file_configured,
        evaluation_dataset_ready=evaluations.dataset_ready,
        evaluation_enabled=bool(
            settings.openai_api_key and settings.evaluation_run_token and evaluations.dataset_ready
        ),
        knowledge_documents=await repository.document_count() if database_ready else 0,
        dry_run_only=settings.dry_run_only,
        demo_mode_allowed=settings.demo_mode_allowed,
    )


@router.get("/config", response_model=PublicConfig)
async def public_config(
    settings: SettingsDep,
    policies: PolicyRegistryDep,
    evaluations: EvaluationServiceDep,
) -> PublicConfig:
    policy_summary = policies.summary()
    evaluation_case_count = (
        evaluations.dataset_summary().case_count if evaluations.dataset_ready else 0
    )
    return PublicConfig(
        app_name=settings.app_name,
        environment=settings.app_env,
        openai_model=settings.openai_model,
        embedding_model=settings.openai_embedding_model,
        openai_configured=bool(settings.openai_api_key),
        github_configured=bool(settings.github_token or settings.github_app_ready),
        github_app_configured=settings.github_app_ready,
        webhook_configured=bool(settings.github_webhook_secret),
        worker_enabled=settings.worker_enabled,
        publishing_enabled=bool(
            settings.github_publishing_enabled and settings.publish_confirmation_token
        ),
        allowlist_enabled=policy_summary.allowlist_enabled,
        allowed_repository_count=policy_summary.allowed_repository_count,
        policy_file_configured=policy_summary.policy_file_configured,
        repository_policy_count=policy_summary.repository_policy_count,
        evaluation_dataset_ready=evaluations.dataset_ready,
        evaluation_enabled=bool(
            settings.openai_api_key and settings.evaluation_run_token and evaluations.dataset_ready
        ),
        evaluation_case_count=evaluation_case_count,
        cost_estimation_configured=bool(
            settings.openai_input_cost_per_million or settings.openai_output_cost_per_million
        ),
        structured_logging=settings.log_json,
        dry_run_only=settings.dry_run_only,
        demo_mode_allowed=settings.demo_mode_allowed,
        prompt_version=settings.prompt_version,
    )


@router.get("/reviews", response_model=ReviewList)
async def list_reviews(
    repository: RepositoryDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReviewList:
    return await repository.list(limit=limit, offset=offset)


@router.get("/reviews/{review_id}", response_model=ReviewRun)
async def get_review(review_id: str, repository: RepositoryDep) -> ReviewRun:
    review = await repository.get(review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
    return review


@router.get("/reviews/{review_id}/publication-preview", response_model=PublicationPreview)
async def publication_preview(
    review_id: str,
    repository: RepositoryDep,
    service: PublicationServiceDep,
) -> PublicationPreview:
    review = await repository.get(review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
    return service.preview(review)


@router.post("/reviews/{review_id}/publish", response_model=PublicationResult)
async def publish_review(
    review_id: str,
    payload: PublishReviewRequest,
    service: PublicationServiceDep,
    settings: SettingsDep,
    publish_token: Annotated[str | None, Header(alias="X-MergeScope-Publish-Token")] = None,
) -> PublicationResult:
    if payload.confirm is not True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Confirmation required."
        )
    expected = settings.publish_confirmation_token
    if not settings.github_publishing_enabled or not expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="GitHub publishing is not fully enabled on this server.",
        )
    if publish_token is None or not secrets.compare_digest(publish_token, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The publication confirmation token is missing or incorrect.",
        )
    try:
        return await service.publish(review_id)
    except PublicationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/reviews/manual", response_model=ReviewRun, status_code=status.HTTP_201_CREATED)
async def manual_review(
    payload: ManualReviewRequest,
    service: ReviewServiceDep,
) -> ReviewRun:
    try:
        return await service.run_manual_review(payload)
    except (ValueError, GitHubError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except OpenAIReviewError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/jobs", response_model=ReviewJobList)
async def list_jobs(
    repository: RepositoryDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> ReviewJobList:
    return await repository.list_jobs(limit=limit)


@router.get("/policies", response_model=RepositoryPolicySummary)
async def policy_summary(policies: PolicyRegistryDep) -> RepositoryPolicySummary:
    return policies.summary()


@router.get("/evaluations/dataset", response_model=EvaluationDatasetSummary)
async def evaluation_dataset(service: EvaluationServiceDep) -> EvaluationDatasetSummary:
    try:
        return service.dataset_summary()
    except EvaluationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.get("/evaluations/runs", response_model=EvaluationRunList)
async def evaluation_runs(
    repository: RepositoryDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> EvaluationRunList:
    return await repository.list_evaluation_runs(limit=limit)


@router.post("/evaluations/runs", response_model=EvaluationRun, status_code=status.HTTP_201_CREATED)
async def run_evaluation(
    payload: RunEvaluationRequest,
    service: EvaluationServiceDep,
    settings: SettingsDep,
    evaluation_token: Annotated[str | None, Header(alias="X-MergeScope-Evaluation-Token")] = None,
) -> EvaluationRun:
    if payload.confirm_cost is not True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OpenAI evaluation cost confirmation is required.",
        )
    expected = settings.evaluation_run_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Evaluation runs are disabled until EVALUATION_RUN_TOKEN is configured.",
        )
    if evaluation_token is None or not secrets.compare_digest(evaluation_token, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The evaluation operator token is missing or incorrect.",
        )
    try:
        return await service.run()
    except EvaluationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/webhooks/github", response_model=WebhookReceipt, status_code=status.HTTP_202_ACCEPTED
)
async def github_webhook(request: Request, service: WebhookServiceDep) -> WebhookReceipt:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > service.max_body_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Webhook payload exceeds the configured size limit.",
            )
    try:
        return await service.ingest(
            delivery_id=request.headers.get("X-GitHub-Delivery"),
            event_name=request.headers.get("X-GitHub-Event"),
            signature=request.headers.get("X-Hub-Signature-256"),
            body=bytes(body),
        )
    except WebhookError as exc:
        status_code = (
            status.HTTP_401_UNAUTHORIZED
            if "signature" in str(exc).lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/knowledge/documents", response_model=KnowledgeDocumentList)
async def list_documents(repository: RepositoryDep) -> KnowledgeDocumentList:
    return await repository.list_documents()


@router.post(
    "/knowledge/documents",
    response_model=KnowledgeDocument,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_document(
    service: KnowledgeServiceDep,
    file: Annotated[UploadFile, File(description="Markdown or UTF-8 text document")],
) -> KnowledgeDocument:
    try:
        payload = await file.read(service.max_document_bytes + 1)
        return await service.ingest(
            filename=file.filename or "document.txt",
            content_type=file.content_type or "text/plain",
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        await file.close()


@router.delete("/knowledge/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str, repository: RepositoryDep) -> Response:
    deleted = await repository.delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
