<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { ElMessage, ElMessageBox } from 'element-plus'

import type {
  Credential,
  CredentialKind,
  RepoConfig,
  RepoProvider,
} from '@/api/contexts'
import { useContextStore } from '@/stores/context'
import { formatDateTime } from '@/utils/datetime'
import { getErrorMessage } from '@/utils/feedback'

const CREDENTIAL_KIND_META: Record<
  CredentialKind,
  { label: string; type: 'primary' | 'success' | 'info' }
> = {
  git_token: { label: 'Git Token', type: 'primary' },
  llm_api_key: { label: 'LLM API Key', type: 'success' },
  mcp_env: { label: 'MCP 环境变量', type: 'info' },
}

const REPO_URL_PREFIX = /^(https:\/\/|git@)/

const props = defineProps<{
  projectId: number
}>()

const store = useContextStore()

const repoForm = reactive({
  repo_url: '',
  repo_provider: null as RepoProvider | null,
  default_branch: 'main',
  credential_id: null as number | null,
})

const credentialForm = reactive({
  name: '',
  kind: 'git_token' as CredentialKind,
  secret: '',
})

const deletingCredentialId = ref<number | null>(null)

onMounted(() => {
  loadRepo()
  loadCredentials()
})

function loadRepo(): void {
  store.fetchRepo(props.projectId).then(applyRepo).catch((err) => {
    ElMessage.error(getErrorMessage(err, '加载仓库配置失败'))
  })
}

function loadCredentials(): void {
  store.fetchCredentials(props.projectId).catch((err) => {
    ElMessage.error(getErrorMessage(err, '加载凭证列表失败'))
  })
}

function applyRepo(config: RepoConfig): void {
  repoForm.repo_url = config.repo_url ?? ''
  repoForm.repo_provider = config.repo_provider
  repoForm.default_branch = config.default_branch || 'main'
  repoForm.credential_id = config.credential_id
}

async function saveRepo(): Promise<void> {
  const repoUrl = repoForm.repo_url.trim()
  if (repoUrl && !REPO_URL_PREFIX.test(repoUrl)) {
    ElMessage.warning('仓库地址必须以 https:// 或 git@ 开头')
    return
  }
  const brand = repoForm.default_branch.trim()
  if (!brand) {
    ElMessage.warning('默认分支不能为空')
    return
  }

  try {
    const config = await store.saveRepo(props.projectId, {
      repo_url: repoUrl || null,
      repo_provider: repoForm.repo_provider || null,
      default_branch: brand,
      credential_id: repoForm.credential_id || null,
    })
    applyRepo(config)
    ElMessage.success('仓库配置已保存')
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '保存仓库配置失败'))
  }
}

async function testConnection(): Promise<void> {
  try {
    const result = await store.testRepo(props.projectId)
    if (result.ok) {
      ElMessage.success(result.message || '仓库连接正常')
    } else {
      ElMessage.warning(result.message || '仓库连接失败')
    }
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '测试仓库连接失败'))
  }
}

async function submitCredential(): Promise<void> {
  const name = credentialForm.name.trim()
  if (!name) {
    ElMessage.warning('请输入凭证名称')
    return
  }
  if (!credentialForm.secret.trim()) {
    ElMessage.warning('请输入密钥')
    return
  }

  try {
    const credential = await store.createCredential(props.projectId, {
      name,
      kind: credentialForm.kind,
      secret: credentialForm.secret,
    })
    credentialForm.name = ''
    credentialForm.secret = ''
    ElMessage.success(`凭证「${credential.name}」已保存，仅显示掩码 ${credential.hint}`)
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '保存凭证失败'))
  }
}

async function removeCredential(credential: Credential): Promise<void> {
  const confirmed = await ElMessageBox.confirm(
    `删除后使用该凭证的配置会失效，确定删除「${credential.name}」？`,
    '删除凭证',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  )
    .then(() => true)
    .catch(() => false)
  if (!confirmed) {
    return
  }

  deletingCredentialId.value = credential.id
  try {
    await store.removeCredential(props.projectId, credential.id)
    if (repoForm.credential_id === credential.id) {
      repoForm.credential_id = null
    }
    ElMessage.success('凭证已删除')
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '删除凭证失败'))
  } finally {
    deletingCredentialId.value = null
  }
}

