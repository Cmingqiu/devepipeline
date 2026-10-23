<script setup lang="ts">
import { ref } from 'vue'

import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

import type { RunStage, RunState } from '@/api/types'
import { useRunStore } from '@/stores/run'
import { formatDateTime } from '@/utils/datetime'
import { getErrorMessage } from '@/utils/feedback'
import { PIPELINE_STAGES, isRunStage, stageLabel } from '@/utils/stage'

const props = withDefaults(
  defineProps<{
    states: RunState[]
    runId: number
    loading?: boolean
  }>(),
  {
    loading: false,
  },
)

const router = useRouter()
const store = useRunStore()

const forkVisible = ref(false)
const forkState = ref<RunState | null>(null)
const forkStage = ref<RunStage>('analysis')

function shortId(value: string): string {
  return value ? value.slice(0, 8) : '-'
}

function openFork(state: RunState): void {
  forkState.value = state
  // 默认从这条 checkpoint 所在阶段重新执行
  forkStage.value = isRunStage(state.stage) ? state.stage : 'analysis'
  forkVisible.value = true
}

async function submitFork(): Promise<void> {
  const state = forkState.value
  if (!state) {
    return
  }
  try {
    const run = await store.fork(props.runId, {
      checkpoint_id: state.checkpoint_id,
      from_stage: forkStage.value,
    })
    forkVisible.value = false
    ElMessage.success(`已创建新运行 #${run.id}`)
    await router.push(`/runs/${run.id}`)
  } catch (err) {
    ElMessage.error(getErrorMessage(err, 'fork 运行失败'))
  }
}
</script>

<template>
  <section class="surface">
    <header class="section-head">
      <h2 class="section-title">状态历史</h2>
      <span class="muted">{{ states.length }} 个 checkpoint</span>
    </header>

    <div v-loading="loading" class="state-list">
      <el-empty v-if="!loading && states.length === 0" description="还没有 checkpoint" />

      <div v-for="state in states" :key="state.checkpoint_id" class="state-item">
        <div class="state-item__main">
          <span class="mono">{{ shortId(state.checkpoint_id) }}</span>
          <el-tag v-if="state.stage" size="small" effect="plain">
            {{ stageLabel(state.stage) }}
          </el-tag>
          <el-tag v-if="state.has_interrupt" size="small" type="warning" effect="plain">
            interrupt
          </el-tag>
          <el-button
            class="state-item__fork"
            size="small"
            plain
            :loading="store.forking && forkState?.checkpoint_id === state.checkpoint_id"
            :disabled="store.forking"
            @click="openFork(state)"
          >
            从此处 fork
          </el-button>
        </div>
        <div class="state-item__meta">
          <span v-if="state.next && state.next.length">next: {{ state.next.join(', ') }}</span>
          <span>{{ formatDateTime(state.created_at) }}</span>
        </div>
        <p v-if="state.error" class="state-item__error">{{ state.error }}</p>
      </div>
    </div>

    <el-dialog v-model="forkVisible" title="从 checkpoint 分叉" width="420px">
      <p class="muted state-fork__checkpoint">
        checkpoint {{ shortId(forkState?.checkpoint_id ?? '') }}
      </p>
      <el-radio-group v-model="forkStage" class="state-fork__stages">
        <el-radio-button
          v-for="stage in PIPELINE_STAGES"
          :key="stage.key"
          :value="stage.key"
        >
          {{ stage.label }}
        </el-radio-button>
      </el-radio-group>
      <template #footer>
        <el-button @click="forkVisible = false">取消</el-button>
        <el-button type="primary" :loading="store.forking" @click="submitFork">
          创建新运行
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>
