import type { RunStage, RunStatus } from '@/api/types'

export const PIPELINE_STAGES: ReadonlyArray<{ key: RunStage; label: string }> = [
  { key: 'analysis', label: '需求分析' },
  { key: 'design', label: '系统设计' },
  { key: 'coding', label: '编码' },
  { key: 'review', label: 'PR 评审' },
]

export type StageStepStatus = 'wait' | 'process' | 'finish' | 'error'

/** 用于给当前步骤加颜色/动画：运行中蓝色、等待审批橙色、失败红 */
export type StageStepTone = 'running' | 'approval' | 'failed' | null

export interface StageStep {
  key: RunStage
  label: string
  status: StageStepStatus
  tone: StageStepTone
  description: string
}

export function stageIndex(stage: RunStage | null | undefined): number {
  if (!stage) {
    return -1
  }
  return PIPELINE_STAGES.findIndex((entry) => entry.key === stage)
}

export function isRunStage(value: string | null | undefined): value is RunStage {
  return (
    value === 'analysis' ||
    value === 'design' ||
    value === 'coding' ||
    value === 'review'
  )
}

export function stageLabel(stage: RunStage | string | null | undefined): string {
  if (!stage) {
    return '-'
  }
  return PIPELINE_STAGES.find((entry) => entry.key === stage)?.label ?? stage
}

export function isActiveRunStatus(status: RunStatus): boolean {
  return status === 'queued' || status === 'running' || status === 'waiting_approval'
}

/**
 * 把 run 的 status + current_stage 推导成 4 个步骤的展示状态。
 *
 * 后端语义：`current_stage` 是「当前停在/正在执行的阶段」。
 * 等待审批时它等于**待审批产物所属的阶段**（interrupt 的 payload.stage），
 * 所以该步本身就是「等待审批」，前面完成、后面未执行 —— 不要错位到下一步。
 */
export function buildStageSteps(
  status: RunStatus,
  currentStage: RunStage | null,
): StageStep[] {
  const index = stageIndex(currentStage)

  return PIPELINE_STAGES.map((entry, i) => {
    const base = { key: entry.key, label: entry.label }
    const finish = { ...base, status: 'finish' as const, tone: null, description: '已完成' }
    const wait = { ...base, status: 'wait' as const, tone: null, description: '未执行' }

    if (status === 'succeeded') {
      return finish
    }

    if (status === 'failed') {
      if (index < 0 || i < index) {
        return finish
      }
      if (i === index) {
        return { ...base, status: 'error' as const, tone: 'failed' as const, description: '执行失败' }
      }
      return wait
    }

    if (status === 'cancelled') {
      if (i < index) {
        return { ...finish, description: '已取消' }
      }
      return { ...wait, description: '已取消' }
    }

    if (status === 'waiting_approval') {
      if (index < 0) {
        return wait
      }
      if (i < index) {
        return finish
      }
      if (i === index) {
        return {
          ...base,
          status: 'process' as const,
          tone: 'approval' as const,
          description: '等待审批',
        }
      }
      return wait
    }

    if (status === 'paused') {
      if (index < 0) {
        return wait
      }
      if (i < index) {
        return finish
      }
      if (i === index) {
        return { ...base, status: 'process' as const, tone: null, description: '已暂停' }
      }
      return wait
    }

    if (status === 'running') {
      if (index < 0) {
        return i === 0
          ? { ...base, status: 'process' as const, tone: 'running' as const, description: '运行中' }
          : wait
      }
      if (i < index) {
        return finish
      }
      if (i === index) {
        return { ...base, status: 'process' as const, tone: 'running' as const, description: '运行中' }
      }
      return wait
    }

    // queued
    return i === 0
      ? { ...base, status: 'wait' as const, tone: null, description: '排队中' }
      : wait
  })
}

/** el-steps 的 active 下标：等待审批时当前阶段自身就是「进行中」的那步 */
export function activeStageIndex(status: RunStatus, currentStage: RunStage | null): number {
  const index = stageIndex(currentStage)
  if (status === 'succeeded') {
    return PIPELINE_STAGES.length
  }
  if (index < 0) {
    return 0
  }
  return index
}
