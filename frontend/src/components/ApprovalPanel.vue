<script setup lang="ts">
import { computed, ref } from 'vue'

import { ElMessage, ElMessageBox } from 'element-plus'
import { MdPreview } from 'md-editor-v3'

import { ApiError } from '@/api/client'
import type { ApprovalDecision, PendingApproval } from '@/api/types'
import { useRunStore } from '@/stores/run'
import { getErrorMessage } from '@/utils/feedback'
import { stageLabel } from '@/utils/stage'

const props = defineProps<{
  runId: number
  pending: PendingApproval
}>()

const emit = defineEmits<{
  (e: 'decided'): void
}>()

const store = useRunStore()

const editVisible = ref(false)
const editContent = ref('')
const editError = ref('')

const rejectVisible = ref(false)
const feedback = ref('')
const feedbackError = ref('')

const stageText = computed(() => stageLabel(props.pending.stage))
const summary = computed(() => props.pending.summary || '（没有摘要）')

function openEdit(): void {
  editContent.value = props.pending.preview ?? ''
  editError.value = ''
  editVisible.value = true
}

function openReject(): void {
  feedback.value = ''
  feedbackError.value = ''
  rejectVisible.value = true
}

async function decide(
  decision: ApprovalDecision,
  options: { feedback?: string; edited?: string } = {},
): Promise<void> {
  try {
    await store.submitApproval(props.runId, {
      decision,
      ...(options.feedback ? { feedback: options.feedback } : {}),
      ...(options.edited !== undefined ? { edited_content: options.edited } : {}),
    })
    ElMessage.success('审批已提交')
    editVisible.value = false
    rejectVisible.value = false
    emit('decided')
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      ElMessage.warning('该审批已失效，请刷新运行状态')
      return
    }
    ElMessage.error(getErrorMessage(err, '提交审批失败'))
  }
}

async function submitReject(): Promise<void> {
  const text = feedback.value.trim()
  if (!text) {
    feedbackError.value = '驳回必须填写意见'
    return
  }
  feedbackError.value = ''
  await decide('rejected', { feedback: text })
}

async function submitEdit(): Promise<void> {
  if (!editContent.value.trim()) {
    editError.value = '修改后的正文不能为空'
    return
  }
  editError.value = ''
  await decide('approved_with_edit', { edited: editContent.value })
}

async function submitAbort(): Promise<void> {
  const confirmed = await ElMessageBox.confirm(
    '中止运行后当前阶段会停止，已生成的产物保留。确定中止？',
    '中止运行',
    { type: 'warning', confirmButtonText: '中止', cancelButtonText: '取消' },
  )
    .then(() => true)
    .catch(() => false)
  if (!confirmed) {
    return
  }
  await decide('aborted')
}
</script>

<template>
  <section class="surface approval-panel">
    <header class="approval-panel__head">
      <div class="page-head__text">
        <h2 class="section-title">
          待审批：{{ pending.label || stageText }}
        </h2>
        <p class="page-subtitle">
          阶段 {{ stageText }} · 第 {{ pending.attempt }} 次尝试
        </p>
      </div>
      <div class="page-actions">
        <el-button type="primary" :loading="store.approving" @click="decide('approved')">
          通过
        </el-button>
        <el-button :disabled="store.approving" @click="openEdit">改后通过</el-button>
        <el-button type="danger" plain :disabled="store.approving" @click="openReject">
          驳回
        </el-button>
        <el-button :disabled="store.approving" @click="submitAbort">中止运行</el-button>
      </div>
    </header>

    <p class="approval-panel__summary">{{ summary }}</p>

    <div v-if="pending.preview" class="approval-preview">
      <MdPreview
        :id="`approval-preview-${pending.stage}`"
        :model-value="pending.preview"
        language="zh-CN"
      />
    </div>
    <el-empty v-else description="该审批没有预览正文" />

    <el-dialog v-model="editVisible" title="改后通过" width="760px" :close-on-click-modal="false">
      <p class="page-subtitle">
        默认带入待审批正文，修改后提交会保存为新产物版本并继续流水线。
      </p>
      <el-input v-model="editContent" type="textarea" :rows="16" class="edit-textarea" />
      <p v-if="editError" class="form-error">{{ editError }}</p>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="store.approving" @click="submitEdit">
          确认修改并提交
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="rejectVisible" title="驳回" width="560px" :close-on-click-modal="false">
      <p class="page-subtitle">驳回必须填写意见，流水线会按意见回到上游阶段重做。</p>
      <el-input
        v-model="feedback"
        type="textarea"
        :rows="5"
        placeholder="说明需要改什么"
        class="edit-textarea"
      />
      <p v-if="feedbackError" class="form-error">{{ feedbackError }}</p>
      <template #footer>
        <el-button @click="rejectVisible = false">取消</el-button>
        <el-button type="danger" :loading="store.approving" @click="submitReject">
          确认驳回
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>
