import { computed, ref } from 'vue'

import { defineStore } from 'pinia'

import * as projectsApi from '@/api/projects'
import type { ProjectCreatePayload, ProjectUpdatePayload } from '@/api/projects'
import type { Project, ProjectStatus } from '@/api/types'

export const useProjectStore = defineStore('project', () => {
  const items = ref<Project[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(12)
  const statusFilter = ref<ProjectStatus | ''>('')
  const loading = ref(false)
  const submitting = ref(false)
  const error = ref<string | null>(null)

  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
  const isEmpty = computed(() => !loading.value && items.value.length === 0)

  async function fetchList(options: { page?: number; status?: ProjectStatus | '' } = {}): Promise<void> {
    if (typeof options.page === 'number') {
      page.value = options.page
    }
    if (options.status !== undefined) {
      statusFilter.value = options.status
    }

    loading.value = true
    error.value = null
    try {
      const data = await projectsApi.listProjects({
        page: page.value,
        page_size: pageSize.value,
        status: statusFilter.value || undefined,
      })
      items.value = data.items
      total.value = data.total
      page.value = data.page
    } catch (err) {
      error.value = err instanceof Error ? err.message : '加载项目列表失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function create(payload: ProjectCreatePayload): Promise<Project> {
    submitting.value = true
    try {
      const project = await projectsApi.createProject(payload)
      await fetchList({ page: 1 })
      return project
    } finally {
      submitting.value = false
    }
  }

  async function update(projectId: number, payload: ProjectUpdatePayload): Promise<Project> {
    submitting.value = true
    try {
      const project = await projectsApi.updateProject(projectId, payload)
      await fetchList()
      return project
    } finally {
      submitting.value = false
    }
  }

  async function archive(projectId: number): Promise<Project> {
    return update(projectId, { status: 'archived' })
  }

  async function remove(projectId: number): Promise<void> {
    submitting.value = true
    try {
      await projectsApi.deleteProject(projectId)
      if (items.value.length === 1 && page.value > 1) {
        page.value -= 1
      }
      await fetchList()
    } finally {
      submitting.value = false
    }
  }

  function reset(): void {
    items.value = []
    total.value = 0
    page.value = 1
    statusFilter.value = ''
    error.value = null
  }

  return {
    items,
    total,
    page,
    pageSize,
    statusFilter,
    loading,
    submitting,
    error,
    totalPages,
    isEmpty,
    fetchList,
    create,
    update,
    archive,
    remove,
    reset,
  }
})
