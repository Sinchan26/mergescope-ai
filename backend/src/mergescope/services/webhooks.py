import hashlib
import hmac
import json
from typing import Any
from uuid import uuid4

from mergescope.core.logging import correlation_id
from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import ReviewJob, WebhookReceipt
from mergescope.services.policies import PolicyRegistry

SUPPORTED_ACTIONS = {"opened", "reopened", "ready_for_review", "synchronize"}


class WebhookError(ValueError):
    pass


class WebhookService:
    def __init__(
        self,
        *,
        repository: ReviewRepository,
        secret: str | None,
        prompt_version: str,
        max_attempts: int,
        max_body_bytes: int,
        notify_worker,
        policies: PolicyRegistry | None = None,
        model: str = "",
    ) -> None:
        self.repository = repository
        self.secret = secret
        self.prompt_version = prompt_version
        self.max_attempts = max_attempts
        self.max_body_bytes = max_body_bytes
        self.notify_worker = notify_worker
        self.policies = policies
        self.model = model

    async def ingest(
        self,
        *,
        delivery_id: str | None,
        event_name: str | None,
        signature: str | None,
        body: bytes,
    ) -> WebhookReceipt:
        if not self.secret:
            raise WebhookError("GitHub webhook handling is not configured.")
        if not delivery_id:
            raise WebhookError("X-GitHub-Delivery is required.")
        if len(body) > self.max_body_bytes:
            raise WebhookError("Webhook payload exceeds the configured size limit.")
        if not self.verify_signature(self.secret, body, signature):
            raise WebhookError("Webhook signature validation failed.")
        if event_name == "ping":
            return WebhookReceipt(
                delivery_id=delivery_id,
                accepted=True,
                message="GitHub App webhook is connected.",
            )
        if event_name != "pull_request":
            return WebhookReceipt(
                delivery_id=delivery_id,
                accepted=False,
                message=f"Event {event_name or '(missing)'} is not used by MergeScope.",
            )

        payload = self._decode_payload(body)
        action = payload.get("action")
        pull_request = payload.get("pull_request")
        if action not in SUPPORTED_ACTIONS or not isinstance(pull_request, dict):
            return WebhookReceipt(
                delivery_id=delivery_id,
                accepted=False,
                message=f"Pull-request action {action or '(missing)'} was ignored.",
            )
        if pull_request.get("draft"):
            return WebhookReceipt(
                delivery_id=delivery_id,
                accepted=False,
                message="Draft pull requests are not queued.",
            )

        repository_name, number, url, head_sha = self._pull_request_fields(payload, pull_request)
        if self.policies and not self.policies.is_allowed(repository_name):
            return WebhookReceipt(
                delivery_id=delivery_id,
                accepted=False,
                message=f"Repository {repository_name} is not allowlisted.",
            )
        installation = payload.get("installation")
        installation_id = (
            int(installation["id"])
            if isinstance(installation, dict) and installation.get("id") is not None
            else None
        )
        policy_fingerprint = (
            self.policies.fingerprint(repository_name) if self.policies else "default"
        )
        key_source = (
            f"{repository_name}:{number}:{head_sha}:{self.model}:{self.prompt_version}:"
            f"{policy_fingerprint}"
        )
        job = ReviewJob(
            id=str(uuid4()),
            idempotency_key=hashlib.sha256(key_source.encode()).hexdigest(),
            delivery_id=delivery_id,
            repository=repository_name,
            pr_number=number,
            pr_url=url,
            head_sha=head_sha,
            installation_id=installation_id,
            correlation_id=correlation_id(),
            max_attempts=self.max_attempts,
        )
        stored, duplicate = await self.repository.enqueue_webhook_job(job, event_name, action)
        self.notify_worker()
        return WebhookReceipt(
            delivery_id=delivery_id,
            accepted=True,
            duplicate=duplicate,
            job_id=stored.id,
            message=(
                "This pull-request head is already queued."
                if duplicate
                else "Pull-request review queued."
            ),
        )

    @staticmethod
    def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
        if not signature or not signature.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def _decode_payload(body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebhookError("Webhook body must be valid UTF-8 JSON.") from exc
        if not isinstance(payload, dict):
            raise WebhookError("Webhook body must be a JSON object.")
        return payload

    @staticmethod
    def _pull_request_fields(
        payload: dict[str, Any], pull_request: dict[str, Any]
    ) -> tuple[str, int, str, str]:
        try:
            repository_name = str(payload["repository"]["full_name"])
            number = int(pull_request["number"])
            url = str(pull_request["html_url"])
            head_sha = str(pull_request["head"]["sha"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WebhookError("Pull-request webhook is missing required fields.") from exc
        if not repository_name or not url or not head_sha:
            raise WebhookError("Pull-request webhook contains empty required fields.")
        return repository_name, number, url, head_sha
