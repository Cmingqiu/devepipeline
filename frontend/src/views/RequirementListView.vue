<script setup lang="ts">
import { onBeforeUnmount, computed, onMounted, ref, watch } from 'vue'

import { Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { getProject } from '@/api/projects'
import type { RequirementCreatePayload } from '@/api/requirements'
import type { Requirement } from '@/api/types'
import RequirementFormDialog from '@/components/RequirementFormDialog.vue'
import { useRequirementStore } from '@/stores/requirement'
import { formatDateTime } from '@/utils/datetime'
import { getErrorMessage, isConflict } from '@/utils/feedback'
import { requirementStatusMeta } from '@/utils/status'

const route = useRoute()
const router = useRouter()
const store = useRequirementStore()

const projectId = computed(() => Number(route.params.projectId))
const projectName = ref('')
const keyword = ref('')
const dialogVisible = ref(false)
const deletingId = ref<number | null>(null)

let searchTimer: ReturnType<typeof setTimeout> | undefined

onMounted(() => {
  store.resetList()
  loadProject()
  loadRequirements()
})

onBeforeUnmount(() => {
  if (searchTimer) {
    clearTimeout(searchTimer)
  }
})

watch(keyword, () => {
  if (searchTimer) {
    clearTimeout(searchTimer)
  }
  searchTimer = setTimeout(() => {
    loadRequirements(1, keyword.value)
  }, 300)
})

function loadProject(): void {
  getProject(projectId.value)
    .then((project) => {
      projectName.value = project.name
    })
    .catch(() => {
      projectName.value = ''
    })
}

function loadRequirements(page?: number, q?: string): void {
  store
    .fetchList(projectId.value, { page, q })
    .catch((err) => {
      ElMessage.error(getErrorMessage(err, '加载需求列表失败'))
    })
}

async function handleCreate(payload: RequirementCreatePayload): Promise<void> {
  try {
    await store.create(projectId.value, payload)
    dialogVisible.value = false
    ElMessage.success('需求已创建，已生成 v1')
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '创建需求失败'))
  }
}

function openDetail(requirement: Requirement): void {
  router.push({
    name: 'requirement-detail',
    params: { requirementId: requirement.id },
  })
}

function openRun(requirement: Requirement): void {
  if (!requirement.latest_run_id) {
    return
  }
  router.push({
    name: 'run-detail',
    params: { runId: requirement.latest_run_id },
  })
}

async function handleDelete(requirement: Requirement): Promise<void> {
  const confirmed = await ElMessageBox.confirm(
    `删除后无法恢复，确定删除「${requirement.title}」？`,
    '删除需求',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  )
    .then(() => true)
    .catch(() => false)
  if (!confirmed) {
    return
  }

  deletingId.value = requirement.id
  try {
    await store.remove(requirement.id, projectId.value)
    ElMessage.success('需求已删除')
  } catch (err) {
    if (isConflict(err)) {
      ElMessage.warning('该需求已有运行记录，不能删除')
      return
    }
    ElMessage.error(getErrorMessage(err, '删除需求失败'))
  } finally {
    deletingId.value = null
  }
}
</script>

<template>
  <div class="page">
    <el-breadcrumb class="crumbs" separator="/">
      <el-breadcrumb-item :to="{ path: '/projects' }">项目</el-breadcrumb-item>
      <el-breadcrumb-item>{{ projectName || `项目 #${projectId}` }}</el-breadcrumb-item>
      <el-breadcrumb-item>需求</el-breadcrumb-item>
    </el-breadcrumb>

    <header class="page-head">
      <div class="page-head__text">
        <h1 class="page-title">{{ projectName || '需求' }}</h1>
        <p class="page-subtitle">
          共 {{ store.total }} 条需求；点击标题进入详情编辑正文与版本。
        </p>
      </div>
      <div class="page-actions">
        <el-input
          v-model="keyword"
          placeholder="搜索需求标题"
          clearable
          :prefix-icon="Search"
          style="width: 240px"
        />
        <el-button type="primary" @click="dialogVisible = true">新建需求</el-button>
      </div>
    </header>

    <div class="surface surface--flush">
      <el-table v-loading="store.loading" :data="store.items" row-key="id">
        <el-table-column label="标题" min-width="320">
          <template #default="{ row }">
            <RouterLink
              class="requirement-title"
              :to="{ name: 'requirement-detail', params: { requirementId: row.id } }"
            >
              {{ row.title }}
            </RouterLink>
            <div class="muted mono">#{{ row.id }}</div>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag
              size="small"
              effect="plain"
              :type="requirementStatusMeta(row.status).type"
            >
              {{ requirementStatusMeta(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="当前版本" width="110">
          <template #default="{ row }">
            <span class="mono">v{{ row.current_version_no }}</span>
          </template>
        </el-table-column>

        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">
            <span class="muted">{{ formatDateTime(row.updated_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">查看</el-button>
            <el-button
              v-if="row.latest_run_id"
              link
              type="primary"
              @click="openRun(row)"
            >
              查看运行
            </el-button>
            <el-button
              link
              type="danger"
              :loading="deletingId === row.id"
              @click="handleDelete(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>

        <template #empty>
          <el-empty
            :description="store.query ? '没有匹配的需求' : '还没有需求，先创建一条'"
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
        @current-change="loadRequirements"
      />
    </div>

    <RequirementFormDialog
      v-model="dialogVisible"
      :loading="store.submitting"
      @submit="handleCreate"
    />
  </div>
</template>
