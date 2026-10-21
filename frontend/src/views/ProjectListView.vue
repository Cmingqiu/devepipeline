<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'

import ProjectFormDialog from '@/components/ProjectFormDialog.vue'
import type { ProjectCreatePayload, ProjectUpdatePayload } from '@/api/projects'
import type { Project } from '@/api/types'
import { useProjectStore } from '@/stores/project'
import { formatDateTime } from '@/utils/datetime'
import { getErrorMessage, isConflict } from '@/utils/feedback'
import { projectStatusMeta } from '@/utils/status'

const router = useRouter()
const store = useProjectStore()

const dialogVisible = ref(false)
const editingProject = ref<Project | null>(null)

onMounted(() => {
  loadProjects()
})

function loadProjects(page?: number): void {
  store.fetchList({ page }).catch((err) => {
    ElMessage.error(getErrorMessage(err, '加载项目列表失败'))
  })
}

function openCreate(): void {
  editingProject.value = null
  dialogVisible.value = true
}

function openEdit(project: Project): void {
  editingProject.value = project
  dialogVisible.value = true
}

async function handleSubmit(payload: ProjectCreatePayload | ProjectUpdatePayload): Promise<void> {
  try {
    if (editingProject.value) {
      await store.update(editingProject.value.id, payload as ProjectUpdatePayload)
      ElMessage.success('项目已更新')
    } else {
      await store.create(payload as ProjectCreatePayload)
      ElMessage.success('项目已创建')
    }
    dialogVisible.value = false
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '保存项目失败'))
  }
}

async function handleArchive(project: Project): Promise<void> {
  const confirmed = await ElMessageBox.confirm(
    `归档后项目将不在默认视图中展示，确定归档「${project.name}」？`,
    '归档项目',
    { type: 'warning', confirmButtonText: '归档', cancelButtonText: '取消' },
  )
    .then(() => true)
    .catch(() => false)
  if (!confirmed) {
    return
  }

  try {
    await store.archive(project.id)
    ElMessage.success('项目已归档')
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '归档项目失败'))
  }
}

async function handleDelete(project: Project): Promise<void> {
  const confirmed = await ElMessageBox.confirm(
    `删除后无法恢复，确定删除「${project.name}」？`,
    '删除项目',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  )
    .then(() => true)
    .catch(() => false)
  if (!confirmed) {
    return
  }

  try {
    await store.remove(project.id)
    ElMessage.success('项目已删除')
  } catch (err) {
    if (isConflict(err)) {
      ElMessage.warning('项目下还有需求，不能删除')
      return
    }
    ElMessage.error(getErrorMessage(err, '删除项目失败'))
  }
}

function openRequirements(project: Project): void {
  router.push({ name: 'requirements', params: { projectId: project.id } })
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div class="page-head__text">
        <h1 class="page-title">项目</h1>
        <p class="page-subtitle">每个项目下管理需求与版本，M1 只做需求录入与管理。</p>
      </div>
      <div class="page-actions">
        <el-button type="primary" :icon="Plus" @click="openCreate">新建项目</el-button>
      </div>
    </header>

    <div v-loading="store.loading" class="project-grid-wrap">
      <div v-if="store.isEmpty" class="surface">
        <el-empty description="还没有项目，先创建一个">
          <el-button type="primary" @click="openCreate">新建项目</el-button>
        </el-empty>
      </div>

      <div v-else class="project-grid">
        <el-card
          v-for="project in store.items"
          :key="project.id"
          class="project-card"
          shadow="never"
          :body-style="{ padding: '18px', height: '100%', display: 'flex', flexDirection: 'column' }"
        >
          <div class="project-card__head">
            <h2 class="project-card__name">{{ project.name }}</h2>
            <el-tag size="small" :type="projectStatusMeta(project.status).type" effect="plain">
              {{ projectStatusMeta(project.status).label }}
            </el-tag>
          </div>

          <span class="project-card__slug mono">{{ project.slug }}</span>

          <p class="project-card__desc">
            {{ project.description || '还没有描述' }}
          </p>

          <div class="project-card__meta">
            <span>{{ project.requirement_count ?? 0 }} 个需求</span>
            <span>更新于 {{ formatDateTime(project.updated_at) }}</span>
          </div>

          <div class="project-card__footer">
            <el-button type="primary" link @click="openRequirements(project)">进入需求</el-button>
            <div class="page-actions">
              <el-button link @click="openEdit(project)">编辑</el-button>
              <el-button
                v-if="project.status === 'active'"
                link
                type="warning"
                @click="handleArchive(project)"
              >
                归档
              </el-button>
              <el-button link type="danger" @click="handleDelete(project)">删除</el-button>
            </div>
          </div>
        </el-card>
      </div>
    </div>

    <div v-if="store.total > store.pageSize" class="page-actions" style="justify-content: center">
      <el-pagination
        layout="prev, pager, next"
        :total="store.total"
        :page-size="store.pageSize"
        :current-page="store.page"
        background
        @current-change="loadProjects"
      />
    </div>

    <ProjectFormDialog
      v-model="dialogVisible"
      :project="editingProject"
      :loading="store.submitting"
      @submit="handleSubmit"
    />
  </div>
</template>
