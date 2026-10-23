import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ModelBinding, Provider } from '@/api/types'

vi.mock('@/api/providers', () => ({
  listProviders: vi.fn(),
  createProvider: vi.fn(),
  updateProvider: vi.fn(),
  deleteProvider: vi.fn(),
  listModelBindings: vi.fn(),
  saveModelBindings: vi.fn(),
}))

import { ApiError } from '@/api/client'
import * as providersApi from '@/api/providers'
import ModelPanel from '@/components/ModelPanel.vue'

const mockedApi = vi.mocked(providersApi)

const T1 = '2026-10-23T06:00:00.000Z'
const T2 = '2026-10-23T07:00:00.000Z'

const provider: Provider = {
  id: 7,
  name: 'deepseek',
  endpoint: 'https://api.deepseek.com/v1',
  model: 'deepseek-chat',
  enabled: true,
  credential_id: 3,
  configured: true,
  credential_hint: '****1234',
  extra: { temperature: 0.2 },
  created_at: T1,
  updated_at: T2,
}

const unconfiguredProvider: Provider = {
  id: 8,
  name: 'qwen',
  endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  model: 'qwen-plus',
  enabled: false,
  credential_id: null,
  configured: false,
  credential_hint: null,
  extra: {},
  created_at: T1,
  updated_at: T2,
}

function makeBinding(
  stage: ModelBinding['stage'],
  overrides: Partial<ModelBinding> = {},
): ModelBinding {
  return {
    stage,
    provider_id: null,
    provider_name: null,
    model: null,
    params: {},
    source: 'env',
    configured: false,
    override_model: null,
    override_params: {},
    ...overrides,
  }
}

const bindings: ModelBinding[] = [
  makeBinding('analysis', {
    provider_id: 7,
    provider_name: 'deepseek',
    source: 'project',
    configured: true,
  }),
  makeBinding('design', {
    source: 'global',
    provider_id: 8,
    provider_name: 'qwen',
    model: 'qwen-plus',
    configured: true,
  }),
  makeBinding('coding'),
  makeBinding('review'),
]

const mountedWrappers: VueWrapper[] = []

