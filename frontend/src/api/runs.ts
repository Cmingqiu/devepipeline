import { http } from './client'
import type {
  ApprovalPayload,
  ApprovalResult,
  Artifact,
  ArtifactDetail,
  Page,
  PendingApproval,
  PullRequest,
  Run,
  RunDetail,
  RunEvent,
  RunStage,
  RunState,
  RunStatus,
} from './types'

export interface RunListParams {
  page?: number
  page_size?: number
  project_id?: number
  requirement_id?: number
  status?: RunStatus
}

export interface RunCreatePayload {
  version_no?: number
  max_review_rounds?: number
}

export interface RunForkPayload {
  checkpoint_id: string
  from_stage?: RunStage
}

export interface ArtifactListParams {
  page?: number
  page_size?: number
}

export interface RunEventListParams {
  after_seq?: number
  page_size?: number
  types?: string
}

export function listRunEvents(
  runId: number,
  params: RunEventListParams = {},
): Promise<RunEvent[]> {
  return http
    .get<RunEvent[]>(`/runs/${runId}/events`, { params })
    .then((response) => response.data)
}

export function listRuns(params: RunListParams = {}): Promise<Page<Run>> {
  return http.get<Page<Run>>('/runs', { params }).then((response) => response.data)
}

export function getRun(runId: number): Promise<RunDetail> {
  return http.get<RunDetail>(`/runs/${runId}`).then((response) => response.data)
}

export function createRun(requirementId: number, payload: RunCreatePayload = {}): Promise<Run> {
  return http
    .post<Run>(`/requirements/${requirementId}/runs`, payload)
    .then((response) => response.data)
}

export function cancelRun(runId: number): Promise<Run> {
  return http.post<Run>(`/runs/${runId}/cancel`).then((response) => response.data)
}

export function retryRun(runId: number): Promise<Run> {
  return http.post<Run>(`/runs/${runId}/retry`).then((response) => response.data)
}

/** 请求暂停：在当前节点结束后生效，等待审批时后端返回 409 */
export function pauseRun(runId: number): Promise<Run> {
  return http.post<Run>(`/runs/${runId}/pause`).then((response) => response.data)
}

/** 继续已暂停的运行；非 paused 时后端返回 409 */
export function resumeRun(runId: number): Promise<Run> {
  return http.post<Run>(`/runs/${runId}/resume`).then((response) => response.data)
}

/** 从指定 checkpoint 分叉出新运行，原 run 不受影响 */
export function forkRun(runId: number, payload: RunForkPayload): Promise<Run> {
  return http
    .post<Run>(`/runs/${runId}/fork`, payload)
    .then((response) => response.data)
}

/** 无待审批时后端返回 204，这里归一化为 null（不是错误） */
export function getPendingApproval(runId: number): Promise<PendingApproval | null> {
  return http.get<PendingApproval | null>(`/runs/${runId}/pending-approval`).then((response) => {
    if (response.status === 204 || !response.data) {
      return null
    }
    return response.data
  })
}

export function submitApproval(
  runId: number,
  payload: ApprovalPayload,
): Promise<ApprovalResult> {
  return http
    .post<ApprovalResult>(`/runs/${runId}/approval`, payload)
    .then((response) => response.data)
}

export function listRunStates(runId: number, limit = 20): Promise<RunState[]> {
  return http
    .get<RunState[]>(`/runs/${runId}/states`, { params: { limit } })
    .then((response) => response.data)
}

export function listPullRequests(runId: number): Promise<PullRequest[]> {
  return http
    .get<PullRequest[]>(`/runs/${runId}/pull-requests`)
    .then((response) => response.data)
}

export function listArtifacts(
  runId: number,
  params: ArtifactListParams = {},
): Promise<Page<Artifact>> {
  return http
    .get<Page<Artifact>>(`/runs/${runId}/artifacts`, { params })
    .then((response) => response.data)
}

export function getArtifact(artifactId: number): Promise<ArtifactDetail> {
  return http.get<ArtifactDetail>(`/artifacts/${artifactId}`).then((response) => response.data)
}

export function updateArtifact(artifactId: number, content: string): Promise<ArtifactDetail> {
  return http
    .patch<ArtifactDetail>(`/artifacts/${artifactId}`, { content })
    .then((response) => response.data)
}
