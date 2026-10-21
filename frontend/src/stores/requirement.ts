import { computed, ref } from 'vue'

import { defineStore } from 'pinia'

import * as requirementsApi from '@/api/requirements'
import type {
  RequirementCreatePayload,
  RequirementListParams,
  VersionCreatePayload,
} from '@/api/requirements'
import type { Requirement, RequirementDetail, RequirementVersion, RequirementVersionDetail } from '@/api/types'

const VERSION_PAGE_SIZE = 100

export const useRequirementStore = defineStore('requirement', () => {
  const items = ref<Requirement[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const query = ref('')
  const loading = ref(false)
  const submitting = ref(false)
  const error = ref<string | null>(null)

  const detail = ref<RequirementDetail | null>(null)
  const detailLoading = ref(false)

  const versions = ref<RequirementVersion[]>([])
  const versionsTotal = ref(0)
  const versionsLoading = ref(false)

  const saving = ref(false)
  const uploading = ref(false)

  const isEmpty = computed(() => !loading.value && items.value.length === 0)

  async function fetchList(
    projectId: number,
    options: RequirementListParams & { resetPage?: boolean } = {},
  ): Promise<void> {
    if (options.resetPage) {
      page.value = 1
    }
    if (options.page !== undefined) {
      page.value = options.page
    }
    if (options.q !== undefined) {
      query.value = options.q
    }

    loading.value = true
    error.value = null
    try {
      const data = await requirementsApi.listRequirements(projectId, {
        page: page.value,
        page_size: pageSize.value,
        q: query.value.trim() || undefined,
      })
      items.value = data.items
      total.value = data.total
      page.value = data.page
    } catch (err) {
      error.value = err instanceof Error ? err.message : '加载需求列表失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function create(
    projectId: number,
    payload: RequirementCreatePayload,
  ): Promise<RequirementDetail> {
    submitting.value = true
    try {
      const requirement = await requirementsApi.createRequirement(projectId, payload)
      await fetchList(projectId, { resetPage: true })
      return requirement
    } finally {
      submitting.value = false
    }
  }

  async function fetchDetail(requirementId: number): Promise<RequirementDetail> {
    detailLoading.value = true
    try {
      const data = await requirementsApi.getRequirement(requirementId)
      detail.value = data
      return data
    } finally {
      detailLoading.value = false
    }
  }

  async function updateTitle(requirementId: number, title: string): Promise<Requirement> {
    const updated = await requirementsApi.updateRequirement(requirementId, { title })
    if (detail.value && detail.value.id === requirementId) {
      detail.value = { ...detail.value, title: updated.title, updated_at: updated.updated_at }
    }
    const item = items.value.find((entry) => entry.id === requirementId)
    if (item) {
      item.title = updated.title
      item.updated_at = updated.updated_at
    }
    return updated
  }

  async function remove(requirementId: number, projectId: number): Promise<void> {
    submitting.value = true
    try {
      await requirementsApi.deleteRequirement(requirementId)
      if (items.value.length === 1 && page.value > 1) {
        page.value -= 1
      }
      await fetchList(projectId)
    } finally {
      submitting.value = false
    }
  }

  async function fetchVersions(requirementId: number): Promise<void> {
    versionsLoading.value = true
    try {
      const data = await requirementsApi.listVersions(requirementId, {
        page: 1,
        page_size: VERSION_PAGE_SIZE,
      })
      versions.value = data.items
      versionsTotal.value = data.total
    } finally {
      versionsLoading.value = false
    }
  }

  async function saveVersion(
    requirementId: number,
    payload: VersionCreatePayload,
  ): Promise<RequirementVersionDetail> {
    saving.value = true
    try {
      const created = await requirementsApi.createVersion(requirementId, payload)
      applyCurrentVersion(requirementId, created)
      await fetchVersions(requirementId).catch(() => undefined)
      return created
    } finally {
      saving.value = false
    }
  }

  async function uploadVersion(
    requirementId: number,
    file: File,
    note?: string,
  ): Promise<RequirementVersionDetail> {
    uploading.value = true
    try {
      const created = await requirementsApi.uploadVersion(requirementId, file, note)
      applyCurrentVersion(requirementId, created)
      await fetchVersions(requirementId).catch(() => undefined)
      return created
    } finally {
      uploading.value = false
    }
  }

  function applyCurrentVersion(requirementId: number, created: RequirementVersionDetail): void {
    if (!detail.value || detail.value.id !== requirementId) {
      return
    }
    detail.value = {
      ...detail.value,
      content: created.content,
      current_version_no: created.version_no,
      version_no: created.version_no,
      updated_at: created.created_at,
    }
  }

  async function loadVersion(
    requirementId: number,
    versionNo: number,
  ): Promise<RequirementVersionDetail> {
    return requirementsApi.getVersion(requirementId, versionNo)
  }

  function resetDetail(): void {
    detail.value = null
    versions.value = []
    versionsTotal.value = 0
  }

  function resetList(): void {
    items.value = []
    total.value = 0
    page.value = 1
    query.value = ''
    error.value = null
  }

  return {
    items,
    total,
    page,
    pageSize,
    query,
    loading,
    submitting,
    error,
    detail,
    detailLoading,
    versions,
    versionsTotal,
    versionsLoading,
    saving,
    uploading,
    isEmpty,
    fetchList,
    create,
    fetchDetail,
    updateTitle,
    remove,
    fetchVersions,
    saveVersion,
    uploadVersion,
    loadVersion,
    resetDetail,
    resetList,
  }
})