function mountPanel(): VueWrapper {
  const wrapper = mount(ModelPanel, {
    props: { projectId: 1 },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

function findButton(wrapper: VueWrapper, text: string) {
  const button = wrapper.findAll('button').find((item) => item.text().trim() === text)
  if (!button) {
    throw new Error(`按钮不存在：${text}`)
  }
  return button
}

function findInput(wrapper: VueWrapper, placeholder: string) {
  const input = wrapper.findAll('input').find((item) => item.attributes('placeholder') === placeholder)
  if (!input) {
    throw new Error(`输入框不存在：${placeholder}`)
  }
  return input
}

function findTextarea(wrapper: VueWrapper, placeholder: string) {
  const textarea = wrapper
    .findAll('textarea')
    .find((item) => (item.attributes('placeholder') ?? '').includes(placeholder))
  if (!textarea) {
    throw new Error(`文本框不存在：${placeholder}`)
  }
  return textarea
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mockedApi.listProviders.mockResolvedValue([provider, unconfiguredProvider])
  mockedApi.listModelBindings.mockResolvedValue(bindings)
})

afterEach(() => {
  while (mountedWrappers.length > 0) {
    mountedWrappers.pop()?.unmount()
  }
  document.body.innerHTML = ''
})

describe('ModelPanel 提供商', () => {
  it('渲染提供商列表、未配置密钥提示与四条阶段绑定', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('deepseek')
    expect(text).toContain('https://api.deepseek.com/v1')
    expect(text).toContain('已配置')
    expect(text).toContain('qwen')
    expect(text).toContain('未配置密钥')
    expect(text).toContain('需求分析')
    expect(text).toContain('系统设计')
    expect(text).toContain('编码')
    expect(text).toContain('PR 评审')
    expect(text).toContain('项目')
    expect(text).toContain('全局')
    expect(text).toContain('环境变量')
    expect(text).toContain('当前生效：qwen · qwen-plus')
  })

  it('新增提供商时提交完整 payload，extra 解析为对象', async () => {
    mockedApi.createProvider.mockResolvedValue({ ...provider, id: 9, name: 'moonshot' })

    const wrapper = mountPanel()
    await flushPromises()

    await findButton(wrapper, '新增提供商').trigger('click')
    await flushPromises()

    await findInput(wrapper, '例如 deepseek').setValue('moonshot')
    await findInput(wrapper, 'https://api.deepseek.com/v1').setValue('https://api.moonshot.cn/v1')
    await findInput(wrapper, 'deepseek-chat').setValue('moonshot-v1-8k')
    await findInput(wrapper, '可选：不填则读取环境变量').setValue('sk-test')
    await findTextarea(wrapper, '可选 JSON 对象').setValue('{"temperature":0.2}')

    await findButton(wrapper, '保存').trigger('click')
    await flushPromises()

    expect(mockedApi.createProvider).toHaveBeenCalledWith({
      name: 'moonshot',
      endpoint: 'https://api.moonshot.cn/v1',
      model: 'moonshot-v1-8k',
      enabled: true,
      api_key: 'sk-test',
      extra: { temperature: 0.2 },
    })
  })

  it('extra 不是合法 JSON 时本地拦截，不调用创建接口', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    await findButton(wrapper, '新增提供商').trigger('click')
    await flushPromises()

    await findInput(wrapper, '例如 deepseek').setValue('moonshot')
    await findInput(wrapper, 'https://api.deepseek.com/v1').setValue('https://api.moonshot.cn/v1')
    await findInput(wrapper, 'deepseek-chat').setValue('moonshot-v1-8k')
    await findTextarea(wrapper, '可选 JSON 对象').setValue('not-json')

    await findButton(wrapper, '保存').trigger('click')
    await flushPromises()

    expect(mockedApi.createProvider).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('extra 不是合法的 JSON')
  })

  it('编辑提供商时 api_key 留空表示不修改，不提交该字段', async () => {
    mockedApi.updateProvider.mockResolvedValue({ ...provider, name: 'deepseek-v2' })

    const wrapper = mountPanel()
    await flushPromises()

    await findButton(wrapper, '编辑').trigger('click')
    await flushPromises()

    const nameInput = findInput(wrapper, '例如 deepseek')
    expect((nameInput.element as HTMLInputElement).value).toBe('deepseek')
    await nameInput.setValue('deepseek-v2')

    await findButton(wrapper, '保存').trigger('click')
    await flushPromises()

    expect(mockedApi.updateProvider).toHaveBeenCalledWith(7, {
      name: 'deepseek-v2',
      endpoint: provider.endpoint,
      model: provider.model,
      enabled: true,
      extra: { temperature: 0.2 },
    })
  })

  it('删除被绑定引用的提供商时展示后端 409 错误', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    mockedApi.deleteProvider.mockRejectedValue(
      new ApiError({
        code: 'provider_in_use',
        message: '提供商仍被阶段绑定引用，无法删除',
        status: 409,
      }),
    )

    const wrapper = mountPanel()
    await flushPromises()

    await findButton(wrapper, '删除').trigger('click')
    await flushPromises()

    expect(mockedApi.deleteProvider).toHaveBeenCalledWith(7)
    expect(wrapper.text()).toContain('提供商仍被阶段绑定引用，无法删除')
  })
})

describe('ModelPanel 阶段绑定', () => {
  it('保存时提交完整 4 条，provider 为 null 的条目回退全局', async () => {
    mockedApi.saveModelBindings.mockResolvedValue(bindings)

    const wrapper = mountPanel()
    await flushPromises()

    const modelInputs = wrapper.findAll('input[placeholder="模型覆盖（可空）"]')
    expect(modelInputs).toHaveLength(4)
    await modelInputs[0].setValue('deepseek-reasoner')

    const paramInputs = wrapper.findAll('textarea')
    await paramInputs[0].setValue('{"temperature":0.2}')

    await findButton(wrapper, '保存模型绑定').trigger('click')
    await flushPromises()

    expect(mockedApi.saveModelBindings).toHaveBeenCalledWith({
      project_id: 1,
      scope: 'project',
      items: [
        {
          stage: 'analysis',
          provider_id: 7,
          model: 'deepseek-reasoner',
          params: { temperature: 0.2 },
        },
        { stage: 'design', provider_id: null },
        { stage: 'coding', provider_id: null },
        { stage: 'review', provider_id: null },
      ],
    })
  })

  it('绑定 params 不是合法 JSON 时本地拦截，不调用保存接口', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    const paramInputs = wrapper.findAll('textarea')
    await paramInputs[0].setValue('{bad json}')

    await findButton(wrapper, '保存模型绑定').trigger('click')
    await flushPromises()

    expect(mockedApi.saveModelBindings).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('需求分析参数 不是合法的 JSON')
  })
})
