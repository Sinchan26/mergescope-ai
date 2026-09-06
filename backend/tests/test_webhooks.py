import hashlib
import hmac
import json
from pathlib import Path

import pytest
from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import JobStatus
from mergescope.services.webhooks import WebhookError, WebhookService


def pull_request_payload(*, head_sha: str = "head-123", draft: bool = False) -> bytes:
    return json.dumps(
        {
            "action": "synchronize",
            "installation": {"id": 501},
            "repository": {"full_name": "example/project"},
            "pull_request": {
                "number": 7,
                "html_url": "https://github.com/example/project/pull/7",
                "draft": draft,
                "head": {"sha": head_sha},
            },
        }
    ).encode()


def signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def test_signed_webhook_is_queued_and_deduplicated(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "reviews.db")
    await repository.initialize()
    notifications = 0

    def notify() -> None:
        nonlocal notifications
        notifications += 1

    service = WebhookService(
        repository=repository,
        secret="webhook-secret",
        prompt_version="phase3-test",
        max_attempts=3,
        max_body_bytes=50_000,
        notify_worker=notify,
    )
    body = pull_request_payload()

    first = await service.ingest(
        delivery_id="delivery-1",
        event_name="pull_request",
        signature=signature("webhook-secret", body),
        body=body,
    )
    repeated_delivery = await service.ingest(
        delivery_id="delivery-1",
        event_name="pull_request",
        signature=signature("webhook-secret", body),
        body=body,
    )
    repeated_head = await service.ingest(
        delivery_id="delivery-2",
        event_name="pull_request",
        signature=signature("webhook-secret", body),
        body=body,
    )

    assert first.accepted is True
    assert first.duplicate is False
    assert repeated_delivery.duplicate is True
    assert repeated_head.duplicate is True
    assert first.job_id == repeated_delivery.job_id == repeated_head.job_id
    jobs = await repository.list_jobs()
    assert jobs.total == 1
    assert jobs.items[0].installation_id == 501
    assert notifications == 3


async def test_webhook_rejects_bad_signature_and_ignores_drafts(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "reviews.db")
    await repository.initialize()
    service = WebhookService(
        repository=repository,
        secret="correct-secret",
        prompt_version="phase3-test",
        max_attempts=3,
        max_body_bytes=50_000,
        notify_worker=lambda: None,
    )
    body = pull_request_payload()

    with pytest.raises(WebhookError, match="signature"):
        await service.ingest(
            delivery_id="bad-delivery",
            event_name="pull_request",
            signature=signature("wrong-secret", body),
            body=body,
        )

    draft = pull_request_payload(draft=True)
    receipt = await service.ingest(
        delivery_id="draft-delivery",
        event_name="pull_request",
        signature=signature("correct-secret", draft),
        body=draft,
    )
    assert receipt.accepted is False
    assert (await repository.list_jobs()).total == 0


async def test_job_claim_and_terminal_failure_are_persisted(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "reviews.db")
    await repository.initialize()
    service = WebhookService(
        repository=repository,
        secret="secret",
        prompt_version="phase3-test",
        max_attempts=3,
        max_body_bytes=50_000,
        notify_worker=lambda: None,
    )
    body = pull_request_payload()
    await service.ingest(
        delivery_id="delivery-claim",
        event_name="pull_request",
        signature=signature("secret", body),
        body=body,
    )

    claimed = await repository.claim_next_job(lease_seconds=300)
    assert claimed is not None
    assert claimed.status is JobStatus.running
    assert claimed.attempts == 1
    status = await repository.fail_job(claimed, "Invalid configuration", retryable=False)

    assert status is JobStatus.failed
    assert (await repository.list_jobs()).items[0].error_message == "Invalid configuration"
