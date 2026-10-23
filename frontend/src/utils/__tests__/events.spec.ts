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

  it('pull_request_created 标签、tone 与摘要', () => {
    expect(eventTypeLabel('pull_request_created')).toBe('PR 创建')
    expect(eventTone('pull_request_created')).toBe('success')

    expect(
      formatEventSummary('pull_request_created', {
        provider: 'github',
        number: 12,
        url: 'https://github.com/acme/devpipeline/pull/12',
        branch: 'devpipeline/run-7',
        base_branch: 'main',
        head_sha: 'abc123def456',
      }),
    ).toBe('GitHub PR #12：devpipeline/run-7 → main')
  })

  it('pull_request_created 缺字段时不崩', () => {
    expect(formatEventSummary('pull_request_created')).toBe('PR')
    expect(formatEventSummary('pull_request_created', { number: 3 })).toBe('PR #3')
    expect(
      formatEventSummary('pull_request_created', {
        provider: 'gitlab',
        head_sha: null,
        branch: 'feature/x',
      }),
    ).toBe('GitLab PR：feature/x')
    expect(formatEventSummary('pull_request_created', { provider: 'other' })).toBe(
      'other PR',
    )
  })

  it('暂停/继续/fork 事件的标签、tone 与摘要', () => {
    expect(eventTypeLabel('run_pausing')).toBe('暂停中')
    expect(eventTypeLabel('run_paused')).toBe('已暂停')
    expect(eventTypeLabel('run_resumed')).toBe('已继续')
    expect(eventTypeLabel('forked')).toBe('已 fork')

    expect(eventTone('run_pausing')).toBe('warning')
    expect(eventTone('run_paused')).toBe('warning')
    expect(eventTone('run_resumed')).toBe('info')
    expect(eventTone('forked')).toBe('info')

    expect(formatEventSummary('run_pausing')).toBe(
      '已请求暂停，将在当前节点结束后生效',
    )
    expect(formatEventSummary('run_paused')).toBe('已暂停')
    expect(
      formatEventSummary('run_paused', {
        status: 'paused',
        checkpoint_id: 'checkpoint-abcdef123456',
      }),
    ).toBe('已暂停（checkpoint checkpoi）')
    expect(formatEventSummary('run_resumed')).toBe('继续运行（running）')
    expect(
      formatEventSummary('forked', {
        source_run_id: 7,
        checkpoint_id: 'abcdef1234567890',
        from_stage: 'coding',
      }),
    ).toBe('源自运行 #7（abcdef12），起始阶段：编码')
    // 缺字段不崩
    expect(formatEventSummary('forked')).toBe('从 checkpoint fork')
    expect(formatEventSummary('forked', { from_stage: 'unknown_stage' })).toBe(
      '从 checkpoint fork，起始阶段：unknown_stage',
    )
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
