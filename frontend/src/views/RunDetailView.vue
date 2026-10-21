<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { listRunEvents } from '@/api/runs'
import type { RunEvent, RunStage } from '@/api/types'
import ApprovalPanel from '@/components/ApprovalPanel.vue'
import ArtifactPanel from '@/components/ArtifactPanel.vue'
import PipelineGraph from '@/components/PipelineGraph.vue'
import RunStateHistory from '@/components/RunStateHistory.vue'
import RunStreamPanel from '@/components/RunStreamPanel.vue'
import RunTimelinePanel from '@/components/RunTimelinePanel.vue'
import { useRunStream } from '@/composables/useRunStream'
import { SSE_FALLBACK_POLL_INTERVAL_MS, useRunStore } from '@/stores/run'
import { formatDateTime, formatDuration } from '@/utils/datetime'
import { getErrorMessage } from '@/utils/feedback'
import { pendingStageOf } from '@/utils/pipeline'
import { runStatusMeta } from '@/utils/status'
import { isActiveRunStatus, isRunStage, stageLabel } from '@/utils/stage'

const route = useRoute()
const router = useRouter()
const store = useRunStore()

const runId = computed(() => Number(route.params.runId))
const refreshing = ref(false)

const {
  status: streamStatus,
  connected: streamConnected,
  tokensByStage,
  timeline: timelineEvents,
  promptTokens: streamPromptTokens,
  completionTokens: streamCompletionTokens,
  currentStage: streamCurrentStage,
  start: startStream,
  stop: stopStream,
  clear: clearStream,
  seedTimeline,
  setCurrentStage: setStreamStage,
} = useRunStream(() => runId.value, {
  onInterrupt: () => {
    void refreshFromStream()
  },
  onDecision: () => {
    void refreshFromStream()
  },
  onRunFinished: () => {
    void refreshFromStream()
  },
  onArtifactSaved: () => {
    void store.fetchArtifacts(runId.value).catch(() => undefined)
  },
})

const liveStage = computed<RunStage | null>(() => {
  const stage = streamCurrentStage.value
  if (isRunStage(stage)) {
    return stage
  }
  return store.detail?.current_stage ?? null
})

const pendingStage = computed<RunStage | null>(() =>
  pendingStageOf(store.pendingApproval),
)

const streamText = computed(() => {
  const stage = liveStage.value
  if (!stage) {
    return ''
  }
  return tokensByStage.value[stage] ?? ''
})

const canCancel = computed(() =>
  store.detail ? isActiveRunStatus(store.detail.status) : false,
)
const canRetry = computed(
  () => store.detail?.status === 'failed' || store.detail?.status === 'cancelled',
)
const hasError = computed(
  () => store.detail?.status === 'failed' || Boolean(store.detail?.error_code),
)
const threadShort = computed(() =>
  store.detail?.thread_id ? store.detail.thread_id.slice(0, 8) : '-',
)

onMounted(() => {
  load()
})

onBeforeUnmount(() => {
  stopStream()
  store.stopPolling()
})

watch(runId, (next, previous) => {
  if (next !== previous) {
    stopStream()
    store.stopPolling()
    load()
  }
})

// SSE 断开 → 5s 轮询兜底；重连成功 → 停止轮询
watch(streamStatus, (next) => {
  const detail = store.detail
  if (!detail || !isActiveRunStatus(detail.status)) {
    return
  }
  if (next === 'error') {
    store.startPolling(runId.value, SSE_FALLBACK_POLL_INTERVAL_MS)
  } else if (next === 'open') {
    store.stopPolling()
  }
})

async function load(): Promise<void> {
  if (!Number.isFinite(runId.value) || runId.value <= 0) {
    return
  }

  stopStream()
  clearStream()
  store.resetDetail()
  try {
    const detail = await store.fetchDetail(runId.value)
    setStreamStage(detail.current_stage)
    await Promise.all([
      store.fetchPendingApproval(runId.value).catch(() => undefined),
      store.fetchStates(runId.value).catch(() => undefined),
      store.fetchArtifacts(runId.value).catch(() => undefined),
      seedHistory(),
    ])
    if (isActiveRunStatus(detail.status)) {
      startStream()
    }
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '加载运行详情失败'))
  }
}

