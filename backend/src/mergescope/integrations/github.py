import re
from urllib.parse import urlparse

import httpx

from mergescope.domain.models import PullRequestFile, PullRequestSnapshot

PR_PATH = re.compile(r"^/([^/]+)/([^/]+)/pull/(\d+)/?$")


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
    def __init__(self, api_url: str, token: str | None, timeout_seconds: float) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "MergeScope-AI",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(
            base_url=api_url.rstrip("/"), headers=headers, timeout=timeout_seconds
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_pull_request(self, url: str) -> PullRequestSnapshot:
        owner, repository, number = parse_github_pr_url(url)
        pull = await self._get(f"/repos/{owner}/{repository}/pulls/{number}")
        files = await self._fetch_files(owner, repository, number)
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

    async def _fetch_files(self, owner: str, repository: str, number: int) -> list[dict]:
        files: list[dict] = []
        for page in range(1, 4):
            batch = await self._get(
                f"/repos/{owner}/{repository}/pulls/{number}/files",
                params={"per_page": 100, "page": page},
            )
            files.extend(batch)
            if len(batch) < 100:
                break
        return files

    async def _get(self, path: str, params: dict[str, int] | None = None) -> dict | list[dict]:
        try:
            response = await self._client.get(path, params=params)
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
