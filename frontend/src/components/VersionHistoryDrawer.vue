<script setup lang="ts">
import { ref, watch } from 'vue'

import { ElMessage } from 'element-plus'
import { MdPreview } from 'md-editor-v3'

import type { RequirementVersion, RequirementVersionDetail } from '@/api/types'
import { useRequirementStore } from '@/stores/requirement'
import { formatDateTime } from '@/utils/datetime'
import { getErrorMessage } from '@/utils/feedback'
import { versionSourceMeta } from '@/utils/status'

const visible = defineModel<boolean>({ required: true })

const props = withDefaults(
  defineProps<{
    requirementId: number
    versions: RequirementVersion[]
    loading?: boolean
    currentVersionNo?: number
  }>(),
  {
    loading: false,
    currentVersionNo: 0,
  },
)

const emit = defineEmits<{
  (e: 'restore', content: string): void
}>()

const store = useRequirementStore()
const preview = ref<RequirementVersionDetail | null>(null)
const previewLoading = ref(false)
const activeVersionNo = ref<number | null>(null)

watch(visible, (open) => {
  if (!open) {
    preview.value = null
    activeVersionNo.value = null
  }
})

async function selectVersion(version: RequirementVersion): Promise<void> {
  if (previewLoading.value) {
    return
  }
  activeVersionNo.value = version.version_no
  previewLoading.value = true
  try {
    preview.value = await store.loadVersion(props.requirementId, version.version_no)
  } catch (err) {
    activeVersionNo.value = null
    ElMessage.error(getErrorMessage(err, '加载版本正文失败'))
  } finally {
    previewLoading.value = false
  }
}

function backToList(): void {
  preview.value = null
  activeVersionNo.value = null
}

function restore(): void {
  if (!preview.value) {
    return
  }
  emit('restore', preview.value.content)
  visible.value = false
}
</script>

<template>
  <el-drawer
    v-model="visible"
    title="版本历史"
    direction="rtl"
    size="560px"
    :destroy-on-close="false"
  >
    <div v-if="preview" class="version-preview">
      <div class="version-preview__head">
        <el-button link type="primary" @click="backToList">← 返回版本列表</el-button>
        <el-button
          type="primary"
          size="small"
          :disabled="preview.version_no === currentVersionNo"
          @click="restore"
        >
          以该版本为基础继续编辑
        </el-button>
      </div>

      <div class="detail-meta">
        <el-tag size="small" type="primary" effect="plain">v{{ preview.version_no }}</el-tag>
        <el-tag size="small" :type="versionSourceMeta(preview.source).type" effect="plain">
          {{ versionSourceMeta(preview.source).label }}
        </el-tag>
        <span v-if="preview.note">备注：{{ preview.note }}</span>
        <span>{{ formatDateTime(preview.created_at) }}</span>
      </div>

      <div class="version-preview__body">
        <MdPreview
          :id="`version-preview-${preview.version_no}`"
          :model-value="preview.content"
          language="zh-CN"
        />
      </div>
    </div>

    <div v-else v-loading="loading || previewLoading" class="version-list">
      <p class="page-subtitle">
        当前版本 v{{ currentVersionNo }}，共 {{ versions.length }} 个版本；点击查看该版本正文。
      </p>

      <el-empty v-if="!loading && versions.length === 0" description="还没有版本记录" />

      <button
        v-for="version in versions"
        :key="version.id"
        type="button"
        class="version-item"
        :class="{ 'is-current': version.version_no === currentVersionNo }"
        @click="selectVersion(version)"
      >
        <span class="version-item__main">
          <el-tag size="small" type="primary" effect="plain">v{{ version.version_no }}</el-tag>
          <el-tag size="small" :type="versionSourceMeta(version.source).type" effect="plain">
            {{ versionSourceMeta(version.source).label }}
          </el-tag>
          <span v-if="version.note" class="version-item__note">{{ version.note }}</span>
        </span>
        <span class="version-item__time">{{ formatDateTime(version.created_at) }}</span>
      </button>
    </div>
  </el-drawer>
</template>
