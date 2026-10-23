"""VCS 入口：按项目配置解析仓库坐标并造 PR 客户端。

`repo_provider` 优先于域名推断（GitHub Enterprise 自定义域名靠域名字段判断不出来）。
"""

from __future__ import annotations

from dataclasses import replace

from app.core.config import get_settings
from app.vcs.base import PullRequestInfo, RepoRef, VcsClient, VcsError, parse_repo_url
from app.vcs.github import DEFAULT_API_BASE, GitHubClient


def resolve_repo(repo_url: str | None, repo_provider: str | None = None) -> RepoRef | None:
    ref = parse_repo_url(repo_url)
    if ref is None:
        return None
    provider = (repo_provider or "").strip().lower()
    if provider in {"github", "gitlab"}:
        ref = replace(ref, provider=provider)
    return ref


def build_vcs_client(ref: RepoRef, token: str | None) -> VcsClient:
    if ref.provider == "github":
        return GitHubClient(
            token or "",
            api_base=get_settings().github_api_base or DEFAULT_API_BASE,
        )
    if ref.provider == "gitlab":
        raise VcsError("GitLab PR 暂未实现（当前只支持 GitHub）")
    raise VcsError(f"无法识别的仓库托管平台：{ref.host or ref.provider}")


__all__ = [
    "GitHubClient",
    "PullRequestInfo",
    "RepoRef",
    "VcsClient",
    "VcsError",
    "build_vcs_client",
    "parse_repo_url",
    "resolve_repo",
]
