<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { ElMessage } from 'element-plus'
import { MdEditor } from 'md-editor-v3'

import { useContextStore } from '@/stores/context'
import { formatDateTime } from '@/utils/datetime'
import { getErrorMessage } from '@/utils/feedback'

const props = defineProps<{
  projectId: number
}>()

const store = useContextStore()

const content = ref('')
const baseline = ref('')
const loaded = ref(false)
/** 未配置时点「新建」进入编辑态，保存后由后端生成 v1 */
const creating = ref(false)

const showEditor = computed(() => store.agentDoc !== null || creating.value)
const hasUnsavedChanges = computed(
  () => loaded.value && content.value !== baseline.value,
)

onMounted(() => {
  load()
})

async function load(): Promise<void> {
  loaded.value = false
  try {
    const doc = await store.fetchAgentDoc(props.projectId)
    content.value = doc?.content ?? ''
    baseline.value = content.value
    creating.value = false
    await store.fetchAgentVersions(props.projectId).catch(() => undefined)
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '加载 AGENTS.md 失败'))
  } finally {
    loaded.value = true
  }
}

function startNew(): void {
  creating.value = true
  content.value = ''
  baseline.value = ''
}

async function save(): Promise<void> {
  if (!content.value.trim()) {
    ElMessage.warning('AGENTS.md 内容不能为空')
    return
  }

  try {
    const doc = await store.saveAgentDoc(props.projectId, content.value)
    baseline.value = content.value
    creating.value = false
    ElMessage.success(`AGENTS.md 已保存为 v${doc.version}`)
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '保存 AGENTS.md 失败'))
  }
}
</script>

<template>
  <section class="surface">
    <header class="section-head">
      <div class="page-head__text">
        <h2 class="section-title">AGENTS.md</h2>
        <p class="page-subtitle">
          项目级协作说明；相同内容不会产生新版本，版本历史只保留元信息。
        </p>
      </div>
      <div class="page-actions">
        <el-button
          v-if="showEditor"
          type="primary"
          :loading="store.agentSaving"
          :disabled="!hasUnsavedChanges"
          @click="save"
        >
          保存
        </el-button>
        <el-button v-else type="primary" @click="startNew">新建</el-button>
      </div>
    </header>

    <div v-loading="!loaded" class="settings-layout">
      <div class="settings-main">
        <template v-if="showEditor">
          <div class="detail-meta">
            <template v-if="store.agentDoc">
              <el-tag size="small" type="primary" effect="plain">
                v{{ store.agentDoc.version }}
              </el-tag>
              <el-tag v-if="store.agentDoc.is_active" size="small" type="success" effect="plain">
                生效中
              </el-tag>
              <span>更新于 {{ formatDateTime(store.agentDoc.created_at) }}</span>
            </template>
            <span v-else class="muted">尚未配置，保存后生成 v1</span>
            <span v-if="hasUnsavedChanges" class="unsaved-hint">● 有未保存的修改</span>
          </div>

          <div class="editor-frame">
            <MdEditor v-model="content" language="zh-CN" :style="{ height: '520px' }" />
          </div>
        </template>

        <el-empty v-else description="还没有配置 AGENTS.md">
          <el-button type="primary" @click="startNew">新建 AGENTS.md</el-button>
          <p class="upload-row__hint">说明项目的背景、约定与禁区，供流水线各阶段读取。</p>
        </el-empty>
      </div>

      <aside class="settings-side">
        <div class="settings-side__head">
          <h3 class="section-title">版本历史</h3>
          <span class="muted">{{ store.agentVersions.length }} 个版本</span>
        </div>

        <div v-loading="store.agentVersionsLoading" class="settings-list">
          <el-empty
            v-if="!store.agentVersionsLoading && store.agentVersions.length === 0"
            description="还没有版本记录"
            :image-size="72"
          />

          <div
            v-for="version in store.agentVersions"
            :key="version.id"
            class="settings-version-item"
            :class="{ 'is-active': version.is_active }"
          >
            <span class="settings-version-item__main">
              <el-tag size="small" type="primary" effect="plain">v{{ version.version }}</el-tag>
              <el-tag size="small" :type="version.is_active ? 'success' : 'info'" effect="plain">
                {{ version.is_active ? '生效' : '历史' }}
              </el-tag>
            </span>
            <span class="version-item__time">{{ formatDateTime(version.created_at) }}</span>
          </div>
        </div>

        <p class="page-subtitle">历史版本接口不返回正文，仅展示版本号与时间。</p>
      </aside>
    </div>
  </section>
</template>
