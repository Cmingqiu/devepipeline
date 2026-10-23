<script setup lang="ts">
import { onMounted, ref } from 'vue'

import {
  ElMessage,
  ElMessageBox,
  type UploadFile,
  type UploadInstance,
} from 'element-plus'

import type { Skill, SkillFile } from '@/api/contexts'
import { useContextStore } from '@/stores/context'
import { formatDateTime } from '@/utils/datetime'
import { getErrorMessage } from '@/utils/feedback'

const MAX_SKILL_SIZE = 20 * 1024 * 1024

const props = defineProps<{
  projectId: number
}>()

const store = useContextStore()

const uploadRef = ref<UploadInstance>()
const pendingFile = ref<File | null>(null)
const drawerVisible = ref(false)
const activeSkill = ref<Skill | null>(null)
const previewFile = ref<SkillFile | null>(null)
const previewContent = ref('')
const deletingId = ref<number | null>(null)

onMounted(() => {
  loadSkills()
})

function loadSkills(): void {
  store.fetchSkills(props.projectId).catch((err) => {
    ElMessage.error(getErrorMessage(err, '加载技能列表失败'))
  })
}

function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) {
    return '-'
  }
  if (bytes < 1024) {
    return `${bytes} B`
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

function resetPendingFile(): void {
  pendingFile.value = null
  uploadRef.value?.clearFiles()
}

function handleFileChange(file: UploadFile): void {
  const raw = file.raw
  if (!raw) {
    return
  }
  if (!/\.zip$/i.test(raw.name)) {
    ElMessage.error('技能包只支持 .zip 文件')
    resetPendingFile()
    return
  }
  if (raw.size > MAX_SKILL_SIZE) {
    ElMessage.error('技能包大小不能超过 20MB')
    resetPendingFile()
    return
  }
  pendingFile.value = raw
}

function handleFileRemove(): void {
  pendingFile.value = null
}

function handleExceed(): void {
  ElMessage.warning('一次只能上传一个技能包')
}

async function submitUpload(): Promise<void> {
  const file = pendingFile.value
  if (!file) {
    return
  }

  try {
    const skill = await store.uploadSkill(props.projectId, file)
    resetPendingFile()
    ElMessage.success(`技能「${skill.name}」已上传，同名技能会被覆盖`)
    if (drawerVisible.value && activeSkill.value?.name === skill.name) {
      await openSkill(skill)
    }
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '上传技能包失败'))
  }
}

async function openSkill(skill: Skill): Promise<void> {
  drawerVisible.value = true
  activeSkill.value = skill
  previewFile.value = null
  previewContent.value = ''
  store.clearSkillDetail()
  try {
    await store.loadSkill(props.projectId, skill.id)
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '加载技能详情失败'))
  }
}

async function preview(file: SkillFile): Promise<void> {
  if (!file.is_text || !activeSkill.value) {
    return
  }

  previewFile.value = file
  previewContent.value = ''
  try {
    const data = await store.loadSkillFile(props.projectId, activeSkill.value.id, file.path)
    previewContent.value = data.content
  } catch (err) {
    previewFile.value = null
    ElMessage.error(getErrorMessage(err, '加载文件内容失败'))
  }
}

function handleRowClick(row: SkillFile): void {
  if (row.is_text) {
    preview(row)
  }
}

function closePreview(): void {
  previewFile.value = null
  previewContent.value = ''
}

async function removeSkill(skill: Skill): Promise<void> {
  const confirmed = await ElMessageBox.confirm(
    `删除后该技能的全部文件会被移除，确定删除「${skill.name}」？`,
    '删除技能',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  )
    .then(() => true)
    .catch(() => false)
  if (!confirmed) {
    return
  }

  deletingId.value = skill.id
  try {
    await store.removeSkill(props.projectId, skill.id)
    if (activeSkill.value?.id === skill.id) {
      drawerVisible.value = false
    }
    ElMessage.success('技能已删除')
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '删除技能失败'))
  } finally {
    deletingId.value = null
  }
}
</script>

