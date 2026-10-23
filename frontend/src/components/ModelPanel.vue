<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { ElMessage, ElMessageBox } from 'element-plus'

import type {
  BindingSource,
  ModelBinding,
  ModelBindingInput,
  Provider,
  ProviderCreatePayload,
  ProviderUpdatePayload,
} from '@/api/types'
import { useModelStore } from '@/stores/model'
import { getErrorMessage } from '@/utils/feedback'
import { PIPELINE_STAGES, stageLabel } from '@/utils/stage'

const SOURCE_META: Record<BindingSource, { label: string; type: 'primary' | 'info' | 'warning' }> = {
  project: { label: '项目', type: 'primary' },
  global: { label: '全局', type: 'info' },
  env: { label: '环境变量', type: 'warning' },
}

const GLOBAL_PROVIDER_VALUE = 0

interface BindingDraft {
  stage: ModelBinding['stage']
  /** 0 表示跟随全局 / 环境变量（el-option 的 value 不支持 null） */
  provider_id: number
  model: string
  params: string
  source: BindingSource
  configured: boolean
  /** 非项目来源时展示当前生效的 provider/model */
  effective: string
}

interface JsonParseResult {
  ok: boolean
  /** 空白文本归一化为 null */
  value: Record<string, unknown> | null
  message: string
}

const props = defineProps<{
  projectId: number
}>()

const store = useModelStore()

const providerDialogVisible = ref(false)
const editingProviderId = ref<number | null>(null)
const providerFormError = ref('')
const providerListError = ref('')
const providerForm = reactive({
  name: '',
  endpoint: '',
  model: '',
  api_key: '',
  extra: '',
  enabled: true,
})

const bindingDrafts = ref<BindingDraft[]>([])
const bindingError = ref('')

const isEditingProvider = computed(() => editingProviderId.value !== null)

onMounted(() => {
  loadProviders()
  loadBindings()
})

function loadProviders(): void {
  store.fetchProviders().catch((err) => {
    providerListError.value = getErrorMessage(err, '加载模型提供商失败')
    ElMessage.error(providerListError.value)
  })
}

async function loadBindings(): Promise<void> {
  try {
    applyBindings(await store.fetchBindings(props.projectId))
  } catch (err) {
    bindingError.value = getErrorMessage(err, '加载模型绑定失败')
    ElMessage.error(bindingError.value)
  }
}

function formatParams(params: Record<string, unknown> | null | undefined): string {
  if (!params || Object.keys(params).length === 0) {
    return ''
  }
  return JSON.stringify(params, null, 2)
}

function applyBindings(bindings: ModelBinding[]): void {
  const byStage = new Map(bindings.map((binding) => [binding.stage, binding]))
  bindingDrafts.value = PIPELINE_STAGES.map(({ key }) => {
    const binding = byStage.get(key)
    // 生效视图里 global/env 来源也可能是某个具体 provider，只有 project 来源才是项目覆盖
    const isProject = binding?.source === 'project'
    return {
      stage: key,
      provider_id: isProject
        ? (binding?.provider_id ?? GLOBAL_PROVIDER_VALUE)
        : GLOBAL_PROVIDER_VALUE,
      model: isProject ? (binding?.override_model ?? '') : '',
      params: isProject ? formatParams(binding?.override_params) : '',
      source: binding?.source ?? 'env',
      configured: binding?.configured ?? false,
      effective: isProject
        ? ''
        : `${binding?.provider_name ?? '-'} · ${binding?.model ?? '-'}`,
    }
  })
}

function providerOptionLabel(provider: Provider): string {
  const status = provider.enabled ? '' : ' · 已停用'
  const key = provider.configured ? '' : ' · 未配置密钥'
  return `${provider.name}（${provider.model}）${status}${key}`
}

function sourceMeta(source: BindingSource): { label: string; type: 'primary' | 'info' | 'warning' } {
  return SOURCE_META[source] ?? { label: source, type: 'info' }
}

/** 空白返回 null；非法 JSON 返回 ok=false，不抛异常 */
function parseJsonObject(text: string, label: string): JsonParseResult {
  const raw = text.trim()
  if (!raw) {
    return { ok: true, value: null, message: '' }
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return { ok: false, value: null, message: `${label} 不是合法的 JSON` }
  }

  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return {
      ok: false,
      value: null,
      message: `${label} 必须是 JSON 对象，例如 {"temperature":0.2}`,
    }
  }

  return { ok: true, value: parsed as Record<string, unknown>, message: '' }
}

function openCreateProvider(): void {
  editingProviderId.value = null
  providerForm.name = ''
  providerForm.endpoint = ''
  providerForm.model = ''
  providerForm.api_key = ''
  providerForm.extra = ''
  providerForm.enabled = true
  providerFormError.value = ''
  providerDialogVisible.value = true
}

function openEditProvider(provider: Provider): void {
  editingProviderId.value = provider.id
  providerForm.name = provider.name
  providerForm.endpoint = provider.endpoint
  providerForm.model = provider.model
  providerForm.api_key = ''
  providerForm.extra = formatParams(provider.extra)
  providerForm.enabled = provider.enabled
  providerFormError.value = ''
  providerDialogVisible.value = true
}

