import { computed, ref } from 'vue'

import { defineStore } from 'pinia'

import * as runsApi from '@/api/runs'
import type { ArtifactListParams, RunCreatePayload, RunListParams } from '@/api/runs'
import type {
  ApprovalPayload,
  ApprovalResult,
  Artifact,
  ArtifactDetail,
  PendingApproval,
  PullRequest,
  Run,
  RunDetail,
  RunState,
  RunStatus,
} from '@/api/types'
import { isActiveRunStatus } from '@/utils/stage'

export const RUN_POLL_INTERVAL_MS = 3000

/** SSE 断开后的兜底轮询间隔 */
export const SSE_FALLBACK_POLL_INTERVAL_MS = 5000

export const useRunStore = defineStore('run', () => {
  const items = ref<Run[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const statusFilter = ref<RunStatus | ''>('')
  const loading = ref(false)
  const error = ref<string | null>(null)

  const detail = ref<RunDetail | null>(null)
  const detailLoading = ref(false)
  const pendingApproval = ref<PendingApproval | null>(null)
  const pendingLoading = ref(false)
  const states = ref<RunState[]>([])
  const statesLoading = ref(false)
  const artifacts = ref<Artifact[]>([])
  const artifactsTotal = ref(0)
  const artifactsLoading = ref(false)
  const pullRequests = ref<PullRequest[]>([])
  const pullRequestsLoading = ref(false)
  const selectedArtifact = ref<ArtifactDetail | null>(null)
  const artifactLoading = ref(false)
  const artifactSaving = ref(false)

  const approving = ref(false)
  const cancelling = ref(false)
  const retrying = ref(false)

  const polling = ref(false)
  const pollingPaused = ref(false)
  let pollTimer: ReturnType<typeof setTimeout> | null = null
  let pollRunId: number | null = null
  let pollIntervalMs = RUN_POLL_INTERVAL_MS

  const isEmpty = computed(() => !loading.value && items.value.length === 0)
  const canPoll = computed(() =>
    detail.value ? isActiveRunStatus(detail.value.status) : false,
  )

  async function fetchList(
    options: RunListParams & { resetPage?: boolean } = {},
  ): Promise<void> {
    if (options.resetPage) {
      page.value = 1
    }
    if (options.page !== undefined) {
      page.value = options.page
    }
    if (options.status !== undefined) {
      statusFilter.value = options.status
    }

    loading.value = true
    error.value = null
    try {
      const data = await runsApi.listRuns({
        page: page.value,
        page_size: pageSize.value,
        status: statusFilter.value || undefined,
      })
      items.value = data.items
      total.value = data.total
      page.value = data.page
    } catch (err) {
      error.value = err instanceof Error ? err.message : '加载运行列表失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function create(requirementId: number, payload: RunCreatePayload = {}): Promise<Run> {
    return runsApi.createRun(requirementId, payload)
  }

  async function fetchDetail(
    runId: number,
    options: { silent?: boolean } = {},
  ): Promise<RunDetail> {
    if (!options.silent) {
      detailLoading.value = true
    }
    try {
      const data = await runsApi.getRun(runId)
      detail.value = data

      if (isActiveRunStatus(data.status)) {
        if (data.pending_approval !== undefined) {
          pendingApproval.value = data.pending_approval ?? null
        }
      } else {
        pendingApproval.value = null
        stopPolling()
      }

      return data
    } finally {
      if (!options.silent) {
        detailLoading.value = false
      }
    }
  }

  async function fetchPendingApproval(runId: number): Promise<void> {
    pendingLoading.value = true
    try {
      pendingApproval.value = await runsApi.getPendingApproval(runId)
    } finally {
      pendingLoading.value = false
    }
  }

  async function fetchStates(runId: number, limit = 20): Promise<void> {
    statesLoading.value = true
    try {
      states.value = await runsApi.listRunStates(runId, limit)
    } finally {
      statesLoading.value = false
    }
  }

  async function fetchArtifacts(
    runId: number,
    options: ArtifactListParams = {},
  ): Promise<void> {
    artifactsLoading.value = true
    try {
      const data = await runsApi.listArtifacts(runId, {
        page: options.page ?? 1,
        page_size: options.page_size ?? 100,
      })
      artifacts.value = data.items
      artifactsTotal.value = data.total
    } finally {
      artifactsLoading.value = false
    }
  }

  async function fetchPullRequests(runId: number): Promise<void> {
    pullRequestsLoading.value = true
    try {
      pullRequests.value = await runsApi.listPullRequests(runId)
    } finally {
      pullRequestsLoading.value = false
    }
  }

  async function loadArtifact(artifactId: number): Promise<ArtifactDetail> {
    artifactLoading.value = true
    try {
      const data = await runsApi.getArtifact(artifactId)
      selectedArtifact.value = data
      return data
    } finally {
      artifactLoading.value = false
    }
  }

  async function saveArtifact(artifactId: number, content: string): Promise<ArtifactDetail> {
    artifactSaving.value = true
    try {
      const updated = await runsApi.updateArtifact(artifactId, content)
      selectedArtifact.value = {
        ...updated,
        content: updated.content || content,
      }
      const runId = detail.value?.id
      if (runId) {
        await fetchArtifacts(runId).catch(() => undefined)
      }
      return updated
    } finally {
      artifactSaving.value = false
    }
  }

  async function submitApproval(
    runId: number,
    payload: ApprovalPayload,
  ): Promise<ApprovalResult> {
    pausePolling()
    approving.value = true
    try {
      const result = await runsApi.submitApproval(runId, payload)
      await refreshAfterDecision(runId)
      return result
    } finally {
      approving.value = false
      resumePolling()
    }
  }

  async function refreshAfterDecision(runId: number): Promise<void> {
    await fetchDetail(runId, { silent: true }).catch(() => undefined)
    await Promise.all([
      fetchPendingApproval(runId).catch(() => undefined),
      fetchStates(runId).catch(() => undefined),
    ])
  }

  async function cancel(runId: number): Promise<Run> {
    cancelling.value = true
    try {
      const run = await runsApi.cancelRun(runId)
      await fetchDetail(runId, { silent: true }).catch(() => undefined)
      return run
    } finally {
      cancelling.value = false
    }
  }

  async function retry(runId: number): Promise<Run> {
    retrying.value = true
    try {
      const run = await runsApi.retryRun(runId)
      await fetchDetail(runId, { silent: true }).catch(() => undefined)
      await fetchStates(runId).catch(() => undefined)
      if (detail.value && isActiveRunStatus(detail.value.status)) {
        startPolling(runId)
      }
      return run
    } finally {
      retrying.value = false
    }
  }

  function clearPollTimer(): void {
    if (pollTimer !== null) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
  }

  function schedulePoll(): void {
    clearPollTimer()
    if (!polling.value || pollingPaused.value || pollRunId === null) {
      return
    }
    if (!canPoll.value) {
      stopPolling()
      return
    }

    const runId = pollRunId
    pollTimer = setTimeout(() => {
      if (!polling.value || pollingPaused.value) {
        return
      }
      void fetchDetail(runId, { silent: true })
        .catch(() => undefined)
        .finally(() => {
          schedulePoll()
        })
    }, pollIntervalMs)
  }

  function startPolling(runId: number, intervalMs = RUN_POLL_INTERVAL_MS): void {
    pollRunId = runId
    pollIntervalMs = intervalMs
    polling.value = true
    pollingPaused.value = false
    schedulePoll()
  }

  function stopPolling(): void {
    polling.value = false
    pollingPaused.value = false
    pollRunId = null
    clearPollTimer()
  }

  function pausePolling(): void {
    pollingPaused.value = true
    clearPollTimer()
  }

  function resumePolling(): void {
    if (!polling.value) {
      return
    }
    if (!canPoll.value) {
      stopPolling()
      return
    }
    pollingPaused.value = false
    schedulePoll()
  }

  function resetDetail(): void {
    stopPolling()
    detail.value = null
    pendingApproval.value = null
    states.value = []
    artifacts.value = []
    artifactsTotal.value = 0
    pullRequests.value = []
    selectedArtifact.value = null
  }

  function resetList(): void {
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
    error,
    detail,
    detailLoading,
    pendingApproval,
    pendingLoading,
    states,
    statesLoading,
    artifacts,
    artifactsTotal,
    artifactsLoading,
    pullRequests,
    pullRequestsLoading,
    selectedArtifact,
    artifactLoading,
    artifactSaving,
    approving,
    cancelling,
    retrying,
    polling,
    pollingPaused,
    isEmpty,
    canPoll,
    fetchList,
    create,
    fetchDetail,
    fetchPendingApproval,
    fetchStates,
    fetchArtifacts,
    fetchPullRequests,
    loadArtifact,
    saveArtifact,
    submitApproval,
    cancel,
    retry,
    startPolling,
    stopPolling,
    pausePolling,
    resumePolling,
    resetDetail,
    resetList,
  }
})
