<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { ElMessage, ElMessageBox, type UploadFile, type UploadInstance } from 'element-plus'
import { MdEditor } from 'md-editor-v3'
import { RouterLink, onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'

import { getProject } from '@/api/projects'
import { createRun } from '@/api/runs'
import VersionHistoryDrawer from '@/components/VersionHistoryDrawer.vue'
import { useRequirementStore } from '@/stores/requirement'
import { formatDateTime } from '@/utils/datetime'
import { getErrorMessage, isConflict } from '@/utils/feedback'
import { requirementStatusMeta } from '@/utils/status'

const MAX_UPLOAD_SIZE = 2 * 1024 * 1024

const route = useRoute()
const router = useRouter()
const store = useRequirementStore()

const requirementId = computed(() => Number(route.params.requirementId))
const projectName = ref('')

const titleDraft = ref('')
const titleSaving = ref(false)

const editorContent = ref('')
const baselineContent = ref('')
const contentLoaded = ref(false)
const note = ref('')

const drawerVisible = ref(false)
const uploadRef = ref<UploadInstance>()
const pendingFile = ref<File | null>(null)
const startingRun = ref(false)
/** 启动流水线跳转前已确认过未保存修改，避免离开守卫二次弹窗 */
const leaveGuardBypassed = ref(false)

const hasUnsavedChanges = computed(
  () => contentLoaded.value && editorContent.value !== baselineContent.value,
)

const titleChanged = computed(() => {
  const detail = store.detail
  if (!detail) {
    return false
  }
  const title = titleDraft.value.trim()
  return Boolean(title) && title !== detail.title
})

onMounted(() => {
  loadRequirement()
})

watch(requirementId, (next, previous) => {
  if (next !== previous) {
    loadRequirement()
  }
})

async function loadRequirement(): Promise<void> {
  if (!Number.isFinite(requirementId.value) || requirementId.value <= 0) {
    return
  }

  store.resetDetail()
  contentLoaded.value = false
  leaveGuardBypassed.value = false
  try {
    const data = await store.fetchDetail(requirementId.value)
    titleDraft.value = data.title
    editorContent.value = data.content ?? ''
    baselineContent.value = editorContent.value
    contentLoaded.value = true
    note.value = ''
    loadProjectName(data.project_id)
    await store.fetchVersions(requirementId.value).catch(() => undefined)
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '加载需求详情失败'))
  }
}

function loadProjectName(projectId: number): void {
  getProject(projectId)
    .then((project) => {
      projectName.value = project.name
    })
    .catch(() => {
      projectName.value = ''
    })
}

async function saveTitle(): Promise<void> {
  const detail = store.detail
  if (!detail || titleSaving.value) {
    return
  }

  const title = titleDraft.value.trim()
  if (!title) {
    ElMessage.warning('标题不能为空')
    titleDraft.value = detail.title
    return
  }
  if (title === detail.title) {
    return
  }

  titleSaving.value = true
  try {
    await store.updateTitle(requirementId.value, title)
    titleDraft.value = title
    ElMessage.success('标题已更新')
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '更新标题失败'))
  } finally {
    titleSaving.value = false
  }
}

async function saveVersion(): Promise<void> {
  if (!store.detail) {
    return
  }
  if (!editorContent.value.trim()) {
    ElMessage.warning('正文不能为空')
    return
  }

  try {
    const created = await store.saveVersion(requirementId.value, {
      content: editorContent.value,
      note: note.value.trim() || undefined,
    })
    baselineContent.value = editorContent.value
    note.value = ''
    ElMessage.success(`已保存为 v${created.version_no}`)
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '保存新版本失败'))
  }
}

function openDrawer(): void {
  drawerVisible.value = true
  store.fetchVersions(requirementId.value).catch((err) => {
    ElMessage.error(getErrorMessage(err, '加载版本历史失败'))
  })
}

async function handleRestore(content: string): Promise<void> {
  if (hasUnsavedChanges.value) {
    const confirmed = await ElMessageBox.confirm(
      '当前编辑器里有未保存的修改，使用该版本正文会覆盖它们。继续？',
      '覆盖未保存的修改',
      { type: 'warning', confirmButtonText: '覆盖', cancelButtonText: '取消' },
    )
      .then(() => true)
      .catch(() => false)
    if (!confirmed) {
      return
    }
  }

  editorContent.value = content
  ElMessage.success('已填入编辑器，保存为新版本后才会生效')
}

function handleFileChange(file: UploadFile): void {
  const raw = file.raw
  if (!raw) {
    return
  }
  if (!/\.md$/i.test(raw.name)) {
    ElMessage.error('只支持 .md 文件')
    uploadRef.value?.clearFiles()
    pendingFile.value = null
    return
  }
  if (raw.size > MAX_UPLOAD_SIZE) {
    ElMessage.error('文件大小不能超过 2MB')
    uploadRef.value?.clearFiles()
    pendingFile.value = null
    return
  }
  pendingFile.value = raw
}

function handleFileRemove(): void {
  pendingFile.value = null
}

function handleExceed(): void {
  ElMessage.warning('一次只能上传一个文件')
}

async function submitUpload(): Promise<void> {
  const file = pendingFile.value
  if (!file) {
    return
  }

  try {
    const created = await store.uploadVersion(
      requirementId.value,
      file,
      note.value.trim() || undefined,
    )
    editorContent.value = created.content
    baselineContent.value = created.content
    pendingFile.value = null
    note.value = ''
    uploadRef.value?.clearFiles()
    ElMessage.success(`已上传为 v${created.version_no}`)
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '上传版本失败'))
  }
}

