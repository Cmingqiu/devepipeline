import { flushPromises, mount, type DOMWrapper, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PendingApproval } from '@/api/types'

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
import ApprovalPanel from '@/components/ApprovalPanel.vue'

const mockedApi = vi.mocked(runsApi)

const pending: PendingApproval = {
  stage: 'design',
  label: '系统设计审批',
  attempt: 1,
  summary: '设计文档已生成，等待确认',
  preview: '# 设计正文\n\n这里是预览内容',
  artifact_id: 10,
  checkpoint_id: 'checkpoint-abcdef123456',
}

const mountedWrappers: VueWrapper[] = []

function mountPanel(): ReturnType<typeof mount> {
  const wrapper = mount(ApprovalPanel, {
    props: { runId: 1, pending },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

function findButton(wrapper: ReturnType<typeof mount>, text: string): DOMWrapper<Element> {
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

afterAll(async () => {
  // MdPreview 挂载时排的图片缩放 debounce（200ms）不会被卸载清理，
  // 等它落地再销毁 jsdom，避免环境销毁后报 "document is not defined"
  await new Promise((resolve) => setTimeout(resolve, 300))
})

describe('ApprovalPanel 审批表单校验', () => {
  it('驳回未填 feedback 时不调用审批接口', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    await findButton(wrapper, '驳回').trigger('click')
    await flushPromises()

    await findButton(wrapper, '确认驳回').trigger('click')
    await flushPromises()

    expect(mockedApi.submitApproval).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('驳回必须填写意见')
  })

  it('改后通过但正文为空时不调用审批接口', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    await findButton(wrapper, '改后通过').trigger('click')
    await flushPromises()

    const textarea = wrapper.find('textarea')
    expect(textarea.exists()).toBe(true)
    await textarea.setValue('   ')

    await findButton(wrapper, '确认修改并提交').trigger('click')
    await flushPromises()

    expect(mockedApi.submitApproval).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('修改后的正文不能为空')
  })

  it('通过时调用审批接口并 emit decided', async () => {
    mockedApi.submitApproval.mockResolvedValue({
      id: 1,
      run_id: 1,
      stage: 'design',
      artifact_id: 10,
      decision: 'approved',
      feedback: null,
      decided_by: 'local',
      decided_at: '2026-10-21T06:10:00.000Z',
    })
    mockedApi.getRun.mockResolvedValue({
      id: 1,
      project_id: 9,
      requirement_id: 5,
      requirement_version_id: 2,
      thread_id: 'thread-1234567890',
      status: 'running',
      current_stage: 'coding',
      review_round: 0,
      max_review_rounds: 2,
      error_code: null,
      error_message: null,
      started_at: '2026-10-21T06:00:00.000Z',
      finished_at: null,
      created_at: '2026-10-21T06:00:00.000Z',
      updated_at: '2026-10-21T06:00:00.000Z',
      prompt_tokens: 0,
      completion_tokens: 0,
      pending_approval: null,
    })
    mockedApi.getPendingApproval.mockResolvedValue(null)
    mockedApi.listRunStates.mockResolvedValue([])

    const wrapper = mountPanel()
    await flushPromises()

    await findButton(wrapper, '通过').trigger('click')
    await flushPromises()

    expect(mockedApi.submitApproval).toHaveBeenCalledWith(1, { decision: 'approved' })
    expect(wrapper.emitted('decided')).toHaveLength(1)
  })
})
