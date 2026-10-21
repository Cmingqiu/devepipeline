import { describe, expect, it } from 'vitest'

import {
  buildPipelineNodes,
  type PipelineNode,
  type PipelineNodeStatus,
} from '@/utils/pipeline'

function statusMap(nodes: PipelineNode[]): Record<string, PipelineNodeStatus> {
  return Object.fromEntries(nodes.map((node) => [node.id, node.status]))
}

describe('utils/pipeline 流水线图节点状态', () => {
  it('waiting_approval@design：design 及之前完成，design 审批门等待', () => {
    const nodes = buildPipelineNodes({
      status: 'waiting_approval',
      currentStage: 'design',
      pendingStage: 'design',
    })
    const map = statusMap(nodes)

    expect(nodes).toHaveLength(8)
    expect(map['stage-analysis']).toBe('done')
    expect(map['gate-analysis']).toBe('done')
    expect(map['stage-design']).toBe('done')
    expect(map['gate-design']).toBe('waiting')
    expect(map['stage-coding']).toBe('pending')
    expect(map['gate-coding']).toBe('pending')
    expect(map['stage-review']).toBe('pending')
  })

  it('running@coding：coding 运行中，coding 审批门未到', () => {
    const map = statusMap(
      buildPipelineNodes({ status: 'running', currentStage: 'coding' }),
    )

    expect(map['stage-analysis']).toBe('done')
    expect(map['gate-analysis']).toBe('done')
    expect(map['stage-design']).toBe('done')
    expect(map['gate-design']).toBe('done')
    expect(map['stage-coding']).toBe('running')
    expect(map['gate-coding']).toBe('pending')
    expect(map['stage-review']).toBe('pending')
  })

  it('failed@coding：coding 失败，之后节点未执行', () => {
    const map = statusMap(
      buildPipelineNodes({ status: 'failed', currentStage: 'coding' }),
    )

    expect(map['stage-analysis']).toBe('done')
    expect(map['stage-design']).toBe('done')
    expect(map['gate-design']).toBe('done')
    expect(map['stage-coding']).toBe('failed')
    expect(map['gate-coding']).toBe('pending')
    expect(map['stage-review']).toBe('pending')
    expect(map['gate-review']).toBe('pending')
  })

  it('succeeded：8 个节点全部完成', () => {
    const map = statusMap(
      buildPipelineNodes({ status: 'succeeded', currentStage: 'review' }),
    )

    expect(Object.values(map)).toEqual(Array(8).fill('done'))
  })

  it('其余状态：queued 全部待执行，cancelled 保留已完成节点', () => {
    const queued = statusMap(
      buildPipelineNodes({ status: 'queued', currentStage: null }),
    )
    expect(Object.values(queued).every((status) => status === 'pending')).toBe(true)

    const cancelled = statusMap(
      buildPipelineNodes({ status: 'cancelled', currentStage: 'design' }),
    )
    expect(cancelled['stage-analysis']).toBe('done')
    expect(cancelled['stage-design']).toBe('pending')
    expect(cancelled['stage-coding']).toBe('pending')
  })
})
