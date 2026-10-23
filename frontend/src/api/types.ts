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

export type RunStatus =
  | 'queued'
  | 'running'
  | 'paused'
  | 'waiting_approval'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

export type RunStage = 'analysis' | 'design' | 'coding' | 'review'

export type ArtifactKind = 'markdown' | 'diff'

export type ApprovalDecision = 'approved' | 'approved_with_edit' | 'rejected' | 'aborted'

export interface Run {
  id: number
  project_id: number
  requirement_id: number
  requirement_version_id: number
  thread_id: string
  status: RunStatus
  current_stage: RunStage | null
  review_round: number
  max_review_rounds: number
  error_code: string | null
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
  prompt_tokens: number
  completion_tokens: number
}

export interface PendingApproval {
  stage: RunStage
  label: string
  attempt: number
  summary: string
  preview: string
  artifact_id: number | null
  checkpoint_id: string | null
}

/** 详情接口在 Run 之外附加 pending_approval（无待审批时可能是 null 或缺字段） */
export interface RunDetail extends Run {
  pending_approval?: PendingApproval | null
}

export interface ApprovalPayload {
  decision: ApprovalDecision
  feedback?: string
  edited_content?: string
}

export interface ApprovalResult {
  id: number
  run_id: number
  stage: RunStage
  artifact_id: number | null
  decision: ApprovalDecision
  feedback: string | null
  decided_by: string | null
  decided_at: string
}

export interface RunState {
  checkpoint_id: string
  stage: string
  next: string[]
  created_at: string
  has_interrupt: boolean
  error: string | null
}

export interface Artifact {
  id: number
  run_id: number
  stage: RunStage
  version: number
  kind: ArtifactKind
  summary: string
  edited_by_human: boolean
  created_at: string
}

/** 单产物详情：含正文 */
export interface ArtifactDetail extends Artifact {
  content: string
}

export type PullRequestProvider = 'github' | 'gitlab'

export type PullRequestStatus = 'open' | 'closed' | 'merged'

/** 运行在 review 阶段创建的 PR */
export interface PullRequest {
  id: number
  run_id: number
  provider: PullRequestProvider
  repo_full_name: string
  number: number
  url: string
  branch: string
  base_branch: string
  head_sha: string | null
  status: PullRequestStatus
  created_at: string
  updated_at: string
}

export type RunEventType =
  | 'run_started'
  | 'run_pausing'
  | 'run_paused'
  | 'run_resumed'
  | 'forked'
  | 'stage_started'
  | 'llm_token'
  | 'tool_started'
  | 'tool_finished'
  | 'progress'
  | 'usage'
  | 'artifact_saved'
  | 'pull_request_created'
  | 'stage_finished'
  | 'interrupt'
  | 'decision'
  | 'error'
  | 'run_finished'

export type BindingScope = 'project' | 'global'

export type BindingSource = 'project' | 'global' | 'env'

/** LLM 提供商（OpenAI 兼容端点）；configured 表示密钥可用 */
export interface Provider {
  id: number
  name: string
  endpoint: string
  model: string
  enabled: boolean
  credential_id: number | null
  configured: boolean
  credential_hint: string | null
  extra: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ProviderCreatePayload {
  name: string
  endpoint: string
  model: string
  api_key?: string
  extra?: Record<string, unknown>
  enabled?: boolean
}

export interface ProviderUpdatePayload {
  name?: string
  endpoint?: string
  model?: string
  api_key?: string
  extra?: Record<string, unknown>
  enabled?: boolean
}

/** 每阶段生效的模型绑定（固定 analysis/design/coding/review 四条） */
export interface ModelBinding {
  stage: RunStage
  provider_id: number | null
  provider_name: string | null
  model: string | null
  params: Record<string, unknown>
  source: BindingSource
  configured: boolean
  /** 项目层原始覆盖值；为空表示继承 provider 默认（不要用生效的 model 回填） */
  override_model: string | null
  override_params: Record<string, unknown>
}

/** PUT /model-bindings 的单条；provider_id=null 表示回退 global/env */
export interface ModelBindingInput {
  stage: RunStage
  provider_id: number | null
  model?: string | null
  params?: Record<string, unknown>
}

export interface ModelBindingSavePayload {
  project_id?: number
  scope: BindingScope
  items: ModelBindingInput[]
}

/** 事件历史与 SSE 归并后的统一结构 */
export interface RunEvent {
  seq: number
  ts: string
  stage: string | null
  type: RunEventType
  payload: Record<string, unknown>
}
