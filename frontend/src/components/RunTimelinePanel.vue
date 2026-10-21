<script setup lang="ts">
import { computed } from 'vue'

import type { RunEvent } from '@/api/types'
import {
  eventStageLabel,
  eventTone,
  eventTypeLabel,
  formatEventSummary,
  formatEventTime,
} from '@/utils/events'

const props = withDefaults(
  defineProps<{
    events: RunEvent[]
    connected?: boolean
  }>(),
  {
    connected: false,
  },
)

const MAX_RENDERED = 300

const visibleEvents = computed(() =>
  [...props.events].slice(-MAX_RENDERED).reverse(),
)

const countText = computed(() => {
  const parts = [`${props.events.length} 条`]
  if (props.events.length > MAX_RENDERED) {
    parts.push(`仅显示最近 ${MAX_RENDERED} 条`)
  }
  if (props.connected) {
    parts.push('实时')
  }
  return parts.join(' · ')
})
</script>

<template>
  <section class="surface timeline-panel">
    <header class="section-head">
      <h2 class="section-title">时间线</h2>
      <span class="muted">{{ countText }}</span>
    </header>

    <div class="timeline-list">
      <el-empty v-if="events.length === 0" description="还没有事件" />

      <div
        v-for="event in visibleEvents"
        :key="`${event.seq}-${event.type}`"
        class="timeline-item"
        :class="`timeline-item--${eventTone(event.type)}`"
      >
        <span class="timeline-item__time mono">{{ formatEventTime(event.ts) }}</span>
        <span class="timeline-item__type">{{ eventTypeLabel(event.type) }}</span>
        <span class="timeline-item__stage">{{ eventStageLabel(event) }}</span>
        <span class="timeline-item__summary">
          {{ formatEventSummary(event.type, event.payload) }}
        </span>
      </div>
    </div>
  </section>
</template>
