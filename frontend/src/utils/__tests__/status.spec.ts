import { describe, expect, it } from 'vitest'

import type { RequirementStatus, RunStatus } from '@/api/types'
import { requirementStatusMeta, runStatusMeta } from '@/utils/status'

describe('utils/status 状态元信息', () => {
  it('paused 显示中文标签与 warning 色', () => {
    expect(runStatusMeta('paused')).toEqual({ label: '已暂停', type: 'warning' })
  })

  it('既有运行状态保持不变', () => {
    expect(runStatusMeta('running').label).toBe('运行中')
    expect(runStatusMeta('succeeded').type).toBe('success')
    expect(runStatusMeta('cancelled').label).toBe('已取消')
  })

  it('未知状态兜底为原始值 + info', () => {
    expect(runStatusMeta('paused_legacy' as RunStatus)).toEqual({
      label: 'paused_legacy',
      type: 'info',
    })
  })

  it('需求状态映射没有 paused，未知值兜底', () => {
    expect(requirementStatusMeta('done')).toEqual({ label: '已完成', type: 'success' })
    expect(requirementStatusMeta('unknown' as RequirementStatus)).toEqual({
      label: 'unknown',
      type: 'info',
    })
  })
})