/** 首屏时间线：按 after_seq 翻页拉历史（最多 10 页 / 2000 条）；失败不阻塞页面 */
async function seedHistory(): Promise<void> {
  const collected: RunEvent[] = []
  let afterSeq = 0
  try {
    for (let page = 0; page < 10; page += 1) {
      const events = await listRunEvents(runId.value, {
        after_seq: afterSeq,
        page_size: 200,
      })
      collected.push(...events)
      if (events.length < 200) {
        break
      }
      afterSeq = events[events.length - 1]?.seq ?? afterSeq
    }
  } catch {
    // 历史接口失败时只展示实时事件
  }
  if (collected.length > 0) {
    seedTimeline(collected)
  }
}

async function refreshFromStream(): Promise<void> {
  if (!store.detail) {
    return
  }
  await store.fetchDetail(runId.value, { silent: true }).catch(() => undefined)
  await Promise.all([
    store.fetchPendingApproval(runId.value).catch(() => undefined),
    store.fetchStates(runId.value).catch(() => undefined),
    store.fetchArtifacts(runId.value).catch(() => undefined),
  ])
}

async function refreshAll(): Promise<void> {
  if (!store.detail) {
    return
  }
  refreshing.value = true
  try {
    await refreshFromStream()
    if (
      store.detail &&
      isActiveRunStatus(store.detail.status) &&
      streamStatus.value !== 'open'
    ) {
      startStream()
    }
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '刷新运行详情失败'))
  } finally {
    refreshing.value = false
  }
}

async function handleDecided(): Promise<void> {
  await refreshFromStream()
}

async function handleSelectStage(stage: RunStage): Promise<void> {
  const candidates = store.artifacts.filter((artifact) => artifact.stage === stage)
  if (candidates.length === 0) {
    ElMessage.info(`${stageLabel(stage)}还没有产物`)
    return
  }
  const latest = candidates.reduce((left, right) =>
    right.version > left.version ? right : left,
  )
  try {
    await store.loadArtifact(latest.id)
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '加载产物正文失败'))
  }
}

async function cancelRun(): Promise<void> {
  const confirmed = await ElMessageBox.confirm(
    '取消后流水线会在下一个节点边界停止，已生成的产物保留。确定取消？',
    '取消运行',
    { type: 'warning', confirmButtonText: '取消运行', cancelButtonText: '继续运行' },
  )
    .then(() => true)
    .catch(() => false)
  if (!confirmed) {
    return
  }

  try {
    await store.cancel(runId.value)
    ElMessage.success('已提交取消请求')
    await refreshFromStream()
    if (store.detail && isActiveRunStatus(store.detail.status)) {
      if (streamStatus.value !== 'open') {
        startStream()
      }
    } else {
      stopStream()
    }
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '取消运行失败'))
  }
}

async function retryRun(): Promise<void> {
  const confirmed = await ElMessageBox.confirm(
    '重试会从失败节点重新开始，确定重试？',
    '重试运行',
    { type: 'warning', confirmButtonText: '重试', cancelButtonText: '取消' },
  )
    .then(() => true)
    .catch(() => false)
  if (!confirmed) {
    return
  }

  try {
    await store.retry(runId.value)
    ElMessage.success('已提交重试请求')
    store.stopPolling()
    startStream()
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '重试运行失败'))
  }
}
</script>

