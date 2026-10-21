<script setup lang="ts">
import { computed } from 'vue'

import {
  Handle,
  MarkerType,
  Position,
  VueFlow,
  type Edge,
  type Node,
  type NodeMouseEvent,
} from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'

import type { RunStage, RunStatus } from '@/api/types'
import {
  PIPELINE_NODE_STATUS_LABEL,
  buildPipelineNodes,
  type PipelineNodeStatus,
} from '@/utils/pipeline'

const props = defineProps<{
  status: RunStatus
  currentStage: RunStage | null
  pendingStage?: RunStage | null
}>()

const emit = defineEmits<{
  (e: 'select-stage', stage: RunStage): void
}>()

const NODE_WIDTH = 130
const NODE_GAP = 44
const GATE_OFFSET_Y = 64

const pipelineNodes = computed(() =>
  buildPipelineNodes({
    status: props.status,
    currentStage: props.currentStage,
    pendingStage: props.pendingStage ?? null,
  }),
)

const nodes = computed<Node[]>(() =>
  pipelineNodes.value.map((node, index) => ({
    id: node.id,
    type: 'pipeline',
    position: {
      x: index * (NODE_WIDTH + NODE_GAP),
      y: node.kind === 'gate' ? GATE_OFFSET_Y : 0,
    },
    draggable: false,
    connectable: false,
    data: {
      label: node.label,
      status: node.status,
      kind: node.kind,
      stage: node.stage,
    },
  })),
)

const edges = computed<Edge[]>(() => {
  const list: Edge[] = []
  for (let index = 0; index < nodes.value.length - 1; index += 1) {
    const source = nodes.value[index]
    const target = nodes.value[index + 1]
    const sourceStatus = pipelineNodes.value[index]?.status
    list.push({
      id: `edge-${source.id}-${target.id}`,
      source: source.id,
      target: target.id,
      type: 'smoothstep',
      markerEnd: MarkerType.ArrowClosed,
      animated: sourceStatus === 'running',
      style: { stroke: '#c0c4cc', strokeWidth: 1.5 },
    })
  }
  return list
})

function statusLabel(status: PipelineNodeStatus): string {
  return PIPELINE_NODE_STATUS_LABEL[status] ?? status
}

function handleNodeClick(payload: NodeMouseEvent): void {
  const data = payload.node.data as { stage?: RunStage } | undefined
  if (data?.stage) {
    emit('select-stage', data.stage)
  }
}
</script>

<template>
  <div class="pipeline-graph">
    <VueFlow
      :nodes="nodes"
      :edges="edges"
      :fit-view-on-init="true"
      :nodes-draggable="false"
      :nodes-connectable="false"
      :elements-selectable="true"
      :zoom-on-scroll="false"
      :min-zoom="0.4"
      :max-zoom="1.4"
      @node-click="handleNodeClick"
    >
      <template #node-pipeline="{ data }">
        <div class="pipeline-node" :class="`pipeline-node--${data.status}`">
          <span class="pipeline-node__kind">
            {{ data.kind === 'gate' ? '审批门' : '阶段' }}
          </span>
          <span class="pipeline-node__label">{{ data.label }}</span>
          <span class="pipeline-node__status">{{ statusLabel(data.status) }}</span>
          <Handle type="target" :position="Position.Left" />
          <Handle type="source" :position="Position.Right" />
        </div>
      </template>

      <Background :gap="18" :size="1" />
      <Controls :show-interactive="false" />
    </VueFlow>
  </div>
</template>
