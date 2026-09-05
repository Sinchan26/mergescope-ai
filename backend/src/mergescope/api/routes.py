from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
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
    HealthResponse,
    KnowledgeDocument,
    KnowledgeDocumentList,
    ManualReviewRequest,
    PublicConfig,
    ReviewList,
    ReviewRun,
)
from mergescope.integrations.github import GitHubError
from mergescope.integrations.openai_review import OpenAIReviewError
from mergescope.services.knowledge import KnowledgeService
from mergescope.services.reviews import ReviewService

router = APIRouter()


def get_repository(request: Request) -> ReviewRepository:
    return request.app.state.repository


def get_review_service(request: Request) -> ReviewService:
    return request.app.state.review_service


def get_knowledge_service(request: Request) -> KnowledgeService:
    return request.app.state.knowledge_service


RepositoryDep = Annotated[ReviewRepository, Depends(get_repository)]
ReviewServiceDep = Annotated[ReviewService, Depends(get_review_service)]
KnowledgeServiceDep = Annotated[KnowledgeService, Depends(get_knowledge_service)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("/health", response_model=HealthResponse)
async def health(repository: RepositoryDep, settings: SettingsDep) -> HealthResponse:
    database_ready = await repository.ping()
    return HealthResponse(
        status="ready" if database_ready else "degraded",
        database="connected" if database_ready else "unavailable",
        openai_configured=bool(settings.openai_api_key),
        github_configured=bool(settings.github_token),
        knowledge_documents=await repository.document_count() if database_ready else 0,
        dry_run_only=settings.dry_run_only,
        demo_mode_allowed=settings.demo_mode_allowed,
    )


@router.get("/config", response_model=PublicConfig)
async def public_config(settings: SettingsDep) -> PublicConfig:
    return PublicConfig(
        app_name=settings.app_name,
        environment=settings.app_env,
        openai_model=settings.openai_model,
        embedding_model=settings.openai_embedding_model,
        openai_configured=bool(settings.openai_api_key),
        github_configured=bool(settings.github_token),
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
