<script setup lang="ts">
import { reactive, ref, watch } from 'vue'

import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import type { RequirementCreatePayload } from '@/api/requirements'

const visible = defineModel<boolean>({ required: true })

const props = withDefaults(
  defineProps<{
    loading?: boolean
  }>(),
  {
    loading: false,
  },
)

const emit = defineEmits<{
  (e: 'submit', payload: RequirementCreatePayload): void
}>()

const formRef = ref<FormInstance>()
const form = reactive({
  title: '',
  content: '',
  note: '',
})

const rules: FormRules = {
  title: [
    { required: true, message: '请输入需求标题', trigger: 'blur' },
    { max: 200, message: '标题不超过 200 个字符', trigger: 'blur' },
  ],
  content: [{ required: true, message: '请输入需求正文', trigger: 'blur' }],
}

watch(visible, (open) => {
  if (!open) {
    return
  }
  form.title = ''
  form.content = ''
  form.note = ''
  formRef.value?.clearValidate()
})

function close(): void {
  visible.value = false
}

async function submit(): Promise<void> {
  const formEl = formRef.value
  if (!formEl) {
    return
  }

  const title = form.title.trim()
  if (!title) {
    void formEl.validate().catch(() => undefined)
    ElMessage.warning('请输入需求标题')
    return
  }
  if (!form.content.trim()) {
    void formEl.validate().catch(() => undefined)
    ElMessage.warning('请输入需求正文')
    return
  }

  const payload: RequirementCreatePayload = {
    title,
    content: form.content,
  }
  const note = form.note.trim()
  if (note) {
    payload.note = note
  }
  emit('submit', payload)
}

defineExpose({ submit })
</script>

<template>
  <el-dialog
    v-model="visible"
    title="新建需求"
    width="680px"
    :close-on-click-modal="false"
  >
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-width="76px"
      @submit.prevent="submit"
    >
      <el-form-item label="标题" prop="title">
        <el-input v-model="form.title" maxlength="200" placeholder="一句话说明要做什么" />
      </el-form-item>

      <el-form-item label="正文" prop="content">
        <el-input
          v-model="form.content"
          type="textarea"
          :rows="12"
          placeholder="支持 Markdown，创建后保存为 v1"
        />
      </el-form-item>

      <el-form-item label="备注">
        <el-input v-model="form.note" maxlength="200" placeholder="可选，说明这次录入的背景" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="props.loading" @click="submit">创建</el-button>
    </template>
  </el-dialog>
</template>
