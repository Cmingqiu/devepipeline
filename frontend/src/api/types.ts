export type ProjectStatus = 'active' | 'archived'

export type RequirementStatus =
  | 'draft'
  | 'queued'
  | 'running'
  | 'waiting_approval'
  | 'done'
  | 'failed'
  | 'cancelled'

export type VersionSource = 'editor' | 'upload' | 'ai'

/** 后端统一分页响应 */
export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/** 后端统一错误体 */
export interface ApiErrorBody {
  code: string
  message: string
  details: unknown
  trace_id: string | null
}

export interface Project {
  id: number
  name: string
  slug: string
  description: string | null
  status: ProjectStatus
  requirement_count?: number
  created_at: string
  updated_at: string
}

export interface Requirement {
  id: number
  project_id: number
  title: string
  status: RequirementStatus
  current_version_no: number
  latest_run_id: number | null
  created_at: string
  updated_at: string
}

export interface RequirementDetail extends Requirement {
  /** 当前版本正文 */
  content: string
  version_no: number
}

/** 版本列表项：不含正文 */
export interface RequirementVersion {
  id: number
  version_no: number
  source: VersionSource
  note: string | null
  created_by: string | null
  created_at: string
}

/** 单版本详情：含正文 */
export interface RequirementVersionDetail extends RequirementVersion {
  content: string
}
