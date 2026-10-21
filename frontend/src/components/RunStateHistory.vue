<script setup lang="ts">
import type { RunState } from '@/api/types'
import { formatDateTime } from '@/utils/datetime'
import { stageLabel } from '@/utils/stage'

withDefaults(
  defineProps<{
    states: RunState[]
    loading?: boolean
  }>(),
  {
    loading: false,
  },
)

function shortId(value: string): string {
  return value ? value.slice(0, 8) : '-'
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
        </div>
        <div class="state-item__meta">
          <span v-if="state.next && state.next.length">next: {{ state.next.join(', ') }}</span>
          <span>{{ formatDateTime(state.created_at) }}</span>
        </div>
        <p v-if="state.error" class="state-item__error">{{ state.error }}</p>
      </div>
    </div>
  </section>
</template>
