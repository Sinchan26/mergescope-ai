from time import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from mergescope.integrations.github import GitHubClient, GitHubError
from mergescope.integrations.github_app import GitHubAppAuth, GitHubAppError


class RejectedAppAuth:
    async def installation_token(self, **kwargs) -> str:
        raise GitHubAppError("Installation token rejected.")


async def test_github_app_jwt_uses_rs256_and_short_lived_claims() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    auth = GitHubAppAuth(
        app_id="12345",
        private_key=private_key,
        api_url="https://api.github.com",
        api_version="2026-03-10",
        timeout_seconds=2,
    )
    try:
        token = auth.create_jwt()
        claims = jwt.decode(token, key.public_key(), algorithms=["RS256"])
    finally:
        await auth.close()

    assert claims["iss"] == "12345"
    assert claims["iat"] <= int(time())
    assert claims["exp"] - claims["iat"] == 600


async def test_webhook_installation_auth_does_not_fall_back() -> None:
    client = GitHubClient(
        api_url="https://api.github.com",
        token="personal-token",
        timeout_seconds=2,
        app_auth=RejectedAppAuth(),  # type: ignore[arg-type]
    )
    try:
        with pytest.raises(GitHubError, match="Installation token rejected"):
            await client._repository_headers("example", "project", installation_id=501)
    finally:
        await client.close()
