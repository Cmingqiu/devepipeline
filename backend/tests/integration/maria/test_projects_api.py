from __future__ import annotations

import pytest

pytestmark = pytest.mark.maria


async def test_healthz_ok(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_create_project_generates_slug(client):
    resp = await client.post("/api/v1/projects", json={"name": "Payment Service"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slug"] == "payment-service"
    assert body["status"] == "active"
    assert body["requirement_count"] == 0
    assert body["created_at"].endswith("Z")


async def test_create_project_with_chinese_name_falls_back_to_random_slug(client):
    resp = await client.post("/api/v1/projects", json={"name": "支付服务"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["slug"].startswith("p-")


async def test_duplicate_slug_conflicts(client):
    first = await client.post("/api/v1/projects", json={"name": "A", "slug": "dup"})
    assert first.status_code == 201
    second = await client.post("/api/v1/projects", json={"name": "B", "slug": "dup"})
    assert second.status_code == 409
    assert second.json()["code"] == "conflict"


async def test_list_projects_paginates_and_counts_requirements(client):
    created = await client.post("/api/v1/projects", json={"name": "Listed"})
    project_id = created.json()["id"]
    await client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"title": "需求一", "content": "# 需求\n内容"},
    )

    resp = await client.get("/api/v1/projects", params={"page": 1, "page_size": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    row = next(item for item in body["items"] if item["id"] == project_id)
    assert row["requirement_count"] == 1


async def test_patch_project_and_detail(client):
    created = (await client.post("/api/v1/projects", json={"name": "Patch Me"})).json()
    patch = await client.patch(
        f"/api/v1/projects/{created['id']}", json={"name": "Patched", "status": "archived"}
    )
    assert patch.status_code == 200
    assert patch.json()["name"] == "Patched"
    assert patch.json()["status"] == "archived"

    detail = await client.get(f"/api/v1/projects/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["slug"] == created["slug"]


async def test_delete_project_without_requirements(client):
    created = (await client.post("/api/v1/projects", json={"name": "Delete Me"})).json()
    resp = await client.delete(f"/api/v1/projects/{created['id']}")
    assert resp.status_code == 204
    assert (await client.get(f"/api/v1/projects/{created['id']}")).status_code == 404


async def test_delete_project_with_requirements_conflicts(client):
    created = (await client.post("/api/v1/projects", json={"name": "Has Req"})).json()
    await client.post(
        f"/api/v1/projects/{created['id']}/requirements",
        json={"title": "r", "content": "c"},
    )
    resp = await client.delete(f"/api/v1/projects/{created['id']}")
    assert resp.status_code == 409
    assert "需求" in resp.json()["message"]


async def test_validation_error_shape(client):
    resp = await client.post("/api/v1/projects", json={"name": ""})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "validation_error"
    assert body["trace_id"]
    assert isinstance(body["details"], list)