<template>
  <div v-loading="store.detailLoading" class="page">
    <el-breadcrumb class="crumbs" separator="/">
      <el-breadcrumb-item :to="{ path: '/runs' }">运行</el-breadcrumb-item>
      <el-breadcrumb-item>#{{ runId }}</el-breadcrumb-item>
    </el-breadcrumb>

    <template v-if="store.detail">
      <section class="surface">
        <div class="detail-toolbar">
          <div class="page-head__text">
            <h1 class="page-title">运行 #{{ store.detail.id }}</h1>
            <div class="detail-meta">
              <el-tag size="small" effect="plain" :type="runStatusMeta(store.detail.status).type">
                {{ runStatusMeta(store.detail.status).label }}
              </el-tag>
              <span>当前阶段 {{ stageLabel(liveStage) }}</span>
              <span>
                评审轮次 {{ store.detail.review_round }} / {{ store.detail.max_review_rounds }}
              </span>
              <span v-if="streamConnected" class="run-polling">● SSE 实时</span>
              <span v-else-if="store.polling" class="run-polling">● 轮询兜底（5s）</span>
            </div>
          </div>

          <div class="page-actions">
            <el-button :icon="Refresh" :loading="refreshing" @click="refreshAll">刷新</el-button>
            <el-button v-if="canCancel" :loading="store.cancelling" @click="cancelRun">
              取消运行
            </el-button>
            <el-button
              v-if="canRetry"
              type="primary"
              plain
              :loading="store.retrying"
              @click="retryRun"
            >
              重试
            </el-button>
          </div>
        </div>

        <el-alert
          v-if="hasError"
          class="run-error"
          type="error"
          :closable="false"
          :title="store.detail.error_code || '运行失败'"
          :description="store.detail.error_message || '后端没有返回错误详情'"
          show-icon
        />

        <div class="run-meta-grid">
          <div class="run-meta-item">
            <span class="run-meta-item__label">thread_id</span>
            <span class="mono" :title="store.detail.thread_id">{{ threadShort }}</span>
          </div>
          <div class="run-meta-item">
            <span class="run-meta-item__label">Prompt tokens</span>
            <span class="mono">{{ store.detail.prompt_tokens }}</span>
          </div>
          <div class="run-meta-item">
            <span class="run-meta-item__label">Completion tokens</span>
            <span class="mono">{{ store.detail.completion_tokens }}</span>
          </div>
          <div class="run-meta-item">
            <span class="run-meta-item__label">开始时间</span>
            <span>{{ formatDateTime(store.detail.started_at) }}</span>
          </div>
          <div class="run-meta-item">
            <span class="run-meta-item__label">结束时间</span>
            <span>{{ formatDateTime(store.detail.finished_at) }}</span>
          </div>
          <div class="run-meta-item">
            <span class="run-meta-item__label">耗时</span>
            <span class="mono">
              {{ formatDuration(store.detail.started_at, store.detail.finished_at) }}
            </span>
          </div>
          <div class="run-meta-item">
            <span class="run-meta-item__label">创建时间</span>
            <span>{{ formatDateTime(store.detail.created_at) }}</span>
          </div>
          <div class="run-meta-item">
            <span class="run-meta-item__label">需求</span>
            <RouterLink
              class="requirement-title"
              :to="{
                name: 'requirement-detail',
                params: { requirementId: store.detail.requirement_id },
              }"
            >
              需求 #{{ store.detail.requirement_id }}
            </RouterLink>
          </div>
        </div>
      </section>

      <section class="surface">
        <header class="section-head">
          <h2 class="section-title">流水线</h2>
          <span class="muted">
            {{ streamConnected ? 'SSE 实时更新节点状态' : '节点状态来自后端字段' }}
          </span>
        </header>

        <PipelineGraph
          :status="store.detail.status"
          :current-stage="liveStage"
          :pending-stage="pendingStage"
          @select-stage="handleSelectStage"
        />

        <p class="pipeline-current-stage">
          当前阶段：<strong>{{ stageLabel(liveStage) }}</strong>
          <span class="muted">· 点击节点查看该阶段产物</span>
        </p>
      </section>

      <div class="run-live-grid">
        <RunStreamPanel
          :stage="liveStage"
          :text="streamText"
          :connection="streamStatus"
          :prompt-tokens="streamPromptTokens"
          :completion-tokens="streamCompletionTokens"
        />

        <RunTimelinePanel :events="timelineEvents" :connected="streamConnected" />
      </div>

      <ApprovalPanel
        v-if="store.pendingApproval"
        :run-id="store.detail.id"
        :pending="store.pendingApproval"
        @decided="handleDecided"
      />

      <ArtifactPanel />

      <RunStateHistory :states="store.states" :loading="store.statesLoading" />
    </template>

    <div v-else-if="!store.detailLoading" class="surface">
      <el-empty description="运行不存在或加载失败">
        <el-button @click="router.push('/runs')">返回运行列表</el-button>
      </el-empty>
    </div>
  </div>
</template>
