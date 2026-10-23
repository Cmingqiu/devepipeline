import { flushPromises, mount, type DOMWrapper, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import type { Run, RunState } from '@/api/types'

vi.mock('@/api/runs', () => ({
  listRuns: vi.fn(),
  getRun: vi.fn(),
  createRun: vi.fn(),
  cancelRun: vi.fn(),
  retryRun: vi.fn(),
  pauseRun: vi.fn(),
  resumeRun: vi.fn(),
  forkRun: vi.fn(),
  getPendingApproval: vi.fn(),
  submitApproval: vi.fn(),
  listRunStates: vi.fn(),
  listArtifacts: vi.fn(),
  getArtifact: vi.fn(),
  updateArtifact: vi.fn(),
}))

import * as runsApi from '@/api/runs'
import RunStateHistory from '@/components/RunStateHistory.vue'

const mockedApi = vi.mocked(runsApi)

const T0 = '2026-10-23T06:00:00.000Z'

const state: RunState = {
  checkpoint_id: 'checkpoint-1',
  stage: 'design',
  next: ['gate_design'],
  created_at: T0,
  has_interrupt: false,
  error: null,
}

function makeRun(overrides: Partial<Run> = {}): Run {
  return {
    id: 9,
    project_id: 1,
    requirement_id: 3,
    requirement_version_id: 4,
    thread_id: 'thread-forked',
    status: 'queued',
    current_stage: null,
    review_round: 0,
    max_review_rounds: 2,
    error_code: null,
    error_message: null,
    started_at: null,
    finished_at: null,
    created_at: T0,
    updated_at: T0,
    prompt_tokens: 0,
    completion_tokens: 0,
    ...overrides,
  }
}

const mountedWrappers: VueWrapper[] = []

function createTestRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/runs/:runId',
        name: 'run-detail',
        component: { template: '<div />' },
      },
    ],
  })
}

async function mountHistory(runId = 7): Promise<{ wrapper: VueWrapper; router: Router }> {
  const router = createTestRouter()
  await router.push(`/runs/${runId}`)
  await router.isReady()

  const wrapper = mount(RunStateHistory, {
    props: { states: [state], runId },
    global: { plugins: [ElementPlus, router] },
    attachTo: document.body,
  })
  mountedWrappers.push(wrapper)
  return { wrapper, router }
}

function findButton(wrapper: VueWrapper, text: string): DOMWrapper<Element> {
  const button = wrapper.findAll('button').find((item) => item.text().includes(text))
  if (!button) {
    throw new Error(`按钮不存在：${text}`)
  }
  return button
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

afterEach(() => {
  while (mountedWrappers.length > 0) {
    mountedWrappers.pop()?.unmount()
  }
  document.body.innerHTML = ''
})

describe('RunStateHistory 从 checkpoint fork', () => {
  it('默认选中该 checkpoint 的阶段，提交后跳到新 run', async () => {
    mockedApi.forkRun.mockResolvedValue(makeRun())

    const { wrapper, router } = await mountHistory()
    await findButton(wrapper, '从此处 fork').trigger('click')
    await flushPromises()

    const dialogText = wrapper.text()
    expect(dialogText).toContain('从 checkpoint 分叉')
    expect(dialogText).toContain('checkpoint checkpoi')
    expect(dialogText).toContain('需求分析')
    expect(dialogText).toContain('系统设计')
    expect(dialogText).toContain('编码')
    expect(dialogText).toContain('PR 评审')

    await findButton(wrapper, '创建新运行').trigger('click')
    await flushPromises()

    expect(mockedApi.forkRun).toHaveBeenCalledWith(7, {
      checkpoint_id: 'checkpoint-1',
      from_stage: 'design',
    })
    expect(router.currentRoute.value.path).toBe('/runs/9')
  })

  it('fork 失败时停留在当前 run，不跳转', async () => {
    mockedApi.forkRun.mockRejectedValue(new Error('fork 接口不可用'))

    const { wrapper, router } = await mountHistory()
    await findButton(wrapper, '从此处 fork').trigger('click')
    await flushPromises()
    await findButton(wrapper, '创建新运行').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/runs/7')
  })
})
