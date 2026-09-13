import base64
import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from mergescope.domain.models import ContextSource, PullRequestFile, PullRequestSnapshot
from mergescope.integrations.github_app import GitHubAppAuth, GitHubAppError

PR_PATH = re.compile(r"^/([^/]+)/([^/]+)/pull/(\d+)/?$")
GUIDANCE_FILES = ("AGENTS.md", "CONTRIBUTING.md", ".github/pull_request_template.md")


class GitHubError(RuntimeError):
    pass


def parse_github_pr_url(url: str) -> tuple[str, str, int]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
        raise GitHubError("Enter a valid https://github.com/owner/repository/pull/123 URL.")
    match = PR_PATH.match(parsed.path)
    if not match:
        raise GitHubError("Enter a GitHub pull request URL, not a repository or issue URL.")
    owner, repository, number = match.groups()
    return owner, repository, int(number)


class GitHubClient:
    def __init__(
        self,
        api_url: str,
        token: str | None,
        timeout_seconds: float,
        app_auth: GitHubAppAuth | None = None,
        api_version: str = "2026-03-10",
    ) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": api_version,
            "User-Agent": "MergeScope-AI",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(
            base_url=api_url.rstrip("/"), headers=headers, timeout=timeout_seconds
        )
        self._app_auth = app_auth

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_pull_request(
        self, url: str, installation_id: int | None = None
    ) -> PullRequestSnapshot:
        owner, repository, number = parse_github_pr_url(url)
        headers = await self._repository_headers(owner, repository, installation_id)
        pull = await self._get(f"/repos/{owner}/{repository}/pulls/{number}", headers=headers)
        files = await self._fetch_files(owner, repository, number, headers)
        return PullRequestSnapshot(
            repository=f"{owner}/{repository}",
            number=number,
            url=pull["html_url"],
            title=pull["title"],
            author=pull["user"]["login"],
            base_ref=pull["base"]["ref"],
            head_ref=pull["head"]["ref"],
            head_sha=pull["head"]["sha"],
            body=pull.get("body"),
            files=[PullRequestFile.model_validate(item) for item in files],
        )

    async def fetch_repository_guidance(
        self, pull_request: PullRequestSnapshot, installation_id: int | None = None
    ) -> list[ContextSource]:
        owner, repository = pull_request.repository.split("/", 1)
        headers = await self._repository_headers(owner, repository, installation_id)
        candidates = set(GUIDANCE_FILES)
        for changed_file in pull_request.files:
            parent = PurePosixPath(changed_file.filename).parent
            if str(parent) != ".":
                candidates.add(str(parent / "AGENTS.md"))

        sources: list[ContextSource] = []
        for path in sorted(candidates)[:12]:
            encoded_path = quote(path, safe="/")
            payload = await self._get_optional(
                f"/repos/{owner}/{repository}/contents/{encoded_path}",
                params={"ref": pull_request.head_sha},
                headers=headers,
            )
            if not payload or not isinstance(payload, dict) or payload.get("type") != "file":
                continue
            try:
                content = base64.b64decode(payload["content"]).decode("utf-8")
            except (KeyError, ValueError, UnicodeDecodeError):
                continue
            sources.append(
                ContextSource(
                    source_id=f"github:{path}",
                    name=path,
                    source_type="repository_guidance",
                    excerpt=content[:4_000],
                    relevance_score=1.0,
                )
            )
        return sources

    async def _fetch_files(
        self,
        owner: str,
        repository: str,
        number: int,
        headers: dict[str, str],
    ) -> list[dict]:
        files: list[dict] = []
        for page in range(1, 4):
            batch = await self._get(
                f"/repos/{owner}/{repository}/pulls/{number}/files",
                params={"per_page": 100, "page": page},
                headers=headers,
            )
            files.extend(batch)
            if len(batch) < 100:
                break
        return files

    async def _get_optional(
        self,
        path: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        try:
            response = await self._client.get(path, params=params, headers=headers)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError:
            return None

    async def _get(
        self,
        path: str,
        params: dict[str, int] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        try:
            response = await self._client.get(path, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                message = "Pull request not found or the repository is private."
            elif status == 403:
                message = "GitHub rate limit reached or the token lacks repository access."
            else:
                message = f"GitHub returned HTTP {status}."
            raise GitHubError(message) from exc
        except httpx.HTTPError as exc:
            raise GitHubError("Could not reach GitHub. Check your network and try again.") from exc

    async def _repository_headers(
        self, owner: str, repository: str, installation_id: int | None
    ) -> dict[str, str]:
        if self._app_auth is None:
            return {}
        try:
            token = await self._app_auth.installation_token(
                installation_id=installation_id,
                owner=owner,
                repository=repository,
            )
            return {"Authorization": f"Bearer {token}"}
        except GitHubAppError as exc:
            if installation_id is not None:
                raise GitHubError(str(exc)) from exc
            return {}
