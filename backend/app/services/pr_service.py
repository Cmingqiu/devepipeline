"""PR 交付：编码审批通过后，把沙箱分支推上远端并建 / 复用 PR。

约定：
- 没有可提交的改动且没有历史 PR → 返回 None（不建空 PR）；
- 推送失败 / API 报错 → 抛 `VcsError`，由调用方降级（评审继续用本地 diff）；
- 同一 run 每个 provider 只有一条 `pull_requests`，评审驳回重跑时更新 head_sha。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import decrypt_secret
from app.db.base import utcnow
from app.db.session import get_session_factory
from app.models import CodeWorkspace, Credential, PipelineRun, Project, PullRequest, Requirement
from app.sandbox.worktree import Workspace
from app.vcs import PullRequestInfo, VcsClient, VcsError, build_vcs_client, resolve_repo

logger = get_logger(__name__)

COMMIT_PREFIX = "devpipeline:"


@dataclass
class PullRequestResult:
    info: PullRequestInfo
    created: bool


async def ensure_pull_request(
    run_id: int,
    workspace: Workspace | None,
    *,
    client: VcsClient | None = None,
) -> PullRequestResult | None:
    """返回 None 表示无需建 PR（没仓库/本地仓库/无改动）；失败抛 VcsError。"""
    if workspace is None:
        logger.info("pr_skipped", extra={"run_id": run_id, "reason": "no_sandbox"})
        return None

    async with get_session_factory()() as session:
        run = await session.get(PipelineRun, run_id)
        if run is None:
            return None
        project = await session.get(Project, run.project_id)
        if project is None or not project.repo_url:
            logger.info("pr_skipped", extra={"run_id": run_id, "reason": "no_repo"})
            return None
        ref = resolve_repo(project.repo_url, project.repo_provider)
        if ref is None:
            # 本地路径仓库：能 push 但没有托管平台，谈不上 PR
            logger.info("pr_skipped", extra={"run_id": run_id, "reason": "local_repo"})
            return None
        requirement = await session.get(Requirement, run.requirement_id)
        existing = (
            await session.execute(
                select(PullRequest).where(
                    PullRequest.run_id == run_id, PullRequest.provider == ref.provider
                )
            )
        ).scalar_one_or_none()
        token: str | None = None
        if project.credential_id:
            credential = await session.get(Credential, project.credential_id)
            if credential is not None:
                token = decrypt_secret(credential.encrypted_blob, credential.key_version)
        title = _pr_title(run_id, requirement.title if requirement else "")
        body = _pr_body(run, project, requirement)

    if client is None:
        client = build_vcs_client(ref, token)

    head_sha: str | None = None
    committed = False
    if await workspace.has_changes():
        head_sha = await workspace.commit(f"{COMMIT_PREFIX} run {run_id} {title}")
        committed = head_sha is not None
    if head_sha is None:
        head_sha = await workspace.head()

    if not committed and existing is None:
        # 编码阶段没产生文件改动：不推空分支、不建空 PR
        logger.info("pr_skipped", extra={"run_id": run_id, "reason": "no_changes"})
        return None

    pushed = await workspace.push(token)
    if not pushed.ok:
        raise VcsError(
            f"推送分支失败：{(pushed.stderr or pushed.stdout or '无输出').strip()[:400]}"
        )

    if existing is not None:
        result = await _refresh_existing(existing.id, head_sha)
        await mark_workspace_head(run_id, head_sha)
        return result

    info = await client.create_pull_request(
        owner=ref.owner,
        repo=ref.repo,
        title=title,
        body=body,
        head=workspace.branch,
        base=workspace.base_branch,
    )
    if info.head_sha is None:
        # API 没回 head sha 时用本地提交补齐，事件与库里别出现 null
        info = replace(info, head_sha=head_sha)
    await _save(run_id, info, head_sha)
    await mark_workspace_head(run_id, info.head_sha or head_sha)
    logger.info(
        "pull_request_created",
        extra={"run_id": run_id, "number": info.number, "provider": info.provider},
    )
    return PullRequestResult(info=info, created=True)


async def _refresh_existing(pr_id: int, head_sha: str | None) -> PullRequestResult:
    async with get_session_factory()() as session:
        row = await session.get(PullRequest, pr_id)
        if row is None:
            raise VcsError("PR 记录已被删除")
        if head_sha:
            row.head_sha = head_sha
        row.updated_at = utcnow()
        await session.commit()
        info = _to_info(row)
    return PullRequestResult(info=info, created=False)


async def _save(run_id: int, info: PullRequestInfo, head_sha: str | None) -> None:
    async with get_session_factory()() as session:
        row = PullRequest(
            run_id=run_id,
            provider=info.provider,
            repo_full_name=info.repo_full_name,
            number=info.number,
            url=info.url,
            branch=info.branch,
            base_branch=info.base_branch,
            head_sha=info.head_sha or head_sha,
            status=info.status,
        )
        session.add(row)
        await session.commit()


async def mark_workspace_head(run_id: int, head_sha: str | None) -> None:
    """把沙箱最新提交写回 code_workspaces，前端/排查都能看到。"""
    if not head_sha:
        return
    async with get_session_factory()() as session:
        row = (
            await session.execute(
                select(CodeWorkspace)
                .where(CodeWorkspace.run_id == run_id)
                .order_by(CodeWorkspace.attempt.desc())
            )
        ).scalars().first()
        if row is None:
            return
        row.head_sha = head_sha
        await session.commit()


def _to_info(row: PullRequest) -> PullRequestInfo:
    return PullRequestInfo(
        provider=row.provider,
        repo_full_name=row.repo_full_name,
        number=row.number,
        url=row.url,
        branch=row.branch,
        base_branch=row.base_branch,
        head_sha=row.head_sha,
        status=row.status,
    )


def _pr_title(run_id: int, requirement_title: str) -> str:
    title = f"[devpipeline] run {run_id} {requirement_title}".strip()
    return title[:200]


def _pr_body(run: PipelineRun, project: Project, requirement: Requirement | None) -> str:
    settings = get_settings()
    lines = [
        "## DevPipeline 自动创建",
        "",
        f"- 运行：# {run.id}（{settings.api_base_url}/runs/{run.id}）",
        f"- 项目：{project.name}",
    ]
    if requirement is not None:
        lines.append(f"- 需求：{requirement.title}（v{requirement.current_version_no}）")
    lines += [
        "",
        "代码改动与测试记录见运行详情页的 `coding` 产物；评审意见见 `review` 产物。",
    ]
    return "\n".join(lines)


__all__ = ["COMMIT_PREFIX", "PullRequestResult", "ensure_pull_request", "mark_workspace_head"]
