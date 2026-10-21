import { AxiosError, type AxiosAdapter } from 'axios'
import { describe, expect, it } from 'vitest'

import { ApiError, createHttpClient } from '@/api/client'

function createAdapter(status: number, data: unknown): AxiosAdapter {
  return async (config) => {
    throw new AxiosError('Request failed with status code ' + status, 'ERR_BAD_REQUEST', config, {}, {
      data,
      status,
      statusText: 'Error',
      headers: {},
      config,
      request: {},
    })
  }
}

describe('api/client 错误归一化', () => {
  it('409 响应转换为 ApiError，保留 code/message/details/trace_id/status', async () => {
    const client = createHttpClient()
    client.defaults.adapter = createAdapter(409, {
      code: 'conflict',
      message: '项目下还有需求',
      details: { requirements: 3 },
      trace_id: 'trace-409',
    })

    const error = await client.get('/projects').then(
      () => null,
      (err: unknown) => err,
    )

    expect(error).toBeInstanceOf(ApiError)
    const apiError = error as ApiError
    expect(apiError.code).toBe('conflict')
    expect(apiError.message).toBe('项目下还有需求')
    expect(apiError.status).toBe(409)
    expect(apiError.details).toEqual({ requirements: 3 })
    expect(apiError.trace_id).toBe('trace-409')
  })

  it('响应体缺少 message 时退回可读的 HTTP 文案', async () => {
    const client = createHttpClient()
    client.defaults.adapter = createAdapter(500, { code: 'internal' })

    const error = (await client.get('/projects').catch((err: unknown) => err)) as ApiError

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('internal')
    expect(error.message).toBe('请求失败（HTTP 500）')
    expect(error.status).toBe(500)
  })

  it('网络错误给出中文提示，status 为 0', async () => {
    const client = createHttpClient()
    client.defaults.adapter = async () => {
      throw new AxiosError('Network Error', 'ERR_NETWORK')
    }

    const error = (await client.get('/projects').catch((err: unknown) => err)) as ApiError

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('network_error')
    expect(error.status).toBe(0)
    expect(error.message).toContain('网络异常')
  })
})
