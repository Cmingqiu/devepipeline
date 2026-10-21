from __future__ import annotations

import pytest

pytestmark = pytest.mark.maria


async def _new_project(client, name: str = "需求项目") -> int:
    resp = await client.post("/api/v1/projects", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_create_requirement_creates_v1(client):
    project_id = await _new_project(client)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"title": "登录改造", "content": "# 登录改造\n\n支持手机号。"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["current_version_no"] == 1
    assert body["version_no"] == 1
    assert body["status"] == "draft"
    assert "手机号" in body["content"]


async def test_list_requirements_with_search(client):
    project_id = await _new_project(client)
    for title in ("支付回调", "退款流程", "风控规则"):
        await client.post(
            f"/api/v1/projects/{project_id}/requirements",
            json={"title": title, "content": "x"},
        )

    all_resp = await client.get(f"/api/v1/projects/{project_id}/requirements")
    assert all_resp.status_code == 200
    assert all_resp.json()["total"] == 3
    # 列表不带正文，避免拉 LONGTEXT
    assert "content" not in all_resp.json()["items"][0]

    search = await client.get(
        f"/api/v1/projects/{project_id}/requirements", params={"q": "退款"}
    )
    assert search.json()["total"] == 1
    assert search.json()["items"][0]["title"] == "退款流程"


async def test_create_version_increments_and_returns_content(client):
    project_id = await _new_project(client)
    req = (
        await client.post(
            f"/api/v1/projects/{project_id}/requirements",
            json={"title": "版本需求", "content": "第一版"},
        )
    ).json()

    resp = await client.post(
        f"/api/v1/requirements/{req['id']}/versions",
        json={"content": "第二版", "note": "补充验收标准"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["version_no"] == 2
    assert resp.json()["source"] == "editor"

    detail = await client.get(f"/api/v1/requirements/{req['id']}")
    assert detail.json()["current_version_no"] == 2
    assert detail.json()["content"] == "第二版"


async def test_version_list_has_no_content_and_desc_order(client):
    project_id = await _new_project(client)
    req = (
        await client.post(
            f"/api/v1/projects/{project_id}/requirements",
            json={"title": "多版本", "content": "v1"},
        )
    ).json()
    await client.post(f"/api/v1/requirements/{req['id']}/versions", json={"content": "v2"})
    await client.post(f"/api/v1/requirements/{req['id']}/versions", json={"content": "v3"})

    resp = await client.get(f"/api/v1/requirements/{req['id']}/versions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert [item["version_no"] for item in body["items"]] == [3, 2, 1]
    assert "content" not in body["items"][0]


async def test_get_specific_version_content(client):
    project_id = await _new_project(client)
    req = (
        await client.post(
            f"/api/v1/projects/{project_id}/requirements",
            json={"title": "回滚", "content": "old"},
        )
    ).json()
    await client.post(f"/api/v1/requirements/{req['id']}/versions", json={"content": "new"})

    resp = await client.get(f"/api/v1/requirements/{req['id']}/versions/1")
    assert resp.status_code == 200
    assert resp.json()["content"] == "old"

    missing = await client.get(f"/api/v1/requirements/{req['id']}/versions/99")
    assert missing.status_code == 404


async def test_upload_markdown_creates_upload_version(client):
    project_id = await _new_project(client)
    req = (
        await client.post(
            f"/api/v1/projects/{project_id}/requirements",
            json={"title": "上传", "content": "base"},
        )
    ).json()

    files = {"file": ("spec.md", "# 上传的需求\n中文😀".encode(), "text/markdown")}
    resp = await client.post(
        f"/api/v1/requirements/{req['id']}/versions/upload",
        files=files,
        data={"note": "从文档导入"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source"] == "upload"
    assert body["note"] == "从文档导入"
    assert "中文😀" in body["content"]


async def test_upload_rejects_non_markdown(client):
    project_id = await _new_project(client)
    req = (
        await client.post(
            f"/api/v1/projects/{project_id}/requirements",
            json={"title": "拒绝", "content": "base"},
        )
    ).json()

    files = {"file": ("spec.txt", b"not markdown", "text/plain")}
    resp = await client.post(
        f"/api/v1/requirements/{req['id']}/versions/upload", files=files
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "semantic_error"


async def test_long_utf8_content_roundtrip(client):
    project_id = await _new_project(client)
    content = ("# 大文本\n\n" + "中文😀 emoji 混排\n") * 2000  # 约 60KB，超过 TEXT 上限的 1/10
    resp = await client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"title": "大文本", "content": content},
    )
    assert resp.status_code == 201, resp.text
    req_id = resp.json()["id"]

    detail = await client.get(f"/api/v1/requirements/{req_id}")
    assert detail.json()["content"] == content


async def test_patch_requirement_title(client):
    project_id = await _new_project(client)
    req = (
        await client.post(
            f"/api/v1/projects/{project_id}/requirements",
            json={"title": "旧标题", "content": "c"},
        )
    ).json()
    resp = await client.patch(f"/api/v1/requirements/{req['id']}", json={"title": "新标题"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "新标题"


async def test_delete_requirement_removes_versions(client):
    project_id = await _new_project(client)
    req = (
        await client.post(
            f"/api/v1/projects/{project_id}/requirements",
            json={"title": "待删", "content": "c"},
        )
    ).json()
    assert (await client.delete(f"/api/v1/requirements/{req['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/requirements/{req['id']}")).status_code == 404

    total = (await client.get(f"/api/v1/projects/{project_id}/requirements")).json()["total"]
    assert total == 0


async def test_requirement_in_unknown_project_is_404(client):
    resp = await client.post(
        "/api/v1/projects/99999999/requirements", json={"title": "x", "content": "y"}
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
