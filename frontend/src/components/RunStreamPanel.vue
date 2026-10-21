<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import type { StreamConnectionState } from '@/composables/useRunStream'
import { stageLabel } from '@/utils/stage'

const props = defineProps<{
  stage: string | null
  text: string
  connection: StreamConnectionState
  promptTokens: number
  completionTokens: number
}>()

const outputRef = ref<HTMLElement | null>(null)
const follow = ref(true)
const hasNew = ref(false)

const connectionMeta = computed(() => {
  switch (props.connection) {
    case 'connecting':
      return { label: '连接中', type: 'info' as const }
    case 'open':
      return { label: '实时', type: 'success' as const }
    case 'error':
      return { label: '已断开 · 轮询兜底', type: 'danger' as const }
    default:
      return { label: '已结束', type: 'info' as const }
  }
})

const totalTokens = computed(() => props.promptTokens + props.completionTokens)

watch(
  () => props.text,
  async () => {
    if (!follow.value) {
      hasNew.value = true
      return
    }
    await nextTick()
    scrollToBottom()
  },
  { flush: 'post' },
)

function scrollToBottom(): void {
  const element = outputRef.value
  if (!element) {
    return
  }
  element.scrollTop = element.scrollHeight
}

function handleScroll(): void {
  const element = outputRef.value
  if (!element) {
    return
  }
  const atBottom =
    element.scrollHeight - element.scrollTop - element.clientHeight < 24
  follow.value = atBottom
  if (atBottom) {
    hasNew.value = false
  }
}

function backToLatest(): void {
  follow.value = true
  hasNew.value = false
  scrollToBottom()
}
</script>

<template>
  <section class="surface stream-panel">
    <header class="section-head">
      <h2 class="section-title">
        实时流
        <span v-if="stage" class="stream-panel__stage">· {{ stageLabel(stage) }}</span>
      </h2>
      <div class="stream-panel__meta">
        <el-tag size="small" effect="plain" :type="connectionMeta.type">
          {{ connectionMeta.label }}
        </el-tag>
        <span class="muted">
          {{ totalTokens }} tokens
          <span class="mono">(↓{{ promptTokens }} ↑{{ completionTokens }})</span>
        </span>
      </div>
    </header>

    <div class="stream-output">
      <pre ref="outputRef" class="stream-output__text" @scroll="handleScroll">{{ text }}</pre>
      <p v-if="!text" class="stream-output__empty muted">
        等待当前阶段的 token 输出…
      </p>
      <el-button
        v-if="!follow"
        class="stream-output__latest"
        size="small"
        type="primary"
        @click="backToLatest"
      >
        {{ hasNew ? '有新内容 · 回到最新' : '回到最新' }}
      </el-button>
    </div>
  </section>
</template>
