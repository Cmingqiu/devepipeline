import type { PendingApproval, RunStage, RunStatus } from '@/api/types'
import { PIPELINE_STAGES, stageIndex } from './stage'

export type PipelineNodeStatus = 'pending' | 'running' | 'waiting' | 'done' | 'failed'

export type PipelineNodeKind = 'stage' | 'gate'

export interface PipelineNode {
  id: string
  label: string
  kind: PipelineNodeKind
  stage: RunStage
  status: PipelineNodeStatus
}

export interface PipelineGraphInput {
  status: RunStatus
  currentStage: RunStage | null
  pendingStage?: RunStage | null
}

/**
 * 8 节点流水线：阶段与审批门交替，从左到右。
 *
 * 等待审批时 `current_stage` 指向待审批产物所属的阶段（后端 interrupt 的 stage 语义），
 * 所以该阶段产物已完成（绿），紧随其后的审批门才是橙色的等待状态。
 */
export function buildPipelineNodes(input: PipelineGraphInput): PipelineNode[] {
  const activeIndex = stageIndex(input.currentStage)
  const pendingIndex = stageIndex(input.pendingStage)
  const approvalIndex =
    input.status === 'waiting_approval'
      ? pendingIndex >= 0
        ? pendingIndex
        : activeIndex
      : -1

  const nodes: PipelineNode[] = []

  for (const [index, entry] of PIPELINE_STAGES.entries()) {
    nodes.push({
      id: `stage-${entry.key}`,
      label: entry.label,
      kind: 'stage',
      stage: entry.key,
      status: stageNodeStatus(input.status, index, activeIndex, approvalIndex),
    })
    nodes.push({
      id: `gate-${entry.key}`,
      label: `${entry.label}审批`,
      kind: 'gate',
      stage: entry.key,
      status: gateNodeStatus(input.status, index, activeIndex, approvalIndex),
    })
  }

  return nodes
}

function stageNodeStatus(
  status: RunStatus,
  index: number,
  activeIndex: number,
  approvalIndex: number,
): PipelineNodeStatus {
  switch (status) {
    case 'succeeded':
      return 'done'
    case 'failed':
      if (activeIndex < 0) return 'pending'
      if (index < activeIndex) return 'done'
      if (index === activeIndex) return 'failed'
      return 'pending'
    case 'cancelled':
      return activeIndex >= 0 && index < activeIndex ? 'done' : 'pending'
    case 'waiting_approval':
      return approvalIndex >= 0 && index <= approvalIndex ? 'done' : 'pending'
    case 'running':
      if (activeIndex < 0) return index === 0 ? 'running' : 'pending'
      if (index < activeIndex) return 'done'
      if (index === activeIndex) return 'running'
      return 'pending'
    default:
      return 'pending'
  }
}

function gateNodeStatus(
  status: RunStatus,
  index: number,
  activeIndex: number,
  approvalIndex: number,
): PipelineNodeStatus {
  switch (status) {
    case 'succeeded':
      return 'done'
    case 'failed':
      return activeIndex >= 0 && index < activeIndex ? 'done' : 'pending'
    case 'cancelled':
      return activeIndex >= 0 && index < activeIndex ? 'done' : 'pending'
    case 'waiting_approval':
      if (approvalIndex < 0) return 'pending'
      if (index < approvalIndex) return 'done'
      if (index === approvalIndex) return 'waiting'
      return 'pending'
    case 'running':
      return activeIndex >= 0 && index < activeIndex ? 'done' : 'pending'
    default:
      return 'pending'
  }
}

export const PIPELINE_NODE_STATUS_LABEL: Record<PipelineNodeStatus, string> = {
  pending: '待执行',
  running: '运行中',
  waiting: '等待审批',
  done: '已完成',
  failed: '失败',
}

export function pendingStageOf(pending: PendingApproval | null | undefined): RunStage | null {
  return pending?.stage ?? null
}
