import asyncio
import base64
import hashlib
import time
from urllib.parse import parse_qs, urlparse

import aiosqlite
import httpx
import pytest
from conftest import sign_in
from fastapi import HTTPException
from mergescope.api.workspace import UserGitHubClient, UserRepository
from mergescope.core.config import Settings
from mergescope.services.auth import OAUTH_COOKIE, SESSION_COOKIE, digest
from test_publication import completed_review


async def test_oauth_pkce_browser_binding_and_single_use(auth_app):
    app, client, fake = auth_app
    started = await client.get("/api/auth/login")
    params = parse_qs(urlparse(started.headers["location"]).query)
    assert params["code_challenge_method"] == ["S256"]
    assert "httponly" in started.headers["set-cookie"].lower()
    state = params["state"][0]
    browser = client.cookies.get(OAUTH_COOKIE)
    with pytest.raises(HTTPException) as bad:
        await app.state.auth.finish(state, "different-browser", "code")
    assert bad.value.status_code == 400
    await app.state.auth.finish(state, browser, "code")
    exchange = next(req for req in fake.requests if req.url.path.endswith("access_token"))
    verifier = parse_qs(exchange.content.decode())["code_verifier"][0]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    assert challenge == params["code_challenge"][0]
    with pytest.raises(HTTPException):
        await app.state.auth.finish(state, browser, "code")


async def test_tokens_encrypted_logout_revokes_local_session(auth_app):
    app, client, _ = auth_app
    headers = await sign_in(client)
    key = client.cookies.get(SESSION_COOKIE)
    raw = app.state.auth.path.read_bytes()
    assert b"user-101" not in raw and b"private-refresh" not in raw and key.encode() not in raw
    me = await client.get("/api/auth/me")
    assert set(me.json()) == {"user", "csrf_token"}
    assert (await client.post("/api/auth/logout", headers=headers)).status_code == 204
    client.cookies.set(SESSION_COOKIE, key)
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_disallowed_user_and_revoked_grant(auth_app):
    app, client, fake = auth_app
    fake.user_id = 999
    url, browser = await app.state.auth.start()
    state = parse_qs(urlparse(url).query)["state"][0]
    with pytest.raises(HTTPException) as denied:
        await app.state.auth.finish(state, browser, "code")
    assert denied.value.status_code == 403
    fake.user_id = 101
    await sign_in(client)
    fake.revoked = True
    assert (await client.get("/api/reviews")).status_code == 401


async def test_user_workspaces_isolate_reviews_documents_evaluations_and_cache(auth_app):
    app, client, fake = auth_app
    headers = await sign_in(client)
    first = await client.post("/api/reviews/manual", json={"demo_mode": True}, headers=headers)
    document = await client.post(
        "/api/knowledge/documents",
        files={"file": ("rules.md", b"# Rule\nValidate every request.", "text/markdown")},
        headers=headers,
    )
    assert document.status_code == 201, document.text
    review_id, document_id = first.json()["id"], document.json()["id"]
    await client.post("/api/auth/logout", headers=headers)
    fake.user_id = 202
    headers = await sign_in(client)
    assert (await client.get("/api/reviews")).json()["total"] == 0
    assert (await client.get("/api/knowledge/documents")).json()["total"] == 0
    assert (await client.get("/api/evaluations/runs")).json()["total"] == 0
    assert (await client.get(f"/api/reviews/{review_id}")).status_code == 404
    assert (await client.get(f"/api/reviews/{review_id}/publication-preview")).status_code == 404
    assert (
        await client.delete(f"/api/knowledge/documents/{document_id}", headers=headers)
    ).status_code == 404
    second_doc = await client.post(
        "/api/knowledge/documents",
        files={"file": ("rules.md", b"# Rule\nValidate every request.", "text/markdown")},
        headers=headers,
    )
    assert second_doc.status_code == 201 and second_doc.json()["id"] != document_id
    root = app.state.auth.settings.resolved_database_path.parent / "legacy-users"
    one, two = UserRepository(root / "101.db", {}), UserRepository(root / "202.db", {})
    cached = completed_review("cached")
    cached.cache_key = "same-input"
    await one.create(cached)
    assert await two.find_cached("same-input") is None
    assert not app.state.auth.settings.resolved_database_path.exists()  # legacy untouched


