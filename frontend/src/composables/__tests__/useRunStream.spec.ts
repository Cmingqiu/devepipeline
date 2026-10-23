import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  MAX_TIMELINE_EVENTS,
  RUN_EVENT_TYPES,
  useRunStream,
} from '@/composables/useRunStream'
import type { RunEvent } from '@/api/types'

type Listener = (event: MessageEvent) => void

class FakeEventSource {
  static instances: FakeEventSource[] = []

  readonly url: string
  closed = false
  onopen: ((event: Event) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  readonly listeners = new Map<string, Set<Listener>>()

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: Listener): void {
    const set = this.listeners.get(type) ?? new Set<Listener>()
    set.add(listener)
    this.listeners.set(type, set)
  }

  removeEventListener(type: string, listener: Listener): void {
    this.listeners.get(type)?.delete(listener)
  }

  close(): void {
    this.closed = true
  }

  emit(type: string, payload: unknown, seq = 0): void {
    const event = {
      data: JSON.stringify(payload),
      lastEventId: seq > 0 ? String(seq) : '',
      type,
    } as MessageEvent
    this.listeners.get(type)?.forEach((listener) => listener(event))
  }

  notifyOpen(): void {
    this.onopen?.(new Event('open'))
  }

  notifyError(): void {
    this.onerror?.(new Event('error'))
  }
}

const T = '2026-10-21T06:00:00.000Z'

function makeEvent(overrides: Partial<RunEvent> = {}): RunEvent {
  return {
    seq: 1,
    ts: T,
    stage: 'analysis',
    type: 'stage_started',
    payload: { stage: 'analysis' },
    ...overrides,
  }
}

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('composables/useRunStream', () => {
  it('建连时注册全部事件监听，并按阶段拼接 llm_token', () => {
    const stream = useRunStream(() => 7)
    stream.start()

    const source = FakeEventSource.instances[0]
    expect(source).toBeTruthy()
    expect(source!.url).toBe('/api/v1/runs/7/stream?last_event_id=0')
    for (const type of RUN_EVENT_TYPES) {
      expect(source!.listeners.has(type)).toBe(true)
    }

    source!.notifyOpen()
    expect(stream.status.value).toBe('open')
    expect(stream.connected.value).toBe(true)

    source!.emit('stage_started', { stage: 'analysis' }, 1)
    source!.emit('llm_token', { text: '你' }, 2)
    source!.emit('llm_token', { text: '好' }, 3)
    source!.emit('llm_token', { text: '，世界' }, 4)

    expect(stream.currentStage.value).toBe('analysis')
    expect(stream.tokensByStage.value.analysis).toBe('你好，世界')
    expect(stream.timeline.value).toHaveLength(4)
    expect(stream.eventCount.value).toBe(4)

    stream.stop()
  })

  it('历史 seed 与 SSE 回放按 seq 去重，usage 按阶段累计', () => {
    const stream = useRunStream(() => 3)
    stream.seedTimeline([
      makeEvent({ seq: 1 }),
      makeEvent({
        seq: 2,
        type: 'usage',
        payload: { prompt_tokens: 10, completion_tokens: 20 },
      }),
    ])

    stream.start()
    const source = FakeEventSource.instances[0]!
    source.emit('stage_started', { stage: 'analysis' }, 1)
    source.emit('usage', { prompt_tokens: 10, completion_tokens: 20 }, 2)
    source.emit('usage', { prompt_tokens: 5, completion_tokens: 7 }, 3)

    expect(stream.timeline.value).toHaveLength(3)
    expect(stream.promptTokens.value).toBe(15)
    expect(stream.completionTokens.value).toBe(27)

    stream.stop()
  })

  it('timeline 超过上限时丢弃最旧事件', () => {
    const stream = useRunStream(() => 1)
    stream.start()
    const source = FakeEventSource.instances[0]!

    for (let seq = 1; seq <= MAX_TIMELINE_EVENTS + 1; seq += 1) {
      source.emit('llm_token', { text: 'x' }, seq)
    }

    expect(stream.timeline.value).toHaveLength(MAX_TIMELINE_EVENTS)
    expect(stream.timeline.value[0]?.seq).toBe(2)
    expect(stream.timeline.value[MAX_TIMELINE_EVENTS - 1]?.seq).toBe(
      MAX_TIMELINE_EVENTS + 1,
    )

    stream.stop()
  })

  it('run_finished 关闭连接，之后不再接收事件', () => {
    const stream = useRunStream(() => 1)
    stream.start()
    const source = FakeEventSource.instances[0]!

    source.emit('llm_token', { text: 'a' }, 1)
    expect(stream.tokensByStage.value.unknown).toBe('a')

    source.emit('run_finished', { status: 'succeeded' }, 2)
    expect(stream.status.value).toBe('closed')
    expect(source.closed).toBe(true)

    const size = stream.timeline.value.length
    source.emit('llm_token', { text: 'b' }, 3)
    expect(stream.timeline.value).toHaveLength(size)
    expect(stream.tokensByStage.value.unknown).toBe('a')

    // stop 幂等
    stream.stop()
    stream.stop()
    expect(stream.status.value).toBe('closed')
  })

  it('run_paused 触发回调并关闭连接', () => {
    const onRunPaused = vi.fn()
    const stream = useRunStream(() => 1, { onRunPaused })
    stream.start()
    const source = FakeEventSource.instances[0]!

    source.notifyOpen()
    source.emit('run_paused', { status: 'paused', checkpoint_id: 'cp-1' }, 2)

    expect(onRunPaused).toHaveBeenCalledTimes(1)
    expect(onRunPaused.mock.calls[0]?.[0]?.payload).toEqual({
      status: 'paused',
      checkpoint_id: 'cp-1',
    })
    expect(stream.status.value).toBe('closed')
    expect(source.closed).toBe(true)
    expect(stream.timeline.value).toHaveLength(1)

    const size = stream.timeline.value.length
    source.emit('llm_token', { text: 'x' }, 3)
    expect(stream.timeline.value).toHaveLength(size)
  })

  it('stage_finished 清理该阶段 token 缓冲', () => {
    const stream = useRunStream(() => 1)
    stream.start()
    const source = FakeEventSource.instances[0]!

    source.emit('stage_started', { stage: 'analysis' }, 1)
    source.emit('llm_token', { text: 'abcdef' }, 2)
    expect(stream.tokensByStage.value.analysis).toBe('abcdef')

    source.emit('stage_finished', { stage: 'analysis' }, 3)
    expect(stream.tokensByStage.value.analysis).toBeUndefined()

    stream.stop()
  })

  it('连接失败暴露 error 状态，stop 后不再处理事件', () => {
    const stream = useRunStream(() => 1)
    stream.start()
    const source = FakeEventSource.instances[0]!

    source.notifyError()
    expect(stream.status.value).toBe('error')

    stream.stop()
    const size = stream.timeline.value.length
    source.emit('stage_started', { stage: 'design' }, 10)
    expect(stream.timeline.value).toHaveLength(size)
  })
})
