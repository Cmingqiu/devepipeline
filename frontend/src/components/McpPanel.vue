<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { ElMessage } from 'element-plus'

import { useContextStore } from '@/stores/context'
import { getErrorMessage } from '@/utils/feedback'
import { formatMcpServers, mcpToolLabel, parseMcpServers } from '@/utils/mcp'

const props = defineProps<{
  projectId: number
}>()

const store = useContextStore()

const text = ref('')
const parseError = ref('')
const loaded = ref(false)

onMounted(() => {
  load()
})

async function load(): Promise<void> {
  try {
    const servers = await store.fetchMcpServers(props.projectId)
    text.value = formatMcpServers(servers)
    loaded.value = true
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '加载 MCP 配置失败'))
  }
}

function readDrafts() {
  try {
    const drafts = parseMcpServers(text.value)
    parseError.value = ''
    return drafts
  } catch (err) {
    parseError.value = getErrorMessage(err, 'MCP 配置格式不正确')
    ElMessage.error(parseError.value)
    return null
  }
}

async function save(): Promise<void> {
  const drafts = readDrafts()
  if (!drafts) {
    return
  }

  try {
    const servers = await store.saveMcpServers(props.projectId, drafts)
    text.value = formatMcpServers(servers)
    ElMessage.success('MCP 配置已保存')
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '保存 MCP 配置失败'))
  }
}

async function test(): Promise<void> {
  const drafts = readDrafts()
  if (!drafts) {
    return
  }

  try {
    const results = await store.testMcpServers(props.projectId, drafts)
    const failed = results.filter((result) => !result.ok).length
    if (results.length === 0) {
      ElMessage.info('没有可测试的 MCP 服务器')
      return
    }
    if (failed > 0) {
      ElMessage.warning(`${results.length} 个服务器中 ${failed} 个连接失败`)
      return
    }
    ElMessage.success(`${results.length} 个服务器连接正常`)
  } catch (err) {
    ElMessage.error(getErrorMessage(err, '测试 MCP 连接失败'))
  }
}
</script>

<template>
  <section class="surface">
    <header class="section-head">
      <div class="page-head__text">
        <h2 class="section-title">MCP</h2>
        <p class="page-subtitle">
          JSON 整体覆盖保存；敏感值由后端掩码为 ****1234，保持原样保存即可。
        </p>
      </div>
      <div class="page-actions">
        <el-button :loading="store.mcpTesting" @click="test">测试连通性</el-button>
        <el-button type="primary" :loading="store.mcpSaving" @click="save">保存</el-button>
      </div>
    </header>

    <p class="page-subtitle">
      stdio 需要 config.command；streamable_http 需要 config.url。测试会按当前文本里的服务器逐个连接。
    </p>

    <el-input
      v-model="text"
      class="settings-json"
      type="textarea"
      :rows="18"
      spellcheck="false"
      placeholder='{"servers":[{"name":"filesystem","transport":"stdio","config":{"command":"npx","args":["-y","@modelcontextprotocol/server-filesystem","."]},"enabled":true}]}'
    />
    <p v-if="parseError" class="settings-json-error">{{ parseError }}</p>

    <div v-if="loaded" class="detail-meta mcp-summary">
      <span>已保存 {{ store.mcpServers.length }} 个服务器</span>
      <span v-for="server in store.mcpServers" :key="server.id" class="mcp-summary__item">
        <span class="mono">{{ server.name }}</span>
        <el-tag
          v-if="server.last_test_status"
          size="small"
          :type="server.last_test_status === 'ok' ? 'success' : 'danger'"
          effect="plain"
        >
          {{ server.last_test_status === 'ok' ? '上次测试正常' : '上次测试失败' }}
        </el-tag>
      </span>
    </div>

    <div v-if="store.mcpTestResults.length > 0" class="mcp-test-result">
      <h3 class="section-title">测试结果</h3>
      <el-table :data="store.mcpTestResults" size="small">
        <el-table-column prop="name" label="服务器" min-width="160">
          <template #default="{ row }">
            <span class="mono">{{ row.name }}</span>
          </template>
        </el-table-column>

        <el-table-column label="结果" width="92">
          <template #default="{ row }">
            <el-tag size="small" :type="row.ok ? 'success' : 'danger'" effect="plain">
              {{ row.ok ? '正常' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="工具" min-width="220">
          <template #default="{ row }">
            <template v-if="row.ok && row.tools.length > 0">
              <el-tag
                v-for="tool in row.tools"
                :key="mcpToolLabel(tool)"
                size="small"
                effect="plain"
                class="mcp-tool-tag"
              >
                {{ mcpToolLabel(tool) }}
              </el-tag>
            </template>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>

        <el-table-column label="错误" min-width="220">
          <template #default="{ row }">
            <span v-if="row.error" class="mcp-test-result__error">{{ row.error }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>
