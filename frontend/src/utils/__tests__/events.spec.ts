import { describe, expect, it } from 'vitest'

import {
  eventStageLabel,
  eventTone,
  eventTypeLabel,
  formatEventSummary,
  formatEventTime,
  truncateText,
} from '@/utils/events'
import type { RunEvent } from '@/api/types'

describe('utils/events 时间线格式化', () => {
  it('类型标签与颜色 tone', () => {
    expect(eventTypeLabel('llm_token')).toBe('Token')
    expect(eventTypeLabel('interrupt')).toBe('等待审批')
    expect(eventTypeLabel('unknown_type')).toBe('unknown_type')

    expect(eventTone('interrupt')).toBe('warning')
    expect(eventTone('error')).toBe('danger')
    expect(eventTone('run_finished')).toBe('success')
    expect(eventTone('llm_token')).toBe('default')
  })

  it('摘要按事件类型提取关键字段并截断', () => {
    expect(
      formatEventSummary('interrupt', {
        stage: 'design',
        label: '系统设计审批',
        attempt: 2,
      }),
    ).toBe('等待审批：系统设计审批（第 2 次）')

    expect(formatEventSummary('usage', { prompt_tokens: 10, completion_tokens: 20 })).toBe(
      'prompt 10 / completion 20',
    )

    expect(
      formatEventSummary('artifact_saved', {
        artifact_id: 3,
        version: 2,
        kind: 'markdown',
        summary: '设计文档',
      }),
    ).toBe('产物 #3 v2 markdown：设计文档')

    expect(
      formatEventSummary('error', { code: 'boom', message: 'x'.repeat(200) }).length,
    ).toBeLessThanOrEqual(120 + 1)
    expect(
      formatEventSummary('error', { code: 'boom', message: 'x'.repeat(200) }),
    ).toContain('boom:')
  })

  it('llm_token 摘要按 40 字截断', () => {
    const long = 'x'.repeat(200)
    const summary = formatEventSummary('llm_token', { text: long })

    expect(summary).toBe(truncateText(long, 40))
    expect(summary.length).toBe(41)
  })

  it('时间格式化与 stage 标签', () => {
    expect(formatEventTime('2026-10-21T06:00:00.000Z')).toMatch(/^\d{2}:\d{2}:\d{2}$/)
    expect(formatEventTime('not-a-date')).toBe('-')

    const event: RunEvent = {
      seq: 1,
      ts: '2026-10-21T06:00:00.000Z',
      stage: 'design',
      type: 'stage_started',
      payload: { stage: 'design' },
    }
    expect(eventStageLabel(event)).toBe('系统设计')
    expect(eventStageLabel({ ...event, stage: null })).toBe('-')
  })
})
