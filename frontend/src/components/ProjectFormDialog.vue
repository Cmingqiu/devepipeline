<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import type { ProjectCreatePayload, ProjectUpdatePayload } from '@/api/projects'
import type { Project } from '@/api/types'

const visible = defineModel<boolean>({ required: true })

const props = withDefaults(
  defineProps<{
    project?: Project | null
    loading?: boolean
  }>(),
  {
    project: null,
    loading: false,
  },
)

const emit = defineEmits<{
  (e: 'submit', payload: ProjectCreatePayload | ProjectUpdatePayload): void
}>()

const formRef = ref<FormInstance>()
const form = reactive({
  name: '',
  slug: '',
  description: '',
})

const isEdit = computed(() => Boolean(props.project))
const dialogTitle = computed(() => (isEdit.value ? '编辑项目' : '新建项目'))

const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/

const rules: FormRules = {
  name: [
    { required: true, message: '请输入项目名称', trigger: 'blur' },
    { max: 120, message: '名称不超过 120 个字符', trigger: 'blur' },
  ],
  slug: [
    // 与后端一致：≤64，小写字母/数字/单连字符
    { max: 64, message: 'slug 不超过 64 个字符', trigger: 'blur' },
    { pattern: SLUG_PATTERN, message: '只能用小写字母、数字和单个连字符', trigger: 'blur' },
  ],
  description: [{ max: 1000, message: '描述不超过 1000 个字符', trigger: 'blur' }],
}

watch(
  () => [visible.value, props.project] as const,
  ([open]) => {
    if (!open) {
      return
    }
    form.name = props.project?.name ?? ''
    form.slug = props.project?.slug ?? ''
    form.description = props.project?.description ?? ''
    formRef.value?.clearValidate()
  },
  { immediate: true },
)

function close(): void {
  visible.value = false
}

async function submit(): Promise<void> {
  const formEl = formRef.value
  if (!formEl) {
    return
  }

  const name = form.name.trim()
  if (!name) {
    // 触发 el-form 的红框提示；必填判断以显式校验为准
    void formEl.validate().catch(() => undefined)
    ElMessage.warning('请输入项目名称')
    return
  }

  const description = form.description.trim()
  if (isEdit.value) {
    const payload: ProjectUpdatePayload = {
      name,
      description: description || null,
    }
    emit('submit', payload)
    return
  }

  const slug = form.slug.trim()
  if (slug && !SLUG_PATTERN.test(slug)) {
    // 后端会 422，这里先拦住并给明确文案（同时触发红框）
    void formEl.validate().catch(() => undefined)
    ElMessage.warning('slug 只能用小写字母、数字和单个连字符')
    return
  }
  const payload: ProjectCreatePayload = {
    name,
    description: description || null,
  }
  if (slug) {
    payload.slug = slug
  }
  emit('submit', payload)
}

defineExpose({ submit })
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="dialogTitle"
    width="520px"
    :close-on-click-modal="false"
  >
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-width="84px"
      @submit.prevent="submit"
    >
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" maxlength="120" placeholder="例如：DevPipeline" />
      </el-form-item>

      <el-form-item v-if="!isEdit" label="Slug" prop="slug">
        <el-input v-model="form.slug" maxlength="80" placeholder="可选，留空由后端生成" />
      </el-form-item>

      <el-form-item v-else label="Slug">
        <span class="mono muted">{{ project?.slug }}</span>
      </el-form-item>

      <el-form-item label="描述" prop="description">
        <el-input
          v-model="form.description"
          type="textarea"
          :rows="4"
          maxlength="1000"
          show-word-limit
          placeholder="可选，一句话说明这个项目做什么"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="loading" @click="submit">
        {{ isEdit ? '保存' : '创建' }}
      </el-button>
    </template>
  </el-dialog>
</template>
