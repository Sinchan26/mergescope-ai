from httpx import ASGITransport, AsyncClient
from mergescope.main import app


async def test_health_config_history_and_built_frontend_are_available() -> None:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/api/health")
            config = await client.get("/api/config")
            reviews = await client.get("/api/reviews")
            documents = await client.get("/api/knowledge/documents")
            demo = await client.post("/api/reviews/manual", json={"demo_mode": True})
            frontend = await client.get("/")

    assert health.status_code == 200
    assert health.json()["database"] == "connected"
    assert config.status_code == 200
    assert "openai_api_key" not in config.json()
    assert "github_token" not in config.json()
    assert reviews.status_code == 200
    assert documents.status_code == 200
    assert demo.status_code == 201
    assert demo.json()["demo_mode"] is True
    assert demo.json()["result"]["rejected_issue_count"] == 0
    assert frontend.status_code == 200
    assert "MergeScope AI" in frontend.text
