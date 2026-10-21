<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import ApprovalPanel from '@/components/ApprovalPanel.vue'
import ArtifactPanel from '@/components/ArtifactPanel.vue'
import RunStateHistory from '@/components/RunStateHistory.vue'
import { useRunStore } from '@/stores/run'
import { formatDateTime, formatDuration } from '@/utils/datetime'
import { getErrorMessage } from '@/utils/feedback'
import { runStatusMeta } from '@/utils/status'
import {
  activeStageIndex,
  buildStageSteps,
  isActiveRunStatus,
  stageLabel,
} from '@/utils/stage'

const route = useRoute()
const router = useRouter()
const store = useRunStore()

const runId = computed(() => Number(route.params.runId))
const refreshing = ref(false)

const steps = computed(() =>
  store.detail ? buildStageSteps(store.detail.status, store.detail.current_stage) : [],
)
const stepActive = computed(() =>
  store.detail ? activeStageIndex(store.detail.status, store.detail.current_stage) : 0,
)
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
  store.stopPolling()
})

watch(runId, (next, previous) => {
  if (next !== previous) {
    store.stopPolling()
    load()
  }
})

async function load(): Promise<void> {
  if (!Number.isFinite(runId.value) || runId.value <= 0) {
    return
  }

  store.resetDetail()
  try {
    const detail = await store.fetchDetail(runId.value)
    void store.fetchPendingApproval(runId.value).catch(() => undefined)
    void store.fetchStates(runId.value).catch(() => undefined)
    void store.fetchArtifacts(runId.value).catch(() => undefined)
    if (isActiveRunStatus(detail.status)) {
      store.startPolling(runId.value)
    }
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '加载运行详情失败'))
  }
}

async function refreshAll(): Promise<void> {
  if (!store.detail) {
    return
  }
  refreshing.value = true
  try {
    const detail = await store.fetchDetail(runId.value, { silent: true })
    await Promise.all([
      store.fetchPendingApproval(runId.value).catch(() => undefined),
      store.fetchStates(runId.value).catch(() => undefined),
      store.fetchArtifacts(runId.value).catch(() => undefined),
    ])
    if (isActiveRunStatus(detail.status) && !store.polling) {
      store.startPolling(runId.value)
    }
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '刷新运行详情失败'))
  } finally {
    refreshing.value = false
  }
}

async function handleDecided(): Promise<void> {
  await store.fetchArtifacts(runId.value).catch(() => undefined)
  if (store.detail && isActiveRunStatus(store.detail.status) && !store.polling) {
    store.startPolling(runId.value)
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
    if (store.detail && isActiveRunStatus(store.detail.status) && !store.polling) {
      store.startPolling(runId.value)
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
              <span>当前阶段 {{ stageLabel(store.detail.current_stage) }}</span>
              <span>
                评审轮次 {{ store.detail.review_round }} / {{ store.detail.max_review_rounds }}
              </span>
              <span v-if="store.polling" class="run-polling">● 自动刷新中</span>
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
          <h2 class="section-title">阶段进度</h2>
          <span class="muted">
            {{ store.polling ? '运行中每 3 秒自动刷新' : '状态来自后端字段，前端不做推断' }}
          </span>
        </header>

        <el-steps
          :active="stepActive"
          finish-status="success"
          align-center
          class="run-steps"
        >
          <el-step
            v-for="step in steps"
            :key="step.key"
            :title="step.label"
            :description="step.description"
            :status="step.status === 'finish' ? 'success' : step.status"
            :class="['run-step', step.tone ? `run-step--${step.tone}` : '']"
          />
        </el-steps>
      </section>

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
