import { http } from './client'

export type RepoProvider = 'github' | 'gitlab'

export type CredentialKind = 'git_token' | 'llm_api_key' | 'mcp_env'

export type McpTransport = 'stdio' | 'streamable_http'

export type McpTestStatus = 'ok' | 'failed'

/** GET /projects/{id}/agents-md 的返回；未配置时接口 204，前端归一化为 null */
export interface AgentDoc {
  id: number
  project_id: number
  version: number
  is_active: boolean
  created_at: string
  content: string
}

/** 版本列表项：接口不返回正文 */
export interface AgentDocVersion {
  id: number
  project_id: number
  version: number
  is_active: boolean
  created_at: string
}

export interface Skill {
  id: number
  project_id: number
  name: string
  description: string | null
  entry_path: string
  enabled: boolean
  file_count: number
  created_at: string
  updated_at: string
}

export interface SkillFile {
  path: string
  size_bytes: number
  sha256: string
  is_text: boolean
}

export interface SkillDetail extends Skill {
  files: SkillFile[]
}

/** 单文件内容；二进制文件接口返回 404 */
export interface SkillFileContent extends SkillFile {
  content: string
}

export interface McpServer {
  id: number
  project_id: number
  name: string
  transport: McpTransport
  /** 敏感值后端已掩码（****1234），保存时原样回传 */
  config: Record<string, unknown>
  enabled: boolean
  last_test_status: McpTestStatus | null
  last_test_at: string | null
  last_test_message: string | null
}

export interface McpServerInput {
  name: string
  transport: McpTransport
  config: Record<string, unknown>
  enabled: boolean
}

export interface McpTestResult {
  name: string
  ok: boolean
  /** 后端目前返回工具名列表，这里放宽以兼容对象形式 */
  tools: unknown[]
  error: string | null
}

export interface RepoConfig {
  repo_url: string | null
  repo_provider: RepoProvider | null
  default_branch: string
  credential_id: number | null
  credential_hint: string | null
}

export interface RepoUpdatePayload {
  /** 传 null 表示清空仓库地址 */
  repo_url?: string | null
  repo_provider?: RepoProvider | null
  default_branch: string
  credential_id?: number | null
}

export interface RepoTestResult {
  ok: boolean
  message: string
}

export interface Credential {
  id: number
  project_id: number
  name: string
  kind: CredentialKind
  /** 只返回掩码，永不含明文 */
  hint: string
  created_at: string
}

export interface CredentialCreatePayload {
  name: string
  kind: CredentialKind
  secret: string
}

export function getAgentDoc(projectId: number): Promise<AgentDoc | null> {
  return http.get<AgentDoc | null>(`/projects/${projectId}/agents-md`).then((response) => {
    if (response.status === 204 || !response.data) {
      return null
    }
    return response.data
  })
}

export function saveAgentDoc(projectId: number, content: string): Promise<AgentDoc> {
  return http
    .put<AgentDoc>(`/projects/${projectId}/agents-md`, { content })
    .then((response) => response.data)
}

export function listAgentDocVersions(projectId: number): Promise<AgentDocVersion[]> {
  return http
    .get<AgentDocVersion[]>(`/projects/${projectId}/agents-md/versions`)
    .then((response) => response.data)
}

export function listSkills(projectId: number): Promise<Skill[]> {
  return http.get<Skill[]>(`/projects/${projectId}/skills`).then((response) => response.data)
}

export function uploadSkill(projectId: number, file: File): Promise<SkillDetail> {
  const form = new FormData()
  form.append('file', file)

  return http
    .post<SkillDetail>(`/projects/${projectId}/skills`, form)
    .then((response) => response.data)
}

export function getSkill(projectId: number, skillId: number): Promise<SkillDetail> {
  return http
    .get<SkillDetail>(`/projects/${projectId}/skills/${skillId}`)
    .then((response) => response.data)
}

export function getSkillFile(
  projectId: number,
  skillId: number,
  path: string,
): Promise<SkillFileContent> {
  // 路径按段编码，保留 zip 内的目录分隔符
  const encodedPath = path.split('/').map((segment) => encodeURIComponent(segment)).join('/')

  return http
    .get<SkillFileContent>(`/projects/${projectId}/skills/${skillId}/files/${encodedPath}`)
    .then((response) => response.data)
}

export function deleteSkill(projectId: number, skillId: number): Promise<void> {
  return http.delete<void>(`/projects/${projectId}/skills/${skillId}`).then(() => undefined)
}

export function listMcpServers(projectId: number): Promise<McpServer[]> {
  return http.get<McpServer[]>(`/projects/${projectId}/mcp`).then((response) => response.data)
}

export function saveMcpServers(
  projectId: number,
  servers: McpServerInput[],
): Promise<McpServer[]> {
  return http
    .put<McpServer[]>(`/projects/${projectId}/mcp`, { servers })
    .then((response) => response.data)
}

/** 不传 servers 时测试已保存的配置；传了则测试请求里的配置 */
export function testMcpServers(
  projectId: number,
  servers?: McpServerInput[],
): Promise<McpTestResult[]> {
  return http
    .post<McpTestResult[]>(`/projects/${projectId}/mcp/test`, servers ? { servers } : undefined)
    .then((response) => response.data)
}

export function deleteMcpServer(projectId: number, name: string): Promise<void> {
  return http
    .delete<void>(`/projects/${projectId}/mcp/${encodeURIComponent(name)}`)
    .then(() => undefined)
}

export function getRepo(projectId: number): Promise<RepoConfig> {
  return http.get<RepoConfig>(`/projects/${projectId}/repo`).then((response) => response.data)
}

export function saveRepo(projectId: number, payload: RepoUpdatePayload): Promise<RepoConfig> {
  return http
    .put<RepoConfig>(`/projects/${projectId}/repo`, payload)
    .then((response) => response.data)
}

export function testRepo(projectId: number): Promise<RepoTestResult> {
  return http
    .post<RepoTestResult>(`/projects/${projectId}/repo/test`)
    .then((response) => response.data)
}

export function listCredentials(projectId: number): Promise<Credential[]> {
  return http
    .get<Credential[]>(`/projects/${projectId}/credentials`)
    .then((response) => response.data)
}

export function createCredential(
  projectId: number,
  payload: CredentialCreatePayload,
): Promise<Credential> {
  return http
    .post<Credential>(`/projects/${projectId}/credentials`, payload)
    .then((response) => response.data)
}

export function deleteCredential(projectId: number, credentialId: number): Promise<void> {
  return http
    .delete<void>(`/projects/${projectId}/credentials/${credentialId}`)
    .then(() => undefined)
}