async function submitProvider(): Promise<void> {
  const name = providerForm.name.trim()
  const endpoint = providerForm.endpoint.trim()
  const model = providerForm.model.trim()

  if (!name) {
    providerFormError.value = '请输入提供商名称'
    ElMessage.warning(providerFormError.value)
    return
  }
  if (!/^[A-Za-z0-9._-]+$/.test(name)) {
    providerFormError.value = '名称只能包含字母、数字、点、下划线和短横线'
    ElMessage.warning(providerFormError.value)
    return
  }
  if (!endpoint) {
    providerFormError.value = '请输入端点地址'
    ElMessage.warning(providerFormError.value)
    return
  }
  if (!model) {
    providerFormError.value = '请输入模型名称'
    ElMessage.warning(providerFormError.value)
    return
  }

  const extra = parseJsonObject(providerForm.extra, 'extra')
  if (!extra.ok) {
    providerFormError.value = extra.message
    ElMessage.error(extra.message)
    return
  }

  providerFormError.value = ''
  const apiKey = providerForm.api_key.trim()

  try {
    if (editingProviderId.value !== null) {
      const payload: ProviderUpdatePayload = { name, endpoint, model, enabled: providerForm.enabled }
      if (apiKey) {
        payload.api_key = apiKey
      }
      if (extra.value) {
        payload.extra = extra.value
      }
      await store.updateProvider(editingProviderId.value, payload)
      ElMessage.success('模型提供商已更新')
    } else {
      const payload: ProviderCreatePayload = { name, endpoint, model, enabled: providerForm.enabled }
      if (apiKey) {
        payload.api_key = apiKey
      }
      if (extra.value) {
        payload.extra = extra.value
      }
      await store.createProvider(payload)
      ElMessage.success('模型提供商已创建')
    }
    providerDialogVisible.value = false
  } catch (err) {
    providerFormError.value = getErrorMessage(err, '保存模型提供商失败')
    ElMessage.error(providerFormError.value)
  }
}

async function toggleProvider(provider: Provider, value: string | number | boolean): Promise<void> {
  try {
    await store.updateProvider(provider.id, { enabled: Boolean(value) })
  } catch (err) {
    providerListError.value = getErrorMessage(err, '更新提供商状态失败')
    ElMessage.error(providerListError.value)
  }
}

async function removeProvider(provider: Provider): Promise<void> {
  const confirmed = await ElMessageBox.confirm(
    `删除后使用该提供商的阶段绑定会失效，确定删除「${provider.name}」？`,
    '删除模型提供商',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  )
    .then(() => true)
    .catch(() => false)
  if (!confirmed) {
    return
  }

  try {
    await store.removeProvider(provider.id)
    providerListError.value = ''
    ElMessage.success('模型提供商已删除')
    await loadBindings()
  } catch (err) {
    // 被阶段绑定引用时后端返回 409，直接展示后端错误消息
    providerListError.value = getErrorMessage(err, '删除模型提供商失败')
    ElMessage.error(providerListError.value)
  }
}

async function saveBindings(): Promise<void> {
  const items: ModelBindingInput[] = []

  for (const draft of bindingDrafts.value) {
    const params = parseJsonObject(draft.params, `${stageLabel(draft.stage)}参数`)
    if (!params.ok) {
      bindingError.value = params.message
      ElMessage.error(params.message)
      return
    }

    if (draft.provider_id <= GLOBAL_PROVIDER_VALUE) {
      items.push({ stage: draft.stage, provider_id: null })
      continue
    }

    const provider = store.providers.find((item) => item.id === draft.provider_id)
    if (provider && !provider.enabled) {
      bindingError.value = `「${provider.name}」已停用，不能绑定`
      ElMessage.error(bindingError.value)
      return
    }

    items.push({
      stage: draft.stage,
      provider_id: draft.provider_id,
      model: draft.model.trim() || null,
      params: params.value ?? {},
    })
  }

  bindingError.value = ''
  try {
    const bindings = await store.saveBindings({
      project_id: props.projectId,
      scope: 'project',
      items,
    })
    applyBindings(bindings)
    ElMessage.success('模型绑定已保存')
  } catch (err) {
    bindingError.value = getErrorMessage(err, '保存模型绑定失败')
    ElMessage.error(bindingError.value)
  }
}
</script>

