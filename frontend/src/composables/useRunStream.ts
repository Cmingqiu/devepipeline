import { computed, ref, toValue, type MaybeRefOrGetter, type Ref } from 'vue'

import type { RunEvent, RunEventType } from '@/api/types'

export const RUN_EVENT_TYPES: RunEventType[] = [
  'run_started',
  'stage_started',
  'llm_token',
  'usage',
  'artifact_saved',
  'stage_finished',
  'interrupt',
  'decision',
  'error',
  'run_finished',
]

export const MAX_TIMELINE_EVENTS = 2000

export type StreamConnectionState = 'connecting' | 'open' | 'closed' | 'error'

export interface RunStreamCallbacks {
  onInterrupt?: (event: RunEvent) => void
  onDecision?: (event: RunEvent) => void
  onArtifactSaved?: (event: RunEvent) => void
  onStreamError?: (event: RunEvent) => void
  onRunFinished?: (event: RunEvent) => void
}

export interface UseRunStreamReturn {
  status: Ref<StreamConnectionState>
  connected: Ref<boolean>
  tokensByStage: Ref<Record<string, string>>
  timeline: Ref<RunEvent[]>
  eventCount: Ref<number>
  promptTokens: Ref<number>
  completionTokens: Ref<number>
  currentStage: Ref<string | null>
  start: () => void
  stop: () => void
  clear: () => void
  seedTimeline: (events: RunEvent[]) => void
  setCurrentStage: (stage: string | null) => void
}

/**
 * 订阅运行 SSE 流。
 *
 * 后端 SSE 的 data 是 payload 本身（seq 来自 event.lastEventId，stage 需要从 payload/当前阶段推断），
 * 这里兼容「信封」结构以应对后续协议变化。
 */