function credentialKindMeta(kind: CredentialKind) {
  return CREDENTIAL_KIND_META[kind] ?? { label: kind, type: 'info' as const }
}
</script>

<template>
  <section class="surface">
    <header class="section-head">
      <div class="page-head__text">
        <h2 class="section-title">仓库</h2>
        <p class="page-subtitle">
          仓库地址支持 https:// 与 git@；测试连接由服务端执行 git ls-remote，最多 20 秒。
        </p>
      </div>
    </header>

    <el-form class="settings-form" label-width="96px" @submit.prevent="saveRepo">
      <el-form-item label="仓库地址">
        <el-input
          v-model="repoForm.repo_url"
          placeholder="https://github.com/org/repo.git 或 git@github.com:org/repo.git"
        />
      </el-form-item>

      <el-form-item label="Provider">
        <el-select
          v-model="repoForm.repo_provider"
          clearable
          placeholder="不设置"
          style="width: 100%"
        >
          <el-option label="GitHub" value="github" />
          <el-option label="GitLab" value="gitlab" />
        </el-select>
      </el-form-item>

      <el-form-item label="默认分支">
        <el-input v-model="repoForm.default_branch" maxlength="120" placeholder="main" />
      </el-form-item>

      <el-form-item label="凭证">
        <el-select
          v-model="repoForm.credential_id"
          clearable
          placeholder="不使用凭证"
          style="width: 100%"
        >
          <el-option
            v-for="credential in store.credentials"
            :key="credential.id"
            :label="`${credential.name}（${credential.hint}）`"
            :value="credential.id"
          />
        </el-select>
      </el-form-item>

      <el-form-item>
        <div class="page-actions">
          <el-button type="primary" :loading="store.repoSaving" @click="saveRepo">
            保存仓库配置
          </el-button>
          <el-button :loading="store.repoTesting" @click="testConnection">测试连接</el-button>
        </div>
      </el-form-item>
    </el-form>

    <p
      v-if="store.repoTestResult"
      class="repo-test-result"
      :class="store.repoTestResult.ok ? 'is-ok' : 'is-failed'"
    >
      {{ store.repoTestResult.ok ? '连接成功' : '连接失败' }}：{{ store.repoTestResult.message }}
    </p>

    <div class="settings-section">
      <header class="section-head">
        <div class="page-head__text">
          <h3 class="section-title">凭证</h3>
          <p class="page-subtitle">
            密钥只提交一次，保存后只显示掩码，不会回显明文。
          </p>
        </div>
      </header>

      <el-form class="settings-form" label-width="96px" @submit.prevent="submitCredential">
        <el-form-item label="名称">
          <el-input v-model="credentialForm.name" maxlength="120" placeholder="例如：部署令牌" />
        </el-form-item>

        <el-form-item label="类型">
          <el-select v-model="credentialForm.kind" style="width: 100%">
            <el-option label="Git Token" value="git_token" />
            <el-option label="LLM API Key" value="llm_api_key" />
            <el-option label="MCP 环境变量" value="mcp_env" />
          </el-select>
        </el-form-item>

        <el-form-item label="密钥">
          <el-input
            v-model="credentialForm.secret"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="只提交一次，保存后仅显示掩码"
          />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="store.credentialSubmitting" @click="submitCredential">
            添加凭证
          </el-button>
        </el-form-item>
      </el-form>

      <div v-loading="store.credentialsLoading" class="credential-list">
        <el-empty
          v-if="store.credentialIsEmpty"
          description="还没有凭证，先添加一个"
          :image-size="72"
        />

        <div
          v-for="credential in store.credentials"
          :key="credential.id"
          class="settings-version-item"
        >
          <div class="settings-version-item__main">
            <span class="credential-name">{{ credential.name }}</span>
            <el-tag size="small" :type="credentialKindMeta(credential.kind).type" effect="plain">
              {{ credentialKindMeta(credential.kind).label }}
            </el-tag>
            <span class="mono muted">{{ credential.hint }}</span>
          </div>
          <div class="credential-item__side">
            <span class="version-item__time">{{ formatDateTime(credential.created_at) }}</span>
            <el-button
              link
              type="danger"
              :loading="deletingCredentialId === credential.id"
              @click="removeCredential(credential)"
            >
              删除
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
