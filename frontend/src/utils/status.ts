import type {
  ArtifactKind,
  ProjectStatus,
  PullRequestProvider,
  PullRequestStatus,
  RequirementStatus,
  RunStatus,
  VersionSource,
} from '@/api/types'

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

export const RUN_STATUS_META: Record<RunStatus, { label: string; type: TagType }> = {
  queued: { label: '排队中', type: 'info' },
  running: { label: '运行中', type: 'primary' },
  paused: { label: '已暂停', type: 'warning' },
  waiting_approval: { label: '待审批', type: 'warning' },
  succeeded: { label: '成功', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' },
}

export const ARTIFACT_KIND_META: Record<ArtifactKind, { label: string; type: TagType }> = {
  markdown: { label: 'Markdown', type: 'primary' },
  diff: { label: 'Diff', type: 'warning' },
}

export const PULL_REQUEST_PROVIDER_META: Record<
  PullRequestProvider,
  { label: string; type: TagType }
> = {
  github: { label: 'GitHub', type: 'primary' },
  gitlab: { label: 'GitLab', type: 'warning' },
}

export const PULL_REQUEST_STATUS_META: Record<
  PullRequestStatus,
  { label: string; type: TagType }
> = {
  open: { label: '打开', type: 'primary' },
  merged: { label: '已合并', type: 'success' },
  closed: { label: '已关闭', type: 'info' },
}

export const REQUIREMENT_STATUS_META: Record<RequirementStatus, { label: string; type: TagType }> = {
  draft: { label: '草稿', type: 'info' },
  queued: { label: '排队中', type: 'warning' },
  running: { label: '运行中', type: 'primary' },
  waiting_approval: { label: '待审批', type: 'warning' },
  done: { label: '已完成', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' },
}

export const PROJECT_STATUS_META: Record<ProjectStatus, { label: string; type: TagType }> = {
  active: { label: '进行中', type: 'success' },
  archived: { label: '已归档', type: 'info' },
}

export const VERSION_SOURCE_META: Record<VersionSource, { label: string; type: TagType }> = {
  editor: { label: '编辑器', type: 'primary' },
  upload: { label: '上传', type: 'success' },
  ai: { label: 'AI 生成', type: 'warning' },
}

export function requirementStatusMeta(status: RequirementStatus) {
  return REQUIREMENT_STATUS_META[status] ?? { label: status, type: 'info' as TagType }
}

export function projectStatusMeta(status: ProjectStatus) {
  return PROJECT_STATUS_META[status] ?? { label: status, type: 'info' as TagType }
}

export function versionSourceMeta(source: VersionSource) {
  return VERSION_SOURCE_META[source] ?? { label: source, type: 'info' as TagType }
}

export function runStatusMeta(status: RunStatus) {
  return RUN_STATUS_META[status] ?? { label: status, type: 'info' as TagType }
}

export function artifactKindMeta(kind: ArtifactKind) {
  return ARTIFACT_KIND_META[kind] ?? { label: kind, type: 'info' as TagType }
}

export function pullRequestProviderMeta(provider: PullRequestProvider) {
  return PULL_REQUEST_PROVIDER_META[provider] ?? { label: provider, type: 'info' as TagType }
}

export function pullRequestStatusMeta(status: PullRequestStatus) {
  return PULL_REQUEST_STATUS_META[status] ?? { label: status, type: 'info' as TagType }
}
