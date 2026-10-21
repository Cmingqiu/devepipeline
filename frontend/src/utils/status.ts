import type { ProjectStatus, RequirementStatus, VersionSource } from '@/api/types'

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

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
