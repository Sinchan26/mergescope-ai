import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from mergescope.domain.models import RepositoryPolicySummary, ReviewPolicy


class PolicyConfigurationError(ValueError):
    pass


class RepositoryNotAllowedError(ValueError):
    pass


class PolicyRegistry:
    def __init__(self, *, path: Path, allowed_repositories: set[str]) -> None:
        self.path = path
        self.allowed_repositories = {name.lower() for name in allowed_repositories}
        self.default_policy = ReviewPolicy()
        self.repository_policies: dict[str, ReviewPolicy] = {}
        self.policy_file_configured = path.exists()
        if self.policy_file_configured:
            self._load()

    @property
    def allowlist_enabled(self) -> bool:
        return bool(self.allowed_repositories)

    def is_allowed(self, repository: str) -> bool:
        return not self.allowlist_enabled or repository.lower() in self.allowed_repositories

    def require_allowed(self, repository: str) -> None:
        if not self.is_allowed(repository):
            raise RepositoryNotAllowedError(
                f"Repository {repository} is not present in ALLOWED_REPOSITORIES."
            )

    def policy_for(self, repository: str) -> ReviewPolicy:
        return self.repository_policies.get(repository.lower(), self.default_policy)

    def fingerprint(self, repository: str) -> str:
        policy_json = self.policy_for(repository).model_dump_json()
        return hashlib.sha256(policy_json.encode()).hexdigest()

    def summary(self) -> RepositoryPolicySummary:
        return RepositoryPolicySummary(
            allowlist_enabled=self.allowlist_enabled,
            allowed_repository_count=len(self.allowed_repositories),
            policy_file_configured=self.policy_file_configured,
            repository_policy_count=len(self.repository_policies),
            default_policy=self.default_policy,
        )

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise PolicyConfigurationError("Review policy file must contain a JSON object.")
            default_payload = payload.get("default", {})
            repositories = payload.get("repositories", {})
            if not isinstance(default_payload, dict) or not isinstance(repositories, dict):
                raise PolicyConfigurationError(
                    "Review policy default and repositories values must be JSON objects."
                )
            self.default_policy = ReviewPolicy.model_validate(default_payload)
            self.repository_policies = {
                name.lower(): self._merged_policy(policy) for name, policy in repositories.items()
            }
        except (OSError, json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise PolicyConfigurationError(f"Invalid review policy file: {exc}") from exc

    def _merged_policy(self, override: Any) -> ReviewPolicy:
        if not isinstance(override, dict):
            raise PolicyConfigurationError("Each repository policy must be a JSON object.")
        return ReviewPolicy.model_validate(
            {**self.default_policy.model_dump(mode="json"), **override}
        )
