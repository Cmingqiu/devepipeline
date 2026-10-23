"""VCS 抽象：仓库地址解析 + PR 客户端协议。

只实现 GitHub（httpx 直连 REST，便于 respx 回放与统一超时）；GitLab 只留占位，
本地路径仓库能 push 但不支持建 PR（parse_repo_url 返回 None）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from app.core.exceptions import SemanticError


@dataclass(frozen=True)
class RepoRef:
    """托管平台上的仓库坐标。"""

    provider: str  # github / gitlab
    host: str
    owner: str
    repo: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class PullRequestInfo:
    """与 provider 无关的 PR 结果（落库、事件都用这个）。"""

    provider: str
    repo_full_name: str
    number: int
    url: str
    branch: str
    base_branch: str
    head_sha: str | None = None
    status: str = "open"


class VcsError(SemanticError):
    """VCS 操作失败（网络/鉴权/API 报错），调用方负责降级不阻断流水线。"""

    code = "vcs_error"


class VcsClient(Protocol):
    async def create_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> PullRequestInfo: ...

    async def get_pull_request(
        self, *, owner: str, repo: str, number: int
    ) -> PullRequestInfo: ...


def _split_owner_repo(path: str) -> tuple[str, str] | None:
    parts = [item for item in path.strip("/").split("/") if item]
    if len(parts) != 2:
        return None
    owner, repo = parts[0], parts[1]
    repo = repo.removesuffix(".git")
    if not owner or not repo:
        return None
    return owner, repo


def parse_repo_url(repo_url: str | None) -> RepoRef | None:
    """把仓库地址解析成 RepoRef；本地路径 / 非托管平台返回 None。

    支持 https://github.com/owner/repo(.git)、git@github.com:owner/repo.git、
    ssh://git@github.com/owner/repo.git、http(s)://gitlab.example.com/owner/repo。
    """
    text = (repo_url or "").strip()
    if not text:
        return None

    if text.startswith("git@"):
        # scp 风格没有 scheme，先补成 ssh:// 再解析
        text = "ssh://" + text.replace(":", "/", 1)

    parts = urlsplit(text)
    if parts.scheme not in {"http", "https", "ssh"} or not parts.hostname:
        return None

    split = _split_owner_repo(parts.path)
    if split is None:
        return None
    owner, repo = split

    host = parts.hostname.lower()
    if "github" in host:
        provider = "github"
    elif "gitlab" in host:
        provider = "gitlab"
    else:
        # 企业版自定义域名无法靠域名判断，按配置的 provider 兜底由调用方覆盖
        provider = "unknown"
    return RepoRef(provider=provider, host=host, owner=owner, repo=repo)


__all__ = ["PullRequestInfo", "RepoRef", "VcsClient", "VcsError", "parse_repo_url"]
