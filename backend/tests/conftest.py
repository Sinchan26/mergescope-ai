import importlib
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from mergescope.core.config import Settings, get_settings
from mergescope.services.auth import SESSION_COOKIE
from mergescope.services.demo import demo_pull_request


class FakeGitHubOAuth:
    def __init__(self):
        self.user_id = 101
        self.revoked = False
        self.repo_access = True
        self.requests = []
        self.refreshes = 0

    def __call__(self, request):
        self.requests.append(request)
        if request.url.path == "/login/oauth/access_token":
            form = parse_qs(request.content.decode())
            self.refreshes += int("refresh_token" in form)
            return httpx.Response(
                200,
                json={
                    "access_token": f"user-{self.user_id}",
                    "expires_in": 28800,
                    "refresh_token": "private-refresh",
                    "refresh_token_expires_in": 100000,
                },
            )
        if self.revoked:
            return httpx.Response(401, json={})
        user_id = int(request.headers["Authorization"].split("user-")[1])
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": user_id, "login": f"developer-{user_id}"})
        if request.url.path == "/user/installations":
            return httpx.Response(200, json={"installations": [{"id": 9}]})
        if request.url.path == "/user/installations/9/repositories":
            repos = (
                [{"id": 123, "full_name": "acme/payments-api", "private": True}]
                if self.repo_access
                else []
            )
            return httpx.Response(200, json={"repositories": repos})
        pull = demo_pull_request()
        prefix = f"/repos/acme/payments-api/pulls/{pull.number}"
        if request.url.path == prefix:
            return httpx.Response(
                200,
                json={
                    "html_url": pull.url,
                    "title": pull.title,
                    "user": {"login": pull.author},
                    "base": {"ref": pull.base_ref},
                    "head": {"ref": pull.head_ref, "sha": pull.head_sha},
                    "body": pull.body,
                },
            )
        if request.url.path == prefix + "/files":
            return httpx.Response(200, json=[file.model_dump() for file in pull.files])
        if request.url.path == prefix + "/reviews":
            return httpx.Response(200, json=[] if request.method == "GET" else {"id": 7788})
        raise AssertionError(f"Unexpected external request: {request.method} {request.url.path}")


@pytest.fixture
async def auth_app(tmp_path, monkeypatch):
    main = importlib.import_module("mergescope.main")
    configured = Settings(
        _env_file=None,
        database_path=tmp_path / "legacy.db",
        github_client_id="test-client",
        github_client_secret="test-secret",
        auth_encryption_key=Fernet.generate_key().decode(),
        allowed_github_user_ids="101,202",
        github_publishing_enabled=True,
        evaluation_run_token="evaluation-secret",
        openai_api_key=None,
    )
    monkeypatch.setattr(main, "settings", configured)
    main.app.dependency_overrides[get_settings] = lambda: configured
    fake = FakeGitHubOAuth()
    async with main.app.router.lifespan_context(main.app):

        class FakeEmbedder:
            async def embed(self, texts):
                return [[1.0, 0.0] for _ in texts]

        main.app.state.embedder = FakeEmbedder()
        await main.app.state.auth.client.aclose()
        main.app.state.auth.client = httpx.AsyncClient(transport=httpx.MockTransport(fake))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://localhost:5173"
        ) as client:
            yield main.app, client, fake
    main.app.dependency_overrides.clear()


async def sign_in(client):
    started = await client.get("/api/auth/login")
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    callback = await client.get(
        "/api/auth/callback", params={"state": state, "code": "single-use-code"}
    )
    assert callback.status_code == 302
    assert client.cookies.get(SESSION_COOKIE)
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    return {"Origin": "http://localhost:5173", "X-MergeScope-CSRF": me.json()["csrf_token"]}
