<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { RouterLink, useRouter } from 'vue-router'

import { getRequirement } from '@/api/requirements'
import type { Run, RunStatus } from '@/api/types'
import { useRunStore } from '@/stores/run'
import { formatDateTime, formatDuration } from '@/utils/datetime'
import { getErrorMessage } from '@/utils/feedback'
import { runStatusMeta } from '@/utils/status'
import { stageLabel } from '@/utils/stage'

const router = useRouter()
const store = useRunStore()

const requirementTitles = ref<Record<number, string>>({})
const refreshing = ref(false)

const statusOptions: Array<{ value: RunStatus | ''; label: string }> = [
  { value: '', label: '全部状态' },
  { value: 'queued', label: '排队中' },
  { value: 'running', label: '运行中' },
  { value: 'waiting_approval', label: '待审批' },
  { value: 'succeeded', label: '成功' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]

onMounted(() => {
  store.resetList()
  loadRuns()
})

async function loadRuns(page?: number): Promise<void> {
  try {
    await store.fetchList({ page })
    await loadRequirementTitles()
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '加载运行列表失败'))
  }
}

/** 列表接口只有 requirement_id，尽量补上需求标题；失败就用 id 兜底 */
async function loadRequirementTitles(): Promise<void> {
  const missing = [
    ...new Set(
      store.items
        .map((run) => run.requirement_id)
        .filter((id) => !requirementTitles.value[id]),
    ),
  ]
  if (missing.length === 0) {
    return
  }

  const results = await Promise.allSettled(missing.map((id) => getRequirement(id)))
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') {
      requirementTitles.value[missing[index]] = result.value.title
    }
  })
}

function handleStatusChange(value: RunStatus | ''): void {
  store.statusFilter = value
  loadRuns(1)
}

function handleRowClick(row: Run): void {
  openRun(row)
}

function openRun(run: Run): void {
  router.push({ name: 'run-detail', params: { runId: run.id } })
}

async function refresh(): Promise<void> {
  refreshing.value = true
  try {
    await store.fetchList()
    await loadRequirementTitles()
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '刷新运行列表失败'))
  } finally {
    refreshing.value = false
  }
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="page-head__text">
        <h1 class="page-title">运行</h1>
        <p class="page-subtitle">
          共 {{ store.total }} 次运行；运行中每 3 秒自动刷新详情，审批在详情页完成。
        </p>
      </div>
      <div class="page-actions">
        <el-select
          :model-value="store.statusFilter"
          style="width: 150px"
          @change="handleStatusChange"
        >
          <el-option
            v-for="option in statusOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-button :icon="Refresh" :loading="refreshing" @click="refresh">刷新</el-button>
      </div>
    </header>

    <div class="surface surface--flush">
      <el-table
        v-loading="store.loading"
        :data="store.items"
        row-key="id"
        class="run-table"
        @row-click="handleRowClick"
      >
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="runStatusMeta(row.status).type">
              {{ runStatusMeta(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="项目" width="110">
          <template #default="{ row }">
            <span class="muted">项目 #{{ row.project_id }}</span>
          </template>
        </el-table-column>

        <el-table-column label="需求" min-width="220">
          <template #default="{ row }">
            <RouterLink
              class="requirement-title"
              :to="{ name: 'requirement-detail', params: { requirementId: row.requirement_id } }"
              @click.stop
            >
              {{ requirementTitles[row.requirement_id] || `需求 #${row.requirement_id}` }}
            </RouterLink>
            <div class="muted mono">run #{{ row.id }}</div>
          </template>
        </el-table-column>

        <el-table-column label="当前阶段" width="120">
          <template #default="{ row }">
            <span v-if="row.current_stage">{{ stageLabel(row.current_stage) }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>

        <el-table-column label="耗时" width="110">
          <template #default="{ row }">
            <span class="mono">{{ formatDuration(row.started_at, row.finished_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Tokens" width="140">
          <template #default="{ row }">
            <span class="mono">{{ row.prompt_tokens + row.completion_tokens }}</span>
            <div class="muted mono">
              ↓{{ row.prompt_tokens }} ↑{{ row.completion_tokens }}
            </div>
          </template>
        </el-table-column>

        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">
            <span class="muted">{{ formatDateTime(row.created_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openRun(row)">查看运行</el-button>
          </template>
        </el-table-column>

        <template #empty>
          <el-empty
            :description="store.statusFilter ? '该状态下没有运行' : '还没有运行，从需求详情启动流水线'"
          />
        </template>
      </el-table>
    </div>

    <div v-if="store.total > store.pageSize" class="page-actions" style="justify-content: center">
      <el-pagination
        layout="prev, pager, next"
        :total="store.total"
        :page-size="store.pageSize"
        :current-page="store.page"
        background
        @current-change="loadRuns"
      />
    </div>
  </div>
</template>
