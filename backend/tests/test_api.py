from httpx import ASGITransport, AsyncClient
from mergescope.core.config import Settings, get_settings
from mergescope.main import app


async def test_health_config_history_and_built_frontend_are_available() -> None:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/api/health")
            config = await client.get("/api/config")
            reviews = await client.get("/api/reviews")
            documents = await client.get("/api/knowledge/documents")
            jobs = await client.get("/api/jobs")
            policies = await client.get("/api/policies")
            evaluation_dataset = await client.get("/api/evaluations/dataset")
            evaluation_runs = await client.get("/api/evaluations/runs")
            correlated = await client.get(
                "/api/health", headers={"X-Request-ID": "phase4-test-request"}
            )
            demo = await client.post("/api/reviews/manual", json={"demo_mode": True})
            publish_without_confirmation = await client.post(
                f"/api/reviews/{demo.json()['id']}/publish", json={"confirm": False}
            )
            preview = await client.get(f"/api/reviews/{demo.json()['id']}/publication-preview")
            frontend = await client.get("/")

    assert health.status_code == 200
    assert health.json()["database"] == "connected"
    assert config.status_code == 200
    assert "openai_api_key" not in config.json()
    assert "github_token" not in config.json()
    assert "publish_confirmation_token" not in config.json()
    assert "evaluation_run_token" not in config.json()
    assert reviews.status_code == 200
    assert documents.status_code == 200
    assert jobs.status_code == 200
    assert policies.status_code == 200
    assert evaluation_dataset.status_code == 200
    assert evaluation_dataset.json()["case_count"] == 6
    assert evaluation_runs.status_code == 200
    assert correlated.headers["X-Request-ID"] == "phase4-test-request"
    assert demo.status_code == 201
    assert demo.json()["demo_mode"] is True
    assert demo.json()["result"]["rejected_issue_count"] == 0
    assert publish_without_confirmation.status_code == 422
    assert preview.status_code == 200
    assert preview.json()["can_publish"] is False
    assert frontend.status_code == 200
    assert "MergeScope AI" in frontend.text


async def test_publish_endpoint_requires_operator_token() -> None:
    configured = Settings(
        github_publishing_enabled=True,
        publish_confirmation_token="correct-operator-token",
    )
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                demo = await client.post("/api/reviews/manual", json={"demo_mode": True})
                response = await client.post(
                    f"/api/reviews/{demo.json()['id']}/publish",
                    json={"confirm": True},
                    headers={"X-MergeScope-Publish-Token": "wrong-token"},
                )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_evaluation_endpoint_requires_its_own_operator_token() -> None:
    configured = Settings(
        openai_api_key="test-key",
        evaluation_run_token="correct-evaluation-token",
    )
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/evaluations/runs",
                    json={"confirm_cost": True},
                    headers={"X-MergeScope-Evaluation-Token": "wrong-token"},
                )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
