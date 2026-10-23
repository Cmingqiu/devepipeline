from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.vcs import GitHubClient, VcsError, parse_repo_url, resolve_repo

API = "https://api.github.com"


def _pr_payload(number: int = 7, state: str = "open", merged: bool = False) -> dict:
    return {
        "number": number,
        "html_url": f"https://github.com/acme/demo/pull/{number}",
        "state": state,
        "merged": merged,
        "head": {"ref": "devpipeline/run-1", "sha": "a" * 40},
        "base": {"ref": "main"},
    }


def test_parse_https_repo():
    ref = parse_repo_url("https://github.com/acme/demo.git")
    assert ref is not None
    assert ref.provider == "github"
    assert ref.full_name == "acme/demo"


def test_parse_scp_and_ssh_style():
    for url in ("git@github.com:acme/demo.git", "ssh://git@github.com/acme/demo"):
        ref = parse_repo_url(url)
        assert ref is not None, url
        assert ref.full_name == "acme/demo"


def test_parse_gitlab_and_local():
    assert parse_repo_url("https://gitlab.example.com/acme/demo.git").provider == "gitlab"
    # 本地路径 / file:// 不是托管平台：能 push，但建不了 PR
    assert parse_repo_url(r"D:\repos\demo") is None
    assert parse_repo_url("file:///tmp/demo") is None
    assert parse_repo_url("https://github.com/only-owner") is None
    assert parse_repo_url("") is None


def test_provider_override_for_enterprise_host():
    ref = resolve_repo("https://git.example.com/acme/demo.git", "github")
    assert ref is not None
    assert ref.provider == "github"
    assert ref.full_name == "acme/demo"


@respx.mock
async def test_create_pull_request_maps_response():
    route = respx.post(f"{API}/repos/acme/demo/pulls").mock(
        return_value=httpx.Response(201, json=_pr_payload())
    )
    client = GitHubClient("token-1", api_base=API)

    info = await client.create_pull_request(
        owner="acme",
        repo="demo",
        title="t",
        body="b",
        head="devpipeline/run-1",
        base="main",
    )

    assert info.number == 7
    assert info.url == "https://github.com/acme/demo/pull/7"
    assert info.branch == "devpipeline/run-1"
    assert info.head_sha == "a" * 40
    body = json.loads(route.calls[0].request.content)
    assert body["head"] == "devpipeline/run-1"
    assert route.calls[0].request.headers["Authorization"] == "Bearer token-1"


@respx.mock
async def test_create_pull_request_reuses_existing_on_422():
    """重跑时同分支 PR 已存在：回查 head 并复用，而不是把一次性错误抛给流水线。"""
    respx.post(f"{API}/repos/acme/demo/pulls").mock(
        return_value=httpx.Response(
            422, json={"message": "Validation Failed", "errors": [{"code": "custom"}]}
        )
    )
    lookup = respx.get(f"{API}/repos/acme/demo/pulls").mock(
        return_value=httpx.Response(200, json=[_pr_payload(number=9, merged=True)])
    )
    client = GitHubClient("token-1", api_base=API)

    info = await client.create_pull_request(
        owner="acme", repo="demo", title="t", body="b", head="devpipeline/run-1", base="main"
    )

    assert lookup.called
    assert info.number == 9
    assert info.status == "merged"


@respx.mock
async def test_create_pull_request_raises_with_status():
    respx.post(f"{API}/repos/acme/demo/pulls").mock(
        return_value=httpx.Response(403, json={"message": "Resource not accessible by token"})
    )
    client = GitHubClient("bad-token", api_base=API)

    with pytest.raises(VcsError) as excinfo:
        await client.create_pull_request(
            owner="acme", repo="demo", title="t", body="b", head="h", base="main"
        )

    assert "403" in str(excinfo.value)
    assert "Resource not accessible" in str(excinfo.value)


def test_missing_token_is_rejected():
    with pytest.raises(VcsError):
        GitHubClient("")
