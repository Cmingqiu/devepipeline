import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { RequirementDetail, RequirementVersion } from '@/api/types'

vi.mock('@/api/requirements', () => ({
  listRequirements: vi.fn(),
  createRequirement: vi.fn(),
  getRequirement: vi.fn(),
  updateRequirement: vi.fn(),
  deleteRequirement: vi.fn(),
  listVersions: vi.fn(),
  createVersion: vi.fn(),
  uploadVersion: vi.fn(),
  getVersion: vi.fn(),
}))

import * as requirementsApi from '@/api/requirements'
import { useRequirementStore } from '@/stores/requirement'

const mockedApi = vi.mocked(requirementsApi)

const T1 = '2026-10-21T06:00:00.000Z'
const T2 = '2026-10-21T07:00:00.000Z'

function makeDetail(overrides: Partial<RequirementDetail> = {}): RequirementDetail {
  return {
    id: 1,
    project_id: 9,
    title: '登录需求',
    status: 'draft',
    current_version_no: 1,
    latest_run_id: null,
    created_at: T1,
    updated_at: T1,
    content: '# v1 正文',
    version_no: 1,
    ...overrides,
  }
}

function makeVersion(overrides: Partial<RequirementVersion> = {}): RequirementVersion {
  return {
    id: 1,
    version_no: 1,
    source: 'editor',
    note: null,
    created_by: 'local',
    created_at: T1,
    ...overrides,
  }
}

describe('stores/requirement 版本保存', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('保存新版本后 current_version_no 与版本列表都更新', async () => {
    mockedApi.getRequirement.mockResolvedValue(makeDetail())
    mockedApi.createVersion.mockResolvedValue({
      ...makeVersion({ id: 2, version_no: 2, note: '补充登录流程', created_at: T2 }),
      content: '# v2 正文',
    })
    mockedApi.listVersions.mockResolvedValue({
      items: [
        makeVersion({ id: 2, version_no: 2, note: '补充登录流程', created_at: T2 }),
        makeVersion(),
      ],
      total: 2,
      page: 1,
      page_size: 100,
    })

    const store = useRequirementStore()
    await store.fetchDetail(1)
    expect(store.detail?.current_version_no).toBe(1)

    const created = await store.saveVersion(1, { content: '# v2 正文', note: '补充登录流程' })

    expect(mockedApi.createVersion).toHaveBeenCalledWith(1, {
      content: '# v2 正文',
      note: '补充登录流程',
    })
    expect(created.version_no).toBe(2)
    expect(store.detail?.current_version_no).toBe(2)
    expect(store.detail?.version_no).toBe(2)
    expect(store.detail?.content).toBe('# v2 正文')
    expect(store.versions.map((version) => version.version_no)).toEqual([2, 1])
    expect(store.versionsTotal).toBe(2)
  })

  it('保存失败时保留原来的当前版本，不产生乐观更新', async () => {
    mockedApi.getRequirement.mockResolvedValue(makeDetail())
    mockedApi.listVersions.mockResolvedValue({
      items: [makeVersion()],
      total: 1,
      page: 1,
      page_size: 100,
    })
    mockedApi.createVersion.mockRejectedValue(new Error('网络异常'))

    const store = useRequirementStore()
    await store.fetchDetail(1)
    await store.fetchVersions(1)

    await expect(store.saveVersion(1, { content: '# v2 正文' })).rejects.toThrow('网络异常')

    expect(store.detail?.current_version_no).toBe(1)
    expect(store.detail?.content).toBe('# v1 正文')
    expect(store.versions).toHaveLength(1)
  })
})
