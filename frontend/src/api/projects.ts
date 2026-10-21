import { http } from './client'
import type { Page, Project, ProjectStatus } from './types'

export interface ProjectListParams {
  page?: number
  page_size?: number
  status?: ProjectStatus
}

export interface ProjectCreatePayload {
  name: string
  slug?: string
  description?: string | null
}

export interface ProjectUpdatePayload {
  name?: string
  description?: string | null
  status?: ProjectStatus
}

export function listProjects(params: ProjectListParams = {}): Promise<Page<Project>> {
  return http.get<Page<Project>>('/projects', { params }).then((response) => response.data)
}

export function createProject(payload: ProjectCreatePayload): Promise<Project> {
  return http.post<Project>('/projects', payload).then((response) => response.data)
}

export function getProject(projectId: number): Promise<Project> {
  return http.get<Project>(`/projects/${projectId}`).then((response) => response.data)
}

export function updateProject(projectId: number, payload: ProjectUpdatePayload): Promise<Project> {
  return http.patch<Project>(`/projects/${projectId}`, payload).then((response) => response.data)
}

export function deleteProject(projectId: number): Promise<void> {
  return http.delete<void>(`/projects/${projectId}`).then(() => undefined)
}
