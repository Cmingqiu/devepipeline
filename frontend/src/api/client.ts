import axios, { AxiosError, type AxiosInstance } from 'axios'

import type { ApiErrorBody } from './types'

const NETWORK_ERROR_MESSAGE = '网络异常，请确认后端服务已启动（http://127.0.0.1:8000）'
const TIMEOUT_ERROR_MESSAGE = '请求超时，请稍后重试'

/** 后端错误体归一化后的前端错误 */
export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly details: unknown
  readonly trace_id: string | null

  constructor(params: {
    code: string
    message: string
    status?: number
    details?: unknown
    trace_id?: string | null
  }) {
    super(params.message)
    this.name = 'ApiError'
    this.code = params.code
    this.status = params.status ?? 0
    this.details = params.details ?? null
    this.trace_id = params.trace_id ?? null
  }
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  return typeof value === 'object' && value !== null
}

/** 把 axios 错误/任意异常统一成 ApiError */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error
  }

  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<unknown>
    const response = axiosError.response

    if (!response) {
      const isTimeout = axiosError.code === 'ECONNABORTED' || axiosError.code === 'ETIMEDOUT'
      return new ApiError({
        code: isTimeout ? 'timeout' : 'network_error',
        message: isTimeout ? TIMEOUT_ERROR_MESSAGE : NETWORK_ERROR_MESSAGE,
        status: 0,
        details: null,
        trace_id: null,
      })
    }

    const body = response.data
    const hasBody = isApiErrorBody(body)
    const code = hasBody && typeof body.code === 'string' && body.code ? body.code : `http_${response.status}`
    const message =
      hasBody && typeof body.message === 'string' && body.message
        ? body.message
        : `请求失败（HTTP ${response.status}）`

    return new ApiError({
      code,
      message,
      status: response.status,
      details: hasBody ? body.details : null,
      trace_id: hasBody && typeof body.trace_id === 'string' ? body.trace_id : null,
    })
  }

  return new ApiError({
    code: 'unknown_error',
    message: error instanceof Error && error.message ? error.message : '未知错误',
    status: 0,
    details: null,
    trace_id: null,
  })
}

export function createHttpClient(): AxiosInstance {
  const instance = axios.create({
    baseURL: '/api/v1',
    timeout: 30000,
  })

  instance.interceptors.response.use(
    (response) => response,
    (error: unknown) => Promise.reject(toApiError(error)),
  )

  return instance
}

export const http: AxiosInstance = createHttpClient()