<template>
  <section class="surface">
    <header class="section-head">
      <div class="page-head__text">
        <h2 class="section-title">模型</h2>
        <p class="page-subtitle">
          提供商使用 OpenAI 兼容端点；密钥来自 API Key 或环境变量 LLM_KEY_&lt;NAME&gt;。未配置密钥的提供商不能用于运行。
        </p>
      </div>
      <div class="page-actions">
        <el-button type="primary" @click="openCreateProvider">新增提供商</el-button>
      </div>
    </header>

    <el-table v-loading="store.providersLoading" :data="store.providers" size="small">
      <el-table-column label="名称" min-width="130">
        <template #default="{ row }">
          <span class="model-provider-name">{{ row.name }}</span>
        </template>
      </el-table-column>

      <el-table-column label="端点" min-width="220">
        <template #default="{ row }">
          <span class="mono">{{ row.endpoint }}</span>
        </template>
      </el-table-column>

      <el-table-column label="默认模型" min-width="150">
        <template #default="{ row }">
          <span class="mono">{{ row.model }}</span>
        </template>
      </el-table-column>

      <el-table-column label="状态" width="170">
        <template #default="{ row }">
          <div class="model-provider-status">
            <el-tag size="small" :type="row.configured ? 'success' : 'warning'" effect="plain">
              {{ row.configured ? '已配置' : '未配置密钥' }}
            </el-tag>
            <span v-if="row.credential_hint" class="mono muted">{{ row.credential_hint }}</span>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="启用" width="82">
        <template #default="{ row }">
          <el-switch
            :model-value="row.enabled"
            :loading="store.providerSubmitting"
            @change="toggleProvider(row, $event)"
          />
        </template>
      </el-table-column>

      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEditProvider(row)">编辑</el-button>
          <el-button link type="danger" @click="removeProvider(row)">删除</el-button>
        </template>
      </el-table-column>

      <template #empty>
        <el-empty description="还没有模型提供商，先添加一个" :image-size="72" />
      </template>
    </el-table>

    <p v-if="providerListError" class="form-error">{{ providerListError }}</p>

    <div class="settings-section">
      <header class="section-head">
        <div class="page-head__text">
          <h3 class="section-title">每阶段模型绑定</h3>
          <p class="page-subtitle">
            选择「跟随全局 / 环境变量」表示本项目不覆盖该阶段；保存时提交完整 4 条，来源徽标为保存后的生效视图。
          </p>
        </div>
        <div class="page-actions">
          <el-button type="primary" :loading="store.bindingsSaving" @click="saveBindings">
            保存模型绑定
          </el-button>
        </div>
      </header>

      <div v-loading="store.bindingsLoading" class="model-binding-list">
        <div v-for="draft in bindingDrafts" :key="draft.stage" class="model-binding-row">
          <div class="model-binding-row__stage">
            <span class="model-binding-row__label">{{ stageLabel(draft.stage) }}</span>
            <span class="mono muted">{{ draft.stage }}</span>
          </div>

          <el-select v-model="draft.provider_id" class="model-binding-row__select">
            <el-option label="跟随全局 / 环境变量" :value="GLOBAL_PROVIDER_VALUE" />
            <el-option
              v-for="provider in store.providers"
              :key="provider.id"
              :label="providerOptionLabel(provider)"
              :value="provider.id"
            />
          </el-select>

          <el-input
            v-model="draft.model"
            placeholder="模型覆盖（可空）"
            class="model-binding-row__model"
          />

          <el-input
            v-model="draft.params"
            type="textarea"
            :rows="2"
            spellcheck="false"
            placeholder='参数 JSON（可空），例如 {"temperature":0.2}'
            class="model-binding-row__params"
          />

          <div class="model-binding-row__tags">
            <el-tag size="small" :type="sourceMeta(draft.source).type" effect="plain">
              {{ sourceMeta(draft.source).label }}
            </el-tag>
            <el-tag size="small" :type="draft.configured ? 'success' : 'info'" effect="plain">
              {{ draft.configured ? '已生效' : '未生效' }}
            </el-tag>
          </div>

          <span v-if="draft.effective" class="model-binding-row__effective">
            当前生效：{{ draft.effective }}
          </span>
        </div>
      </div>

      <p v-if="bindingError" class="form-error">{{ bindingError }}</p>
    </div>

    <el-dialog
      v-model="providerDialogVisible"
      :title="isEditingProvider ? '编辑模型提供商' : '新增模型提供商'"
      width="560px"
    >
      <el-form class="settings-form" label-width="96px" @submit.prevent="submitProvider">
        <el-form-item label="名称">
          <el-input v-model="providerForm.name" maxlength="64" placeholder="例如 deepseek" />
        </el-form-item>

        <el-form-item label="端点">
          <el-input
            v-model="providerForm.endpoint"
            maxlength="512"
            placeholder="https://api.deepseek.com/v1"
          />
        </el-form-item>

        <el-form-item label="默认模型">
          <el-input v-model="providerForm.model" maxlength="128" placeholder="deepseek-chat" />
        </el-form-item>

        <el-form-item label="API Key">
          <el-input
            v-model="providerForm.api_key"
            type="password"
            show-password
            autocomplete="new-password"
            :placeholder="isEditingProvider ? '留空表示不修改密钥' : '可选：不填则读取环境变量'"
          />
        </el-form-item>

        <el-form-item label="extra">
          <el-input
            v-model="providerForm.extra"
            type="textarea"
            :rows="4"
            spellcheck="false"
            placeholder='可选 JSON 对象，例如 {"temperature":0.2}'
          />
        </el-form-item>

        <el-form-item label="启用">
          <el-switch v-model="providerForm.enabled" />
        </el-form-item>

        <p v-if="providerFormError" class="form-error">{{ providerFormError }}</p>
      </el-form>

      <template #footer>
        <el-button @click="providerDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="store.providerSubmitting" @click="submitProvider">
          保存
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>
