import { ApiError } from '@/api/client'

/** 从任意异常里取给用户看的中文消息 */
export function getErrorMessage(error: unknown, fallback = '操作失败，请稍后重试'): string {
  if (error instanceof ApiError) {
    return error.message || fallback
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallback
}

export function getErrorStatus(error: unknown): number {
  return error instanceof ApiError ? error.status : 0
}

export function isConflict(error: unknown): boolean {
  return getErrorStatus(error) === 409
}
