from __future__ import annotations

import pytest

pytestmark = pytest.mark.pg

ENDPOINT = "https://api.example.com"


async def _create_provider(
    client, name: str = "test-provider", api_key: str | None = "sk-abcdef", **extra
):
    payload = {"name": name, "endpoint": ENDPOINT, "model": "m1", **extra}
    if api_key is not None:
        payload["api_key"] = api_key
    return await client.post("/api/v1/providers", json=payload)


async def _create_project(client, name: str = "模型项目") -> int:
    response = await client.post("/api/v1/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def _bindings(client, project_id: int) -> dict[str, dict]:
    response = await client.get(
        "/api/v1/model-bindings", params={"project_id": project_id}
    )
    assert response.status_code == 200, response.text
    return {item["stage"]: item for item in response.json()}


async def test_create_and_list_provider(client):
    response = await _create_provider(client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["configured"] is True
    assert body["credential_hint"] == "****cdef"
    assert body["endpoint"].endswith("/chat/completions")
    assert body["enabled"] is True

    listed = (await client.get("/api/v1/providers")).json()
    assert any(item["id"] == body["id"] for item in listed)
    # 列表不返回明文 key
    assert "sk-abcdef" not in str(listed)


async def test_provider_without_key_is_not_configured(client):
    response = await _create_provider(client, name="no-key-provider", api_key=None)
    assert response.status_code == 201
    assert response.json()["configured"] is False
    assert response.json()["credential_hint"] is None


async def test_duplicate_provider_name_conflict(client):
    await _create_provider(client, name="dup-provider")
    response = await _create_provider(client, name="dup-provider")
    assert response.status_code == 409


async def test_patch_provider_model_and_key(client):
    provider_id = (await _create_provider(client)).json()["id"]
    response = await client.patch(
        f"/api/v1/providers/{provider_id}",
        json={"model": "m2", "api_key": "sk-zzzz9999", "enabled": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "m2"
    assert body["credential_hint"] == "****9999"
    assert body["enabled"] is False

    # api_key 不传 = 不修改
    response = await client.patch(f"/api/v1/providers/{provider_id}", json={"model": "m3"})
    assert response.json()["credential_hint"] == "****9999"


async def test_bindings_project_scope_and_unbind(client):
    provider_id = (await _create_provider(client)).json()["id"]
    project_id = await _create_project(client)

    response = await client.put(
        "/api/v1/model-bindings",
        json={
            "scope": "project",
            "project_id": project_id,
            "items": [
                {
                    "stage": "analysis",
                    "provider_id": provider_id,
                    "model": "m-override",
                    "params": {"temperature": 0.1},
                },
                {"stage": "coding", "provider_id": provider_id},
            ],
        },
    )
    assert response.status_code == 200, response.text
    rows = {item["stage"]: item for item in response.json()}
    assert rows["analysis"]["source"] == "project"
    assert rows["analysis"]["provider_id"] == provider_id
    assert rows["analysis"]["provider_name"] == "test-provider"
    assert rows["analysis"]["model"] == "m-override"
    assert rows["analysis"]["params"]["temperature"] == 0.1
    assert rows["analysis"]["override_model"] == "m-override"
    assert rows["analysis"]["override_params"]["temperature"] == 0.1
    assert rows["coding"]["model"] == "m1"
    assert rows["coding"]["override_model"] is None
    assert rows["design"]["source"] == "env"

    listed = await _bindings(client, project_id)
    assert listed["analysis"]["provider_id"] == provider_id

    # items=[] 表示该 scope 全部解绑
    response = await client.put(
        "/api/v1/model-bindings",
        json={"scope": "project", "project_id": project_id, "items": []},
    )
    assert {item["stage"]: item for item in response.json()}["analysis"]["source"] == "env"


async def test_global_binding_and_project_override(client):
    provider_id = (await _create_provider(client)).json()["id"]
    project_id = await _create_project(client)

    await client.put(
        "/api/v1/model-bindings",
        json={"scope": "global", "items": [{"stage": "coding", "provider_id": provider_id}]},
    )
    rows = await _bindings(client, project_id)
    assert rows["coding"]["source"] == "global"
    assert rows["coding"]["provider_id"] == provider_id

    await client.put(
        "/api/v1/model-bindings",
        json={
            "scope": "project",
            "project_id": project_id,
            "items": [{"stage": "coding", "provider_id": provider_id, "model": "p-model"}],
        },
    )
    rows = await _bindings(client, project_id)
    assert rows["coding"]["source"] == "project"
    assert rows["coding"]["model"] == "p-model"

    # 清理全局绑定，避免影响其它用例
    await client.put("/api/v1/model-bindings", json={"scope": "global", "items": []})


async def test_delete_provider_in_use_conflict(client):
    provider_id = (await _create_provider(client)).json()["id"]
    project_id = await _create_project(client)

    await client.put(
        "/api/v1/model-bindings",
        json={
            "scope": "project",
            "project_id": project_id,
            "items": [{"stage": "analysis", "provider_id": provider_id}],
        },
    )
    conflict = await client.delete(f"/api/v1/providers/{provider_id}")
    assert conflict.status_code == 409

    await client.put(
        "/api/v1/model-bindings",
        json={"scope": "project", "project_id": project_id, "items": []},
    )
    assert (await client.delete(f"/api/v1/providers/{provider_id}")).status_code == 204


async def test_binding_validation_errors(client):
    provider_id = (await _create_provider(client)).json()["id"]
    project_id = await _create_project(client)

    duplicate = await client.put(
        "/api/v1/model-bindings",
        json={
            "scope": "project",
            "project_id": project_id,
            "items": [
                {"stage": "analysis", "provider_id": provider_id},
                {"stage": "analysis", "provider_id": provider_id},
            ],
        },
    )
    assert duplicate.status_code == 422

    missing_provider = await client.put(
        "/api/v1/model-bindings",
        json={
            "scope": "project",
            "project_id": project_id,
            "items": [{"stage": "analysis", "provider_id": 99999999}],
        },
    )
    assert missing_provider.status_code == 404

    missing_project = await client.put(
        "/api/v1/model-bindings",
        json={
            "scope": "project",
            "project_id": 99999999,
            "items": [{"stage": "analysis", "provider_id": provider_id}],
        },
    )
    assert missing_project.status_code == 404
