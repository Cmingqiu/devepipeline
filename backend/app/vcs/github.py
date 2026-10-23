"""GitHub PR 客户端：httpx 直连 REST（不用 PyGithub 的同步实现，避免线程池与 respx 不可测）。"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.logging import get_logger
from app.vcs.base import PullRequestInfo, VcsError

logger = get_logger(__name__)

ACCEPT = "application/vnd.github+json"
API_VERSION = "2022-11-28"
DEFAULT_API_BASE = "https://api.github.com"


def _status_of(data: dict[str, Any]) -> str:
    if data.get("merged"):
        return "merged"
    state = str(data.get("state") or "open").lower()
    if state in {"open", "closed"}:
        return state
    return "open"


class GitHubClient:
    def __init__(
        self,
        token: str,
        *,
        api_base: str = DEFAULT_API_BASE,
        timeout: float = 20.0,
    ) -> None:
        if not token:
            raise VcsError("缺少 GitHub token，无法创建 PR")
        self._token = token
        self._api_base = (api_base or DEFAULT_API_BASE).rstrip("/")
        self._timeout = timeout

    # ------------------------------------------------------------ 对外接口
    async def create_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> PullRequestInfo:
        payload = {"title": title, "body": body, "head": head, "base": base}
        async with self._client() as client:
            response = await client.post(f"/repos/{owner}/{repo}/pulls", json=payload)
            if response.status_code == 422:
                # 同一分支的 PR 已存在：回查并复用，保证重跑幂等
                existing = await self._find_by_head(client, owner, repo, head)
                if existing is not None:
                    return self._to_info(existing, owner, repo, head, base)
            data = self._json(response, "创建 PR")
            return self._to_info(data, owner, repo, head, base)

    async def get_pull_request(self, *, owner: str, repo: str, number: int) -> PullRequestInfo:
        async with self._client() as client:
            response = await client.get(f"/repos/{owner}/{repo}/pulls/{number}")
            data = self._json(response, f"读取 PR #{number}")
            branch = str((data.get("head") or {}).get("ref") or "")
            base = str((data.get("base") or {}).get("ref") or "")
            return self._to_info(data, owner, repo, branch, base)

    # ------------------------------------------------------------ 内部
    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._api_base,
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": ACCEPT,
                "X-GitHub-Api-Version": API_VERSION,
            },
        )

    async def _find_by_head(
        self, client: httpx.AsyncClient, owner: str, repo: str, head: str
    ) -> dict[str, Any] | None:
        response = await client.get(
            f"/repos/{owner}/{repo}/pulls",
            params={"state": "all", "head": f"{owner}:{head}", "per_page": 1},
        )
        if response.status_code >= 400:
            return None
        items = response.json()
        return items[0] if isinstance(items, list) and items else None

    def _json(self, response: httpx.Response, action: str) -> dict[str, Any]:
        if response.status_code >= 400:
            raise VcsError(
                f"GitHub {action}失败（HTTP {response.status_code}）：{self._error_text(response)}"
            )
        data = response.json()
        if not isinstance(data, dict):
            raise VcsError(f"GitHub {action}返回了非预期结构")
        return data

    @staticmethod
    def _error_text(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return (response.text or "").strip()[:300] or "无响应体"
        message = str(data.get("message") or "").strip() if isinstance(data, dict) else ""
        errors = data.get("errors") if isinstance(data, dict) else None
        detail = message or "无响应体"
        if errors:
            detail = f"{detail}；{str(errors)[:300]}"
        return detail[:500]

    @staticmethod
    def _to_info(
        data: dict[str, Any], owner: str, repo: str, head: str, base: str
    ) -> PullRequestInfo:
        number = int(data.get("number") or 0)
        url = str(data.get("html_url") or "")
        if number <= 0 or not url:
            raise VcsError("GitHub PR 响应缺少 number/html_url")
        head_ref = str((data.get("head") or {}).get("ref") or head)
        base_ref = str((data.get("base") or {}).get("ref") or base)
        head_sha = (data.get("head") or {}).get("sha")
        return PullRequestInfo(
            provider="github",
            repo_full_name=f"{owner}/{repo}",
            number=number,
            url=url,
            branch=head_ref,
            base_branch=base_ref,
            head_sha=str(head_sha) if head_sha else None,
            status=_status_of(data),
        )


__all__ = ["DEFAULT_API_BASE", "GitHubClient"]