export function useRunStream(
  runId: MaybeRefOrGetter<number>,
  callbacks: RunStreamCallbacks = {},
): UseRunStreamReturn {
  const status = ref<StreamConnectionState>('closed')
  const tokensByStage = ref<Record<string, string>>({})
  const timeline = ref<RunEvent[]>([])
  const eventCount = ref(0)
  const promptTokens = ref(0)
  const completionTokens = ref(0)
  const currentStage = ref<string | null>(null)

  const seenSeqs = new Set<number>()
  const handlers = new Map<string, (message: MessageEvent) => void>()
  let source: EventSource | null = null
  let stopped = true

  const connected = computed(() => status.value === 'open')

  function parseMessage(type: RunEventType, message: MessageEvent): RunEvent | null {
    const raw = typeof message.data === 'string' ? message.data : ''
    let data: Record<string, unknown> = {}
    if (raw) {
      try {
        const parsed: unknown = JSON.parse(raw)
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          data = parsed as Record<string, unknown>
        }
      } catch {
        return null
      }
    }

    const envelopePayload =
      data.payload && typeof data.payload === 'object' && !Array.isArray(data.payload)
        ? (data.payload as Record<string, unknown>)
        : null
    const payload = envelopePayload ?? data

    const rawSeq = message.lastEventId ? Number(message.lastEventId) : Number(data.seq)
    const seq = Number.isFinite(rawSeq) ? rawSeq : 0

    const stageValue =
      typeof data.stage === 'string'
        ? data.stage
        : typeof payload.stage === 'string'
          ? payload.stage
          : null

    const tsValue = typeof data.ts === 'string' ? data.ts : new Date().toISOString()

    return { seq, ts: tsValue, stage: stageValue, type, payload }
  }

  function updateState(event: RunEvent): void {
    const payload = event.payload

    switch (event.type) {
      case 'run_started': {
        if (typeof payload.stage === 'string' && payload.stage) {
          currentStage.value = payload.stage
        }
        break
      }
      case 'stage_started': {
        if (typeof payload.stage === 'string' && payload.stage) {
          currentStage.value = payload.stage
          if (tokensByStage.value[payload.stage] === undefined) {
            tokensByStage.value[payload.stage] = ''
          }
        }
        break
      }
      case 'llm_token': {
        const chunk = typeof payload.text === 'string' ? payload.text : ''
        const stage =
          (typeof payload.stage === 'string' && payload.stage) ||
          currentStage.value ||
          'unknown'
        tokensByStage.value[stage] = (tokensByStage.value[stage] ?? '') + chunk
        break
      }
      case 'usage': {
        // 后端 usage 是每阶段的增量，这里按 run 累计
        const prompt = Number(payload.prompt_tokens)
        const completion = Number(payload.completion_tokens)
        if (Number.isFinite(prompt)) {
          promptTokens.value += prompt
        }
        if (Number.isFinite(completion)) {
          completionTokens.value += completion
        }
        break
      }
      case 'interrupt': {
        if (typeof payload.stage === 'string' && payload.stage) {
          currentStage.value = payload.stage
        }
        break
      }
      case 'stage_finished': {
        // 实时流只保留当前阶段的缓冲；阶段完成后清理，避免跨阶段串文本
        const stage =
          (typeof payload.stage === 'string' && payload.stage) || event.stage
        if (stage) {
          delete tokensByStage.value[stage]
        }
        break
      }
      default:
        break
    }
  }

  function applyEvent(event: RunEvent): boolean {
    if (event.seq > 0) {
      if (seenSeqs.has(event.seq)) {
        return false
      }
      seenSeqs.add(event.seq)
    }

    timeline.value.push(event)
    while (timeline.value.length > MAX_TIMELINE_EVENTS) {
      const removed = timeline.value.shift()
      if (removed && removed.seq > 0) {
        seenSeqs.delete(removed.seq)
      }
    }

    updateState(event)
    eventCount.value += 1
    return true
  }

  function handleEvent(type: RunEventType, message: MessageEvent): void {
    if (stopped) {
      return
    }
    const event = parseMessage(type, message)
    if (!event || !applyEvent(event)) {
      return
    }

    switch (type) {
      case 'interrupt':
        callbacks.onInterrupt?.(event)
        break
      case 'decision':
        callbacks.onDecision?.(event)
        break
      case 'artifact_saved':
        callbacks.onArtifactSaved?.(event)
        break
      case 'error':
        callbacks.onStreamError?.(event)
        break
      case 'run_finished':
        callbacks.onRunFinished?.(event)
        stop()
        break
      default:
        break
    }
  }

  function start(): void {
    stop()
    stopped = false

    const id = Number(toValue(runId))
    if (!Number.isFinite(id) || id <= 0) {
      return
    }
    if (typeof EventSource === 'undefined') {
      status.value = 'error'
      return
    }

    const instance = new EventSource(`/api/v1/runs/${id}/stream?last_event_id=0`)
    source = instance
    status.value = 'connecting'

    instance.onopen = () => {
      if (source === instance) {
        status.value = 'open'
      }
    }
    instance.onerror = () => {
      if (source === instance && !stopped) {
        // 浏览器会自行重连；页面据此启动轮询兜底
        status.value = 'error'
      }
    }

    for (const type of RUN_EVENT_TYPES) {
      const handler = (message: MessageEvent) => handleEvent(type, message)
      handlers.set(type, handler)
      instance.addEventListener(type, handler as EventListener)
    }
  }

  function stop(): void {
    stopped = true
    const instance = source
    if (instance) {
      for (const [type, handler] of handlers) {
        instance.removeEventListener(type, handler as EventListener)
      }
      instance.close()
    }
    handlers.clear()
    source = null
    status.value = 'closed'
  }

  function clear(): void {
    timeline.value = []
    tokensByStage.value = {}
    seenSeqs.clear()
    eventCount.value = 0
    promptTokens.value = 0
    completionTokens.value = 0
    currentStage.value = null
  }

  function seedTimeline(events: RunEvent[]): void {
    const sorted = [...events].sort((left, right) => left.seq - right.seq)
    for (const event of sorted) {
      applyEvent(event)
    }
  }

  function setCurrentStage(stage: string | null): void {
    currentStage.value = stage
  }

  return {
    status,
    connected,
    tokensByStage,
    timeline,
    eventCount,
    promptTokens,
    completionTokens,
    currentStage,
    start,
    stop,
    clear,
    seedTimeline,
    setCurrentStage,
  }
}
