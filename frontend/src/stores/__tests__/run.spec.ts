import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import type { ApprovalResult, PendingApproval, Run } from '@/api/types'

vi.mock('@/api/runs', () => ({
  listRuns: vi.fn(),
  getRun: vi.fn(),
  createRun: vi.fn(),
  cancelRun: vi.fn(),
  retryRun: vi.fn(),
  getPendingApproval: vi.fn(),
  submitApproval: vi.fn(),
  listRunStates: vi.fn(),
  listArtifacts: vi.fn(),
  getArtifact: vi.fn(),
  updateArtifact: vi.fn(),
}))

import * as runsApi from '@/api/runs'
import { useRunStore } from '@/stores/run'

const mockedApi = vi.mocked(runsApi)

const T0 = '2026-10-21T06:00:00.000Z'
const T1 = '2026-10-21T06:10:00.000Z'

function makeRun(overrides: Partial<Run> = {}): Run {
  return {
    id: 1,
    project_id: 9,
    requirement_id: 5,
    requirement_version_id: 2,
    thread_id: 'thread-1234567890',
    status: 'waiting_approval',
    current_stage: 'design',
    review_round: 0,
    max_review_rounds: 2,
    error_code: null,
    error_message: null,
    started_at: T0,
    finished_at: null,
    created_at: T0,
    updated_at: T0,
    prompt_tokens: 100,
    completion_tokens: 200,
    ...overrides,
  }
}

function makePending(overrides: Partial<PendingApproval> = {}): PendingApproval {
  return {
    stage: 'design',
    label: '系统设计审批',
    attempt: 1,
    summary: '设计文档已生成',
    preview: '# 设计正文',
    artifact_id: 10,
    checkpoint_id: 'checkpoint-abcdef123456',
    ...overrides,
  }
}

function makeApprovalResult(overrides: Partial<ApprovalResult> = {}): ApprovalResult {
  return {
    id: 1,
    run_id: 1,
    stage: 'design',
    artifact_id: 10,
    decision: 'approved',
    feedback: null,
    decided_by: 'local',
    decided_at: T1,
    ...overrides,
  }
}

describe('stores/run 审批与轮询', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    vi.clearAllMocks()

    mockedApi.listRunStates.mockResolvedValue([])
    mockedApi.listArtifacts.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 100,
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('审批成功后刷新 detail 且停止轮询', async () => {
    const pending = makePending()
    mockedApi.getRun.mockResolvedValue({
      ...makeRun(),
      pending_approval: pending,
    })
    mockedApi.getPendingApproval.mockResolvedValue(pending)
    mockedApi.submitApproval.mockResolvedValue(makeApprovalResult())

    const store = useRunStore()
    await store.fetchDetail(1)
    expect(store.pendingApproval).toEqual(pending)

    store.startPolling(1)
    expect(store.polling).toBe(true)

    await vi.advanceTimersByTimeAsync(3000)
    expect(mockedApi.getRun).toHaveBeenCalledTimes(2)

    mockedApi.getRun.mockResolvedValue(
      makeRun({ status: 'succeeded', current_stage: null, finished_at: T1 }),
    )
    mockedApi.getPendingApproval.mockResolvedValue(null)

    await store.submitApproval(1, { decision: 'approved' })

    expect(mockedApi.submitApproval).toHaveBeenCalledWith(1, { decision: 'approved' })
    expect(store.detail?.status).toBe('succeeded')
    expect(store.pendingApproval).toBeNull()
    expect(store.polling).toBe(false)
    expect(mockedApi.getRun).toHaveBeenCalledTimes(3)

    await vi.advanceTimersByTimeAsync(6000)
    expect(mockedApi.getRun).toHaveBeenCalledTimes(3)
  })

  it('审批 409 时向上抛出，且不清空当前待审批', async () => {
    const pending = makePending()
    mockedApi.getRun.mockResolvedValue({
      ...makeRun(),
      pending_approval: pending,
    })
    mockedApi.getPendingApproval.mockResolvedValue(pending)
    mockedApi.submitApproval.mockRejectedValue(
      new ApiError({ code: 'conflict', message: '当前没有待审批项', status: 409 }),
    )

    const store = useRunStore()
    await store.fetchDetail(1)

    await expect(store.submitApproval(1, { decision: 'approved' })).rejects.toMatchObject({
      code: 'conflict',
      status: 409,
    })

    expect(store.pendingApproval).toEqual(pending)
    expect(store.approving).toBe(false)
    expect(mockedApi.getRun).toHaveBeenCalledTimes(1)
  })

  it('审批 422 时向上抛出，pending 保持不变', async () => {
    const pending = makePending()
    mockedApi.getRun.mockResolvedValue({
      ...makeRun(),
      pending_approval: pending,
    })
    mockedApi.getPendingApproval.mockResolvedValue(pending)
    mockedApi.submitApproval.mockRejectedValue(
      new ApiError({
        code: 'validation_error',
        message: '驳回必须填写意见',
        status: 422,
      }),
    )

    const store = useRunStore()
    await store.fetchDetail(1)

    await expect(
      store.submitApproval(1, { decision: 'rejected' }),
    ).rejects.toMatchObject({ code: 'validation_error', status: 422 })

    expect(store.pendingApproval).toEqual(pending)
    expect(store.polling).toBe(false)
  })
})
