import { describe, expect, it } from 'vitest'

import {
  activeStageIndex,
  buildStageSteps,
  isActiveRunStatus,
  stageIndex,
  stageLabel,
} from '@/utils/stage'

function statusesOf(status: 'waiting_approval' | 'failed' | 'succeeded' | 'running' | 'queued' | 'cancelled' | 'paused', stage: 'analysis' | 'design' | 'coding' | 'review' | null) {
  return buildStageSteps(status, stage).map((step) => step.status)
}

describe('utils/stage 阶段状态推导', () => {
  it('waiting_approval@design：前两步完成，第二步本身等待审批（不是下一步）', () => {
    const steps = buildStageSteps('waiting_approval', 'design')

    expect(steps.map((step) => step.status)).toEqual(['finish', 'process', 'wait', 'wait'])
    expect(steps[1]?.tone).toBe('approval')
    expect(steps[1]?.description).toBe('等待审批')
  })

  it('waiting_approval@analysis：第一步就是等待审批', () => {
    const steps = buildStageSteps('waiting_approval', 'analysis')

    expect(steps.map((step) => step.status)).toEqual(['process', 'wait', 'wait', 'wait'])
    expect(steps[0]?.tone).toBe('approval')
  })

  it('failed@coding：前两步完成，第三步失败，第四步未执行', () => {
    const steps = buildStageSteps('failed', 'coding')

    expect(steps.map((step) => step.status)).toEqual(['finish', 'finish', 'error', 'wait'])
    expect(steps[2]?.tone).toBe('failed')
  })

  it('succeeded：四步全部完成', () => {
    expect(statusesOf('succeeded', 'review')).toEqual(['finish', 'finish', 'finish', 'finish'])
    expect(statusesOf('succeeded', null)).toEqual(['finish', 'finish', 'finish', 'finish'])
  })

  it('running@design：第二阶段运行中，之后的阶段未执行', () => {
    const steps = buildStageSteps('running', 'design')

    expect(steps.map((step) => step.status)).toEqual(['finish', 'process', 'wait', 'wait'])
    expect(steps[1]?.tone).toBe('running')
  })

  it('waiting_approval@review：前三步完成，评审门等待审批', () => {
    const steps = buildStageSteps('waiting_approval', 'review')

    expect(steps.map((step) => step.status)).toEqual(['finish', 'finish', 'finish', 'process'])
    expect(steps[3]?.tone).toBe('approval')
  })

  it('paused@coding：前两步完成，coding 标记已暂停，review 未执行', () => {
    const steps = buildStageSteps('paused', 'coding')

    expect(steps.map((step) => step.status)).toEqual(['finish', 'finish', 'process', 'wait'])
    expect(steps[2]?.description).toBe('已暂停')
  })

  it('activeStageIndex 与后端 current_stage 对齐', () => {
    expect(activeStageIndex('waiting_approval', 'design')).toBe(1)
    expect(activeStageIndex('waiting_approval', 'analysis')).toBe(0)
    expect(activeStageIndex('running', 'coding')).toBe(2)
    expect(activeStageIndex('succeeded', 'review')).toBe(4)
  })

  it('stageIndex/stageLabel/isActiveRunStatus 的边界行为', () => {
    expect(stageIndex('analysis')).toBe(0)
    expect(stageIndex(null)).toBe(-1)
    expect(stageLabel('review')).toBe('PR 评审')
    expect(stageLabel('unknown_stage')).toBe('unknown_stage')
    expect(isActiveRunStatus('waiting_approval')).toBe(true)
    expect(isActiveRunStatus('succeeded')).toBe(false)
  })
})
