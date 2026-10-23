import { http } from './client'
import type {
  ModelBinding,
  ModelBindingSavePayload,
  Provider,
  ProviderCreatePayload,
  ProviderUpdatePayload,
} from './types'

export function listProviders(): Promise<Provider[]> {
  return http.get<Provider[]>('/providers').then((response) => response.data)
}

export function createProvider(payload: ProviderCreatePayload): Promise<Provider> {
  return http.post<Provider>('/providers', payload).then((response) => response.data)
}

export function updateProvider(id: number, payload: ProviderUpdatePayload): Promise<Provider> {
  return http.patch<Provider>(`/providers/${id}`, payload).then((response) => response.data)
}

/** 被阶段绑定引用时后端返回 409，错误消息由调用方展示 */
export function deleteProvider(id: number): Promise<void> {
  return http.delete<void>(`/providers/${id}`).then(() => undefined)
}

export function listModelBindings(projectId: number): Promise<ModelBinding[]> {
  return http
    .get<ModelBinding[]>('/model-bindings', { params: { project_id: projectId } })
    .then((response) => response.data)
}

/** items 是该 scope 的完整集合；未出现 = 删除绑定 */
export function saveModelBindings(payload: ModelBindingSavePayload): Promise<ModelBinding[]> {
  return http.put<ModelBinding[]>('/model-bindings', payload).then((response) => response.data)
}
