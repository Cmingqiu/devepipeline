import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { AgentDoc, AgentDocVersion } from '@/api/contexts'

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
import { useContextStore } from '@/stores/context'

const mockedApi = vi.mocked(contextsApi)

const T1 = '2026-10-23T06:00:00.000Z'
const T2 = '2026-10-23T07:00:00.000Z'

function makeDoc(overrides: Partial<AgentDoc> = {}): AgentDoc {
  return {
    id: 1,
    project_id: 9,
    version: 1,
    is_active: true,
    created_at: T1,
    content: '# v1 约定',
    ...overrides,
  }
}

function makeVersion(overrides: Partial<AgentDocVersion> = {}): AgentDocVersion {
  return {
    id: 1,
    project_id: 9,
    version: 1,
    is_active: true,
    created_at: T1,
    ...overrides,
  }
}

describe('stores/context AGENTS.md', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('GET 204（接口归一化为 null）按「未配置」处理', async () => {
    mockedApi.getAgentDoc.mockResolvedValue(null)

    const store = useContextStore()
    const doc = await store.fetchAgentDoc(9)

    expect(doc).toBeNull()
    expect(store.agentDoc).toBeNull()
    expect(store.agentConfigured).toBe(false)
    expect(store.agentDocLoading).toBe(false)
  })

  it('保存后版本号与正文更新，并刷新版本列表', async () => {
    mockedApi.getAgentDoc.mockResolvedValue(makeDoc())
    mockedApi.saveAgentDoc.mockResolvedValue(
      makeDoc({ id: 2, version: 2, created_at: T2, content: '# v2 约定' }),
    )
    mockedApi.listAgentDocVersions
      .mockResolvedValueOnce([makeVersion()])
      .mockResolvedValue([
        makeVersion({ id: 2, version: 2, created_at: T2 }),
        makeVersion(),
      ])

    const store = useContextStore()
    await store.fetchAgentDoc(9)
    await store.fetchAgentVersions(9)
    expect(store.agentConfigured).toBe(true)
    expect(store.agentVersions).toHaveLength(1)

    const saved = await store.saveAgentDoc(9, '# v2 约定')

    expect(mockedApi.saveAgentDoc).toHaveBeenCalledWith(9, '# v2 约定')
    expect(saved.version).toBe(2)
    expect(store.agentDoc?.version).toBe(2)
    expect(store.agentDoc?.content).toBe('# v2 约定')
    expect(store.agentConfigured).toBe(true)
    expect(store.agentVersions.map((version) => version.version)).toEqual([2, 1])
    expect(store.agentSaving).toBe(false)
  })

  it('保存失败时不覆盖已有正文与版本', async () => {
    mockedApi.getAgentDoc.mockResolvedValue(makeDoc())
    mockedApi.listAgentDocVersions.mockResolvedValue([makeVersion()])
    mockedApi.saveAgentDoc.mockRejectedValue(new Error('网络异常'))

    const store = useContextStore()
    await store.fetchAgentDoc(9)
    await store.fetchAgentVersions(9)

    await expect(store.saveAgentDoc(9, '# v2 约定')).rejects.toThrow('网络异常')

    expect(store.agentDoc?.version).toBe(1)
    expect(store.agentDoc?.content).toBe('# v1 约定')
    expect(store.agentVersions).toHaveLength(1)
    expect(store.agentSaving).toBe(false)
  })
})
