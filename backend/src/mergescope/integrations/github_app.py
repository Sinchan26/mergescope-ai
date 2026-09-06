from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import time
from typing import Any

import httpx
import jwt


class GitHubAppError(RuntimeError):
    pass


@dataclass
class InstallationToken:
    value: str
    expires_at: datetime


class GitHubAppAuth:
    def __init__(
        self,
        *,
        app_id: str,
        private_key: str,
        api_url: str,
        api_version: str,
        timeout_seconds: float,
    ) -> None:
        self.app_id = app_id
        self.private_key = private_key
        self.api_version = api_version
        self._client = httpx.AsyncClient(
            base_url=api_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": api_version,
                "User-Agent": "MergeScope-AI",
            },
        )
        self._tokens: dict[int, InstallationToken] = {}

    async def close(self) -> None:
        await self._client.aclose()

    def create_jwt(self) -> str:
        now = int(time())
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self.app_id},
            self.private_key,
            algorithm="RS256",
        )

    async def installation_token(
        self,
        *,
        installation_id: int | None = None,
        owner: str | None = None,
        repository: str | None = None,
    ) -> str:
        if installation_id is None:
            if not owner or not repository:
                raise GitHubAppError("A repository or installation ID is required.")
            installation_id = await self._find_installation(owner, repository)

        cached = self._tokens.get(installation_id)
        if cached and cached.expires_at > datetime.now(UTC) + timedelta(minutes=5):
            return cached.value

        response = await self._request_with_jwt(
            "POST", f"/app/installations/{installation_id}/access_tokens"
        )
        try:
            value = response["token"]
            expires_at = datetime.fromisoformat(response["expires_at"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubAppError("GitHub returned an invalid installation token response.") from exc
        self._tokens[installation_id] = InstallationToken(value=value, expires_at=expires_at)
        return value

    async def request_as_installation(
        self,
        method: str,
        path: str,
        *,
        owner: str,
        repository: str,
        installation_id: int | None = None,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        token = await self.installation_token(
            installation_id=installation_id,
            owner=owner,
            repository=repository,
        )
        try:
            response = await self._client.request(
                method,
                path,
                headers={"Authorization": f"Bearer {token}"},
                json=json,
                params=params,
            )
            response.raise_for_status()
            return response.json() if response.content else None
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise GitHubAppError(f"GitHub App request failed with HTTP {status}.") from exc
        except httpx.HTTPError as exc:
            raise GitHubAppError("Could not reach GitHub using the app installation.") from exc

    async def _find_installation(self, owner: str, repository: str) -> int:
        response = await self._request_with_jwt("GET", f"/repos/{owner}/{repository}/installation")
        try:
            return int(response["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubAppError("GitHub returned an invalid installation record.") from exc

    async def _request_with_jwt(self, method: str, path: str) -> Any:
        try:
            response = await self._client.request(
                method,
                path,
                headers={"Authorization": f"Bearer {self.create_jwt()}"},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                message = "The GitHub App is not installed for this repository."
            elif status in {401, 403}:
                message = "GitHub rejected the app ID, private key, or permissions."
            else:
                message = f"GitHub App authentication failed with HTTP {status}."
            raise GitHubAppError(message) from exc
        except (httpx.HTTPError, jwt.PyJWTError, ValueError) as exc:
            raise GitHubAppError("Could not authenticate the GitHub App.") from exc