async function startPipeline(): Promise<void> {
  const detail = store.detail
  if (!detail) {
    return
  }

  if (hasUnsavedChanges.value) {
    const confirmed = await ElMessageBox.confirm(
      `正文有未保存的修改，本次运行将使用已保存的 v${detail.current_version_no}。继续？`,
      '未保存的修改',
      { type: 'warning', confirmButtonText: '继续启动', cancelButtonText: '先保存' },
    )
      .then(() => true)
      .catch(() => false)
    if (!confirmed) {
      return
    }
  }

  startingRun.value = true
  try {
    const run = await createRun(detail.id, { version_no: detail.current_version_no })
    leaveGuardBypassed.value = true
    ElMessage.success(`已启动运行 #${run.id}`)
    router.push({ name: 'run-detail', params: { runId: run.id } })
  } catch (err) {
    if (isConflict(err)) {
      ElMessage.warning('该需求已有活跃运行，请先等待或取消')
      return
    }
    ElMessage.error(getErrorMessage(err, '启动流水线失败'))
  } finally {
    startingRun.value = false
  }
}

onBeforeRouteLeave(async () => {
  if (leaveGuardBypassed.value || !hasUnsavedChanges.value) {
    return true
  }

  return ElMessageBox.confirm(
    '正文有未保存的修改，离开后修改会丢失。确定离开？',
    '未保存的修改',
    { type: 'warning', confirmButtonText: '离开', cancelButtonText: '留下' },
  )
    .then(() => true)
    .catch(() => false)
})
</script>

<template>
  <div v-loading="store.detailLoading" class="page">
    <el-breadcrumb class="crumbs" separator="/">
      <el-breadcrumb-item :to="{ path: '/projects' }">项目</el-breadcrumb-item>
      <el-breadcrumb-item
        v-if="store.detail"
        :to="{ name: 'requirements', params: { projectId: store.detail.project_id } }"
      >
        {{ projectName || `项目 #${store.detail.project_id}` }}
      </el-breadcrumb-item>
      <el-breadcrumb-item>需求详情</el-breadcrumb-item>
    </el-breadcrumb>

    <template v-if="store.detail">
      <section class="surface">
        <div class="detail-toolbar">
          <el-input
            v-model="titleDraft"
            class="detail-title-input"
            maxlength="200"
            placeholder="需求标题"
            @blur="saveTitle"
            @keyup.enter="saveTitle"
          />

          <div class="page-actions">
            <el-button :loading="titleSaving" :disabled="!titleChanged" @click="saveTitle">
              保存标题
            </el-button>
            <el-button @click="openDrawer">版本历史</el-button>
            <el-button type="primary" :loading="startingRun" @click="startPipeline">
              启动流水线
            </el-button>
          </div>
        </div>

        <div class="detail-meta">
          <el-tag size="small" effect="plain" :type="requirementStatusMeta(store.detail.status).type">
            {{ requirementStatusMeta(store.detail.status).label }}
          </el-tag>
          <span>当前版本 v{{ store.detail.current_version_no }}</span>
          <span>更新于 {{ formatDateTime(store.detail.updated_at) }}</span>
          <RouterLink
            v-if="store.detail.latest_run_id"
            :to="{ name: 'run-detail', params: { runId: store.detail.latest_run_id } }"
          >
            最近运行 #{{ store.detail.latest_run_id }}
          </RouterLink>
        </div>
      </section>

      <section class="surface">
        <div class="editor-toolbar">
          <div class="editor-actions">
            <el-input
              v-model="note"
              placeholder="版本备注（可选）"
              maxlength="200"
              style="width: 260px"
            />
            <el-button type="primary" :loading="store.saving" @click="saveVersion">
              保存为新版本
            </el-button>
            <span v-if="hasUnsavedChanges" class="unsaved-hint">● 有未保存的修改</span>
          </div>

          <div class="upload-row">
            <el-upload
              ref="uploadRef"
              :auto-upload="false"
              :show-file-list="true"
              :limit="1"
              accept=".md,text/markdown"
              :on-change="handleFileChange"
              :on-remove="handleFileRemove"
              :on-exceed="handleExceed"
            >
              <el-button>选择 .md 文件</el-button>
            </el-upload>
            <el-button :disabled="!pendingFile" :loading="store.uploading" @click="submitUpload">
              上传为新版本
            </el-button>
          </div>
        </div>

        <p class="upload-row__hint">
          仅支持 .md，≤ 2MB；上传成功后正文以文件内容为准，并生成新版本。
        </p>

        <div class="editor-frame">
          <MdEditor v-model="editorContent" language="zh-CN" :style="{ height: '560px' }" />
        </div>
      </section>

      <VersionHistoryDrawer
        v-model="drawerVisible"
        :requirement-id="store.detail.id"
        :versions="store.versions"
        :loading="store.versionsLoading"
        :current-version-no="store.detail.current_version_no"
        @restore="handleRestore"
      />
    </template>

    <div v-else-if="!store.detailLoading" class="surface">
      <el-empty description="需求不存在或加载失败">
        <el-button @click="router.push('/projects')">返回项目列表</el-button>
      </el-empty>
    </div>
  </div>
</template>