async def test_revoked_repo_blocks_history_and_publisher_and_arbitrary_public_repo(auth_app):
    app, client, fake = auth_app
    await sign_in(client)
    await client.get("/api/reviews")  # initialize workspace
    root = app.state.auth.settings.resolved_database_path.parent / "legacy-users"
    repository = UserRepository(root / "101.db", {"acme/payments-api": 123})
    await repository.create(completed_review("private-review"))
    assert (await client.get("/api/reviews/private-review")).status_code == 200
    session = await app.state.auth.session(client.cookies.get(SESSION_COOKIE))
    github = UserGitHubClient(app.state.auth, session)
    try:
        with pytest.raises(HTTPException) as denied:
            await github.fetch_pull_request("https://github.com/stranger/public/pull/1")
        assert denied.value.status_code == 403
        fake.repo_access = False
        assert (await client.get("/api/reviews")).json()["total"] == 0
        assert (await client.get("/api/reviews/private-review")).status_code == 404
        with pytest.raises(HTTPException):
            await github.request_as_user(
                "POST",
                "/repos/acme/payments-api/pulls/1/reviews",
                owner="acme",
                repository="payments-api",
                json={},
            )
        assert not any(
            req.method == "POST" and req.url.path.startswith("/repos/") for req in fake.requests
        )
    finally:
        await github.close()


async def test_refresh_is_serialized_and_session_expiry_is_enforced(auth_app):
    app, client, fake = auth_app
    await sign_in(client)
    key = client.cookies.get(SESSION_COOKIE)
    auth = app.state.auth
    async with aiosqlite.connect(auth.path) as db:
        cursor = await db.execute("SELECT payload FROM sessions WHERE key = ?", (digest(key),))
        data = auth.decrypt((await cursor.fetchone())[0])
        data["token_expires"] = time.time() - 1
        await db.execute(
            "UPDATE sessions SET payload = ? WHERE key = ?", (auth.encrypt(data), digest(key))
        )
        await db.commit()
    await asyncio.gather(auth.session(key), auth.session(key))
    assert fake.refreshes == 1
    async with aiosqlite.connect(auth.path) as db:
        await db.execute("UPDATE sessions SET expires = 0")
        await db.commit()
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_repository_pagination_allowlist_and_suspended_installations(auth_app):
    app, client, _ = auth_app
    await sign_in(client)
    session = await app.state.auth.session(client.cookies.get(SESSION_COOKIE))

    def handler(request):
        if request.url.path == "/user/installations":
            return httpx.Response(
                200, json={"installations": [{"id": 1}, {"id": 2, "suspended_at": "today"}]}
            )
        assert "/1/" in request.url.path
        page = request.url.params["page"]
        items = (
            [
                {"id": index, "full_name": f"acme/repo-{index}", "private": True}
                for index in range(100)
            ]
            if page == "1"
            else [{"id": 999, "full_name": "acme/allowed", "private": True}]
        )
        return httpx.Response(200, json={"repositories": items})

    await app.state.auth.client.aclose()
    app.state.auth.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app.state.auth.settings.allowed_repositories = "acme/allowed"
    repos = await app.state.auth.repositories(session)
    assert [repo["full_name"] for repo in repos] == ["acme/allowed"]


def test_production_auth_configuration_fails_closed():
    with pytest.raises(ValueError):
        Settings(_env_file=None, app_origin="http://public.example")
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            app_origin="https://example.com",
            github_callback_url="https://example.com/api/auth/callback",
            auth_cookie_secure=False,
        )
    with pytest.raises(ValueError):
        Settings(_env_file=None, github_callback_url="https://attacker.example/api/auth/callback")


async def test_signed_in_publisher_uses_user_token_without_shared_token(auth_app):
    app, client, fake = auth_app
    app.state.policy_registry.default_policy.publish_comments = True
    headers = await sign_in(client)
    await client.get("/api/reviews")
    path = app.state.auth.settings.resolved_database_path.parent / "legacy-users" / "101.db"
    repository = UserRepository(path, {"acme/payments-api": 123})
    await repository.create(completed_review("publish-as-user"))
    response = await client.post(
        "/api/reviews/publish-as-user/publish", json={"confirm": True}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["github_review_id"] == 7788
    repeated = await client.post(
        "/api/reviews/publish-as-user/publish", json={"confirm": True}, headers=headers
    )
    assert repeated.status_code == 200
    writes = [
        req for req in fake.requests if req.method == "POST" and req.url.path.startswith("/repos/")
    ]
    assert len(writes) == 1
    assert writes[0].headers["Authorization"] == "Bearer user-101"


async def test_repository_name_reuse_does_not_expose_old_reviews(tmp_path):
    original = UserRepository(tmp_path / "user.db", {"acme/payments-api": 123})
    await original.initialize()
    run = completed_review("old-repository")
    run.cache_key = "cache"
    await original.create(run)
    replacement = UserRepository(tmp_path / "user.db", {"acme/payments-api": 456})
    assert await replacement.get(run.id) is None
    assert (await replacement.list()).total == 0
    assert await replacement.find_cached("cache") is None
