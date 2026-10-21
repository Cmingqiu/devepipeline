<script setup lang="ts">
import { computed, ref } from 'vue'

import { ElMessage } from 'element-plus'
import { MdPreview } from 'md-editor-v3'

import type { Artifact } from '@/api/types'
import { useRunStore } from '@/stores/run'
import { formatDateTime } from '@/utils/datetime'
import { getErrorMessage } from '@/utils/feedback'
import { artifactKindMeta } from '@/utils/status'
import { PIPELINE_STAGES, stageLabel } from '@/utils/stage'

const store = useRunStore()

const editing = ref(false)
const draft = ref('')

const grouped = computed(() =>
  PIPELINE_STAGES.map((stage) => ({
    stage: stage.key,
    label: stage.label,
    items: store.artifacts.filter((artifact) => artifact.stage === stage.key),
  })).filter((group) => group.items.length > 0),
)

const selected = computed(() => store.selectedArtifact)

async function openArtifact(artifact: Artifact): Promise<void> {
  editing.value = false
  try {
    await store.loadArtifact(artifact.id)
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '加载产物正文失败'))
  }
}

function startEdit(): void {
  if (!selected.value) {
    return
  }
  draft.value = selected.value.content
  editing.value = true
}

async function save(): Promise<void> {
  const current = selected.value
  if (!current) {
    return
  }
  try {
    await store.saveArtifact(current.id, draft.value)
    editing.value = false
    ElMessage.success('已保存为新版本产物')
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '保存产物失败'))
  }
}
</script>

<template>
  <section class="surface">
    <header class="section-head">
      <h2 class="section-title">产物</h2>
      <span class="muted">{{ store.artifactsTotal }} 个，按阶段分组</span>
    </header>

    <div v-loading="store.artifactsLoading" class="artifact-layout">
      <aside class="artifact-list">
        <el-empty
          v-if="!store.artifactsLoading && grouped.length === 0"
          description="还没有产物"
        />

        <div v-for="group in grouped" :key="group.stage" class="artifact-group">
          <div class="artifact-group__title">{{ group.label }}</div>

          <button
            v-for="artifact in group.items"
            :key="artifact.id"
            type="button"
            class="artifact-item"
            :class="{ 'is-active': selected?.id === artifact.id }"
            @click="openArtifact(artifact)"
          >
            <span class="artifact-item__main">
              <el-tag size="small" type="primary" effect="plain">v{{ artifact.version }}</el-tag>
              <el-tag
                size="small"
                :type="artifactKindMeta(artifact.kind).type"
                effect="plain"
              >
                {{ artifactKindMeta(artifact.kind).label }}
              </el-tag>
            </span>
            <span class="artifact-item__summary">{{ artifact.summary || '（没有摘要）' }}</span>
            <span class="artifact-item__meta">
              <span v-if="artifact.edited_by_human">人工编辑 · </span>
              {{ formatDateTime(artifact.created_at) }}
            </span>
          </button>
        </div>
      </aside>

      <div v-loading="store.artifactLoading" class="artifact-viewer">
        <template v-if="selected">
          <div class="artifact-viewer__head">
            <div class="detail-meta">
              <el-tag size="small" effect="plain">{{ stageLabel(selected.stage) }}</el-tag>
              <el-tag size="small" type="primary" effect="plain">v{{ selected.version }}</el-tag>
              <el-tag
                size="small"
                :type="artifactKindMeta(selected.kind).type"
                effect="plain"
              >
                {{ artifactKindMeta(selected.kind).label }}
              </el-tag>
              <span v-if="selected.edited_by_human" class="muted">人工编辑</span>
              <span class="muted">{{ formatDateTime(selected.created_at) }}</span>
            </div>
            <div class="page-actions">
              <el-button v-if="!editing" size="small" @click="startEdit">
                编辑并保存为新版本
              </el-button>
            </div>
          </div>

          <div v-if="editing" class="artifact-editor">
            <el-input v-model="draft" type="textarea" :rows="18" class="artifact-textarea" />
            <div class="page-actions">
              <el-button size="small" @click="editing = false">取消</el-button>
              <el-button
                size="small"
                type="primary"
                :loading="store.artifactSaving"
                @click="save"
              >
                保存新版本
              </el-button>
            </div>
          </div>

          <div v-else-if="selected.kind === 'diff'" class="artifact-diff">
            <pre>{{ selected.content }}</pre>
          </div>

          <div v-else class="artifact-markdown">
            <MdPreview
              :id="`artifact-preview-${selected.id}`"
              :model-value="selected.content"
              language="zh-CN"
            />
          </div>
        </template>

        <el-empty v-else description="从左侧选择一个产物查看正文" />
      </div>
    </div>
  </section>
</template>
