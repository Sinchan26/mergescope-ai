from conftest import sign_in


async def test_private_endpoints_require_login(auth_app):
    _, client, _ = auth_app
    assert (await client.get("/api/health")).json() == {"status": "ok"}
    for path in [
        "readiness",
        "config",
        "reviews",
        "jobs",
        "policies",
        "knowledge/documents",
        "evaluations/dataset",
        "evaluations/runs",
        "reviews/missing/publication-preview",
    ]:
        response = await client.get(f"/api/{path}")
        assert response.status_code == 401, path
        assert response.headers["cache-control"] == "no-store"
    response = await client.post("/api/reviews/manual", json={"demo_mode": True})
    assert response.status_code == 401


async def test_signed_in_dashboard_and_demo(auth_app):
    _, client, _ = auth_app
    headers = await sign_in(client)
    for path in [
        "readiness",
        "config",
        "reviews",
        "jobs",
        "policies",
        "knowledge/documents",
        "evaluations/dataset",
        "evaluations/runs",
    ]:
        response = await client.get(f"/api/{path}")
        assert response.status_code == 200, response.text
        assert "test-secret" not in response.text
    demo = await client.post("/api/reviews/manual", json={"demo_mode": True}, headers=headers)
    assert demo.status_code == 201
    review_id = demo.json()["id"]
    preview = await client.get(f"/api/reviews/{review_id}/publication-preview")
    assert preview.status_code == 200 and not preview.json()["can_publish"]
    invalid = await client.post(
        f"/api/reviews/{review_id}/publish", json={"confirm": False}, headers=headers
    )
    assert invalid.status_code == 422
    # A signed-in publication needs no shared operator token; demo safeguard still applies.
    blocked = await client.post(
        f"/api/reviews/{review_id}/publish", json={"confirm": True}, headers=headers
    )
    assert blocked.status_code == 409 and "Demo" in blocked.text
    assert (await client.get("/")).status_code == 200


async def test_csrf_origin_and_evaluation_operator_protection(auth_app):
    _, client, _ = auth_app
    headers = await sign_in(client)
    for bad_headers in [
        {},
        {**headers, "Origin": "https://attacker.example"},
        {**headers, "X-MergeScope-CSRF": "wrong"},
    ]:
        for path, payload in [
            ("reviews/manual", {"demo_mode": True}),
            ("reviews/missing/publish", {"confirm": True}),
            ("auth/logout", {}),
        ]:
            assert (
                await client.post(f"/api/{path}", json=payload, headers=bad_headers)
            ).status_code == 403
    response = await client.post(
        "/api/evaluations/runs",
        json={"confirm_cost": True},
        headers={**headers, "X-MergeScope-Evaluation-Token": "wrong"},
    )
    assert response.status_code == 403
    assert (await client.post("/api/webhooks/github", headers=headers)).status_code == 410
