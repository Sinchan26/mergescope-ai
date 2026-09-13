"""GitHub App user OAuth. Tokens never leave encrypted, server-side storage.

The supported SQLite deployment uses one application process. The refresh lock
serializes rotating refresh tokens, and OAuth state is consumed atomically.
"""

import asyncio
import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

import aiosqlite
import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request

from mergescope.core.config import Settings

SESSION_COOKIE = "mergescope_session"
OAUTH_COOKIE = "mergescope_oauth"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass
class Session:
    key: str = field(repr=False)
    user_id: int
    login: str
    csrf: str = field(repr=False)
    token: str = field(repr=False)


class AuthService:
    def __init__(self, settings: Settings, *, transport=None):
        self.settings = settings
        self.path = settings.resolved_database_path.with_suffix(".auth.db")
        self.cipher = (
            Fernet(settings.auth_encryption_key.encode()) if settings.auth_encryption_key else None
        )
        self.client = httpx.AsyncClient(
            timeout=settings.github_timeout_seconds, transport=transport, follow_redirects=False
        )
        self.lock = asyncio.Lock()

    async def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions
                    (key TEXT PRIMARY KEY, payload BLOB NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS oauth_states
                    (key TEXT PRIMARY KEY, browser TEXT NOT NULL,
                     verifier BLOB NOT NULL, expires REAL NOT NULL);
            """)
        self.path.chmod(0o600)

    async def close(self):
        await self.client.aclose()

    def require_configured(self):
        if not self.settings.github_login_ready:
            raise HTTPException(503, "GitHub login is not configured. Follow docs/github-login.md.")

    def encrypt(self, data: dict) -> bytes:
        return self.cipher.encrypt(json.dumps(data).encode())

    def decrypt(self, data: bytes) -> dict:
        try:
            return json.loads(self.cipher.decrypt(data))
        except (InvalidToken, ValueError):
            raise HTTPException(401, "Session expired. Sign in again.") from None

    async def start(self) -> tuple[str, str]:
        self.require_configured()
        state, browser, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM oauth_states WHERE expires < ?", (time.time(),))
            await db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            await db.execute(
                "INSERT INTO oauth_states VALUES (?, ?, ?, ?)",
                (
                    digest(state),
                    digest(browser),
                    self.encrypt({"verifier": verifier}),
                    time.time() + 600,
                ),
            )
            await db.commit()
        query = urlencode(
            {
                "client_id": self.settings.github_client_id,
                "redirect_uri": self.settings.github_callback_url,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"https://github.com/login/oauth/authorize?{query}", browser

    async def exchange(self, data: dict) -> dict:
        try:
            response = await self.client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": self.settings.github_client_id,
                    "client_secret": self.settings.github_client_secret,
                    **data,
                },
            )
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(
                502, "GitHub authentication is unavailable. Try signing in again."
            ) from None
        if (
            response.status_code != 200
            or not isinstance(payload, dict)
            or not payload.get("access_token")
        ):
            raise HTTPException(401, "GitHub authorization expired or was rejected. Sign in again.")
        return payload

    async def finish(self, state: str, browser: str, code: str) -> str:
        self.require_configured()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "DELETE FROM oauth_states WHERE key = ? AND browser = ? AND expires > ? "
                "RETURNING verifier",
                (digest(state), digest(browser), time.time()),
            )
            row = await cursor.fetchone()
            await cursor.close()
            await db.commit()
        if not row:
            raise HTTPException(400, "Invalid or expired login state. Start sign-in again.")
        tokens = await self.exchange(
            {
                "code": code,
                "redirect_uri": self.settings.github_callback_url,
                "code_verifier": self.decrypt(row[0])["verifier"],
            }
        )
        user = await self.api(tokens["access_token"], "GET", "/user")
        user_id = int(user["id"])
        self.require_allowed_user(user_id)
        key = secrets.token_urlsafe(32)
        data = {
            "user_id": user_id,
            "login": user["login"],
            "csrf": secrets.token_urlsafe(32),
            **self.token_fields(tokens),
        }
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?)",
                (digest(key), self.encrypt(data), time.time() + self.settings.session_ttl_seconds),
            )
            await db.commit()
        return key

    def require_allowed_user(self, user_id: int):
        if user_id not in self.settings.allowed_user_ids:
            raise HTTPException(
                403,
                f"GitHub user ID {user_id} is not enabled on this server. "
                "Ask the operator to add it to ALLOWED_GITHUB_USER_IDS.",
            )

    @staticmethod
    def token_fields(tokens: dict) -> dict:
        return {
            "token": tokens["access_token"],
            "token_expires": time.time() + int(tokens.get("expires_in", 28800)),
            "refresh": tokens.get("refresh_token"),
            "refresh_expires": time.time() + int(tokens.get("refresh_token_expires_in", 0)),
        }

    async def delete(self, key: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM sessions WHERE key = ?", (digest(key),))
            await db.commit()

    async def session(self, key: str) -> Session:
        self.require_configured()
        async with self.lock:
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute(
                    "SELECT payload FROM sessions WHERE key = ? AND expires > ?",
                    (digest(key), time.time()),
                )
                row = await cursor.fetchone()
                if not row:
                    raise HTTPException(401, "Sign in with GitHub to continue.")
                data = self.decrypt(row[0])
                self.require_allowed_user(data["user_id"])
                if data["token_expires"] < time.time() + 120:
                    if not data["refresh"] or data["refresh_expires"] < time.time():
                        raise HTTPException(401, "GitHub session expired. Sign in again.")
                    tokens = await self.exchange(
                        {"grant_type": "refresh_token", "refresh_token": data["refresh"]}
                    )
                    data.update(self.token_fields(tokens))
                    await db.execute(
                        "UPDATE sessions SET payload = ? WHERE key = ?",
                        (self.encrypt(data), digest(key)),
                    )
                    await db.commit()
        try:
            user = await self.api(data["token"], "GET", "/user")
        except HTTPException as exc:
            if exc.status_code == 401:
                await self.delete(key)
            raise
        if int(user["id"]) != data["user_id"]:
            await self.delete(key)
            raise HTTPException(401, "GitHub identity changed. Sign in again.")
        return Session(
            key=key,
            user_id=data["user_id"],
            login=user["login"],
            csrf=data["csrf"],
            token=data["token"],
        )

    async def api(self, token: str, method: str, path: str, **kwargs):
        try:
            response = await self.client.request(
                method,
                f"{self.settings.github_api_url.rstrip('/')}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": self.settings.github_api_version,
                },
                **kwargs,
            )
        except httpx.HTTPError:
            raise HTTPException(502, "GitHub is unavailable. Try again shortly.") from None
        if response.status_code == 401:
            raise HTTPException(401, "GitHub authorization was revoked or expired. Sign in again.")
        if response.status_code in {403, 404}:
            raise HTTPException(
                403,
                "GitHub access denied. Check App installation, repository permissions, "
                "or API rate limits.",
            )
        if response.is_error or response.is_redirect:
            raise HTTPException(502, "GitHub could not complete the request. Try again shortly.")
        try:
            return response.json()
        except ValueError:
            raise HTTPException(502, "GitHub returned an invalid response.") from None

    async def pages(self, session: Session, path: str, key: str):
        items = []
        for page in range(1, 101):
            result = await self.api(
                session.token, "GET", path, params={"per_page": 100, "page": page}
            )
            batch = result[key]
            items.extend(batch)
            if len(batch) < 100:
                return items
        raise HTTPException(503, "Repository access list is too large. Contact the operator.")

    async def repositories(self, session: Session) -> list[dict]:
        installations = await self.pages(session, "/user/installations", "installations")
        repos = {}
        for installation in installations:
            if installation.get("suspended_at"):
                continue
            selected = await self.pages(
                session,
                f"/user/installations/{int(installation['id'])}/repositories",
                "repositories",
            )
            for repo in selected:
                name = repo["full_name"]
                if (
                    self.settings.allowed_repository_set
                    and name.lower() not in self.settings.allowed_repository_set
                ):
                    continue
                repos[repo["id"]] = {
                    "id": repo["id"],
                    "full_name": name,
                    "private": repo["private"],
                    "installation_id": installation["id"],
                }
        return sorted(repos.values(), key=lambda repo: repo["full_name"].lower())


async def require_session(request: Request) -> Session:
    auth = request.app.state.auth
    key = request.cookies.get(SESSION_COOKIE)
    if not key:
        raise HTTPException(401, "Sign in with GitHub to continue.")
    session = await auth.session(key)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        csrf = request.headers.get("X-MergeScope-CSRF", "")
        if origin != auth.settings.app_origin.rstrip("/") or not secrets.compare_digest(
            csrf, session.csrf
        ):
            raise HTTPException(
                403, "Request security check failed. Refresh the page and try again."
            )
    request.state.session = session
    return session
