import { http } from './client'
import type {
  Page,
  Requirement,
  RequirementDetail,
  RequirementVersion,
  RequirementVersionDetail,
} from './types'

export interface RequirementListParams {
  page?: number
  page_size?: number
  q?: string
}

export interface RequirementCreatePayload {
  title: string
  content: string
  note?: string
}

export interface RequirementUpdatePayload {
  title?: string
}

export interface VersionCreatePayload {
  content: string
  note?: string
}

export function listRequirements(
  projectId: number,
  params: RequirementListParams = {},
): Promise<Page<Requirement>> {
  return http
    .get<Page<Requirement>>(`/projects/${projectId}/requirements`, { params })
    .then((response) => response.data)
}

export function createRequirement(
  projectId: number,
  payload: RequirementCreatePayload,
): Promise<RequirementDetail> {
  return http
    .post<RequirementDetail>(`/projects/${projectId}/requirements`, payload)
    .then((response) => response.data)
}

export function getRequirement(requirementId: number): Promise<RequirementDetail> {
  return http
    .get<RequirementDetail>(`/requirements/${requirementId}`)
    .then((response) => response.data)
}

export function updateRequirement(
  requirementId: number,
  payload: RequirementUpdatePayload,
): Promise<Requirement> {
  return http
    .patch<Requirement>(`/requirements/${requirementId}`, payload)
    .then((response) => response.data)
}

export function deleteRequirement(requirementId: number): Promise<void> {
  return http.delete<void>(`/requirements/${requirementId}`).then(() => undefined)
}

export function listVersions(
  requirementId: number,
  params: { page?: number; page_size?: number } = {},
): Promise<Page<RequirementVersion>> {
  return http
    .get<Page<RequirementVersion>>(`/requirements/${requirementId}/versions`, { params })
    .then((response) => response.data)
}

export function createVersion(
  requirementId: number,
  payload: VersionCreatePayload,
): Promise<RequirementVersionDetail> {
  return http
    .post<RequirementVersionDetail>(`/requirements/${requirementId}/versions`, payload)
    .then((response) => response.data)
}

export function uploadVersion(
  requirementId: number,
  file: File,
  note?: string,
): Promise<RequirementVersionDetail> {
  const form = new FormData()
  form.append('file', file)
  if (note) {
    form.append('note', note)
  }

  return http
    .post<RequirementVersionDetail>(`/requirements/${requirementId}/versions/upload`, form)
    .then((response) => response.data)
}

export function getVersion(
  requirementId: number,
  versionNo: number,
): Promise<RequirementVersionDetail> {
  return http
    .get<RequirementVersionDetail>(`/requirements/${requirementId}/versions/${versionNo}`)
    .then((response) => response.data)
}
