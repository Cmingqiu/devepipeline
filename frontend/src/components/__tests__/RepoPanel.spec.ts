import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Credential, RepoConfig } from '@/api/contexts'

vi.mock('@/api/contexts', () => ({
  getAgentDoc: vi.fn(),
  saveAgentDoc: vi.fn(),
  listAgentDocVersions: vi.fn(),
  listSkills: vi.fn(),
  uploadSkill: vi.fn(),
  getSkill: vi.fn(),
  getSkillFile: vi.fn(),
  deleteSkill: vi.fn(),
  listMcpServers: vi.fn(),
  saveMcpServers: vi.fn(),
  testMcpServers: vi.fn(),
  getRepo: vi.fn(),
  saveRepo: vi.fn(),
  testRepo: vi.fn(),
  listCredentials: vi.fn(),
  createCredential: vi.fn(),
  deleteCredential: vi.fn(),
}))

import * as contextsApi from '@/api/contexts'
import RepoPanel from '@/components/RepoPanel.vue'

const mockedApi = vi.mocked(contextsApi)

const SECRET = 'ghp_super_secret_value_123456'

const repoConfig: RepoConfig = {
  repo_url: 'https://github.com/acme/devpipeline.git',
  repo_provider: 'github',
  default_branch: 'main',
  credential_id: null,
  credential_hint: null,
}

const credential: Credential = {
  id: 7,
  project_id: 1,
  name: '部署令牌',
  kind: 'git_token',
  hint: '****1234',
  created_at: '2026-10-23T06:00:00.000Z',
}

const mountedWrappers: VueWrapper[] = []

function mountPanel(): VueWrapper {
  const wrapper = mount(RepoPanel, {
    props: { projectId: 1 },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

function findButton(wrapper: VueWrapper, text: string) {
  const button = wrapper.findAll('button').find((item) => item.text().includes(text))
  if (!button) {
    throw new Error(`按钮不存在：${text}`)
  }
  return button
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mockedApi.getRepo.mockResolvedValue(repoConfig)
  mockedApi.listCredentials.mockResolvedValue([])
})

afterEach(() => {
  while (mountedWrappers.length > 0) {
    mountedWrappers.pop()?.unmount()
  }
  document.body.innerHTML = ''
})

describe('RepoPanel 凭证', () => {
  it('提交请求体包含 secret，列表渲染只出现 hint，不出现明文', async () => {
    mockedApi.listCredentials.mockResolvedValueOnce([]).mockResolvedValue([credential])
    mockedApi.createCredential.mockResolvedValue(credential)

    const wrapper = mountPanel()
    await flushPromises()

    const nameInput = wrapper
      .findAll('input')
      .find((input) => input.attributes('placeholder')?.includes('部署令牌'))
    const secretInput = wrapper
      .findAll('input')
      .find((input) => input.attributes('placeholder')?.includes('只提交一次'))
    expect(nameInput).toBeTruthy()
    expect(secretInput).toBeTruthy()

    await nameInput!.setValue('部署令牌')
    await secretInput!.setValue(SECRET)
    await findButton(wrapper, '添加凭证').trigger('click')
    await flushPromises()

    expect(mockedApi.createCredential).toHaveBeenCalledWith(1, {
      name: '部署令牌',
      kind: 'git_token',
      secret: SECRET,
    })

    expect(wrapper.html()).not.toContain(SECRET)
    expect(wrapper.text()).toContain('部署令牌')
    expect(wrapper.text()).toContain('****1234')

    const secretAfter = wrapper
      .findAll('input')
      .find((input) => input.attributes('placeholder')?.includes('只提交一次'))
    expect((secretAfter!.element as HTMLInputElement).value).toBe('')
  })

  it('仓库地址不是 https:// 或 git@ 开头时本地拦截，不调用保存接口', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    const repoUrlInput = wrapper
      .findAll('input')
      .find((input) => input.attributes('placeholder')?.includes('github.com'))
    expect(repoUrlInput).toBeTruthy()

    await repoUrlInput!.setValue('ftp://example.com/repo.git')
    await findButton(wrapper, '保存仓库配置').trigger('click')
    await flushPromises()

    expect(mockedApi.saveRepo).not.toHaveBeenCalled()
  })
})