<template>
  <section class="surface">
    <header class="section-head">
      <div class="page-head__text">
        <h2 class="section-title">Skills</h2>
        <p class="page-subtitle">
          上传 .zip 技能包（≤ 20MB，需包含 SKILL.md）；同名技能会整体覆盖。
        </p>
      </div>
      <div class="page-actions">
        <el-upload
          ref="uploadRef"
          :auto-upload="false"
          :show-file-list="true"
          :limit="1"
          accept=".zip,application/zip"
          :on-change="handleFileChange"
          :on-remove="handleFileRemove"
          :on-exceed="handleExceed"
        >
          <el-button>选择 .zip 技能包</el-button>
        </el-upload>
        <el-button
          type="primary"
          :disabled="!pendingFile"
          :loading="store.skillUploading"
          @click="submitUpload"
        >
          上传技能包
        </el-button>
      </div>
    </header>

    <div v-loading="store.skillsLoading" class="skill-grid-wrap">
      <el-empty v-if="store.skillIsEmpty" description="还没有上传技能包">
        <span class="upload-row__hint">
          技能包是可以被流水线复用的操作说明与脚本集合。
        </span>
      </el-empty>

      <div v-else class="skill-grid">
        <el-card
          v-for="skill in store.skills"
          :key="skill.id"
          class="skill-card"
          shadow="never"
          @click="openSkill(skill)"
        >
          <div class="skill-card__head">
            <h3 class="skill-card__name">{{ skill.name }}</h3>
            <el-tag size="small" :type="skill.enabled ? 'success' : 'info'" effect="plain">
              {{ skill.enabled ? '启用' : '停用' }}
            </el-tag>
          </div>

          <p class="skill-card__desc">{{ skill.description || '没有描述' }}</p>

          <div class="skill-card__meta">
            <span>{{ skill.file_count }} 个文件 · 更新于 {{ formatDateTime(skill.updated_at) }}</span>
            <el-button
              link
              type="danger"
              :loading="deletingId === skill.id"
              @click.stop="removeSkill(skill)"
            >
              删除
            </el-button>
          </div>
        </el-card>
      </div>
    </div>

    <el-drawer
      v-model="drawerVisible"
      :title="activeSkill?.name ?? '技能详情'"
      direction="rtl"
      size="640px"
    >
      <div v-loading="store.skillDetailLoading" class="skill-detail">
        <p class="page-subtitle">{{ activeSkill?.description || '没有描述' }}</p>

        <div class="detail-meta">
          <span class="mono">{{ activeSkill?.entry_path }}</span>
          <span>{{ store.skillDetail?.files.length ?? 0 }} 个文件</span>
          <span v-if="store.skillDetail">更新于 {{ formatDateTime(store.skillDetail.updated_at) }}</span>
        </div>

        <el-table
          :data="store.skillDetail?.files ?? []"
          size="small"
          class="skill-file-table"
          @row-click="handleRowClick"
        >
          <el-table-column label="文件" min-width="240">
            <template #default="{ row }">
              <span class="mono">{{ row.path }}</span>
            </template>
          </el-table-column>

          <el-table-column label="大小" width="96">
            <template #default="{ row }">
              <span class="muted">{{ formatFileSize(row.size_bytes) }}</span>
            </template>
          </el-table-column>

          <el-table-column label="类型" width="82">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_text ? 'primary' : 'info'" effect="plain">
                {{ row.is_text ? '文本' : '二进制' }}
              </el-tag>
            </template>
          </el-table-column>

          <el-table-column label="操作" width="86">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                :disabled="!row.is_text"
                @click.stop="preview(row)"
              >
                预览
              </el-button>
            </template>
          </el-table-column>

          <template #empty>
            <el-empty description="技能包内没有文件" :image-size="72" />
          </template>
        </el-table>

        <div v-if="previewFile" class="skill-preview">
          <div class="section-head">
            <h3 class="section-title mono">{{ previewFile.path }}</h3>
            <el-button link @click="closePreview">关闭预览</el-button>
          </div>
          <pre v-loading="store.skillFileLoading" class="skill-preview__code">{{ previewContent }}</pre>
        </div>
      </div>
    </el-drawer>
  </section>
</template>
