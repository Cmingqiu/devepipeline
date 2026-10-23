<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'

import { getProject } from '@/api/projects'
import AgentDocEditor from '@/components/AgentDocEditor.vue'
import McpPanel from '@/components/McpPanel.vue'
import ModelPanel from '@/components/ModelPanel.vue'
import RepoPanel from '@/components/RepoPanel.vue'
import SkillPanel from '@/components/SkillPanel.vue'
import { useContextStore } from '@/stores/context'
import { getErrorMessage } from '@/utils/feedback'

const route = useRoute()
const store = useContextStore()

const projectId = computed(() => Number(route.params.projectId))
const projectName = ref('')
const activeTab = ref('agents')
const tabsKey = computed(() => `project-settings-${projectId.value}`)

onMounted(() => {
  loadProject()
})

watch(projectId, () => {
  store.reset()
  activeTab.value = 'agents'
  loadProject()
})

function loadProject(): void {
  if (!Number.isFinite(projectId.value) || projectId.value <= 0) {
    return
  }
  getProject(projectId.value)
    .then((project) => {
      projectName.value = project.name
    })
    .catch((err) => {
      projectName.value = ''
      ElMessage.error(getErrorMessage(err, '加载项目信息失败'))
    })
}
</script>

<template>
  <div class="page">
    <el-breadcrumb class="crumbs" separator="/">
      <el-breadcrumb-item :to="{ path: '/projects' }">项目</el-breadcrumb-item>
      <el-breadcrumb-item :to="{ name: 'requirements', params: { projectId } }">
        {{ projectName || `项目 #${projectId}` }}
      </el-breadcrumb-item>
      <el-breadcrumb-item>设置</el-breadcrumb-item>
    </el-breadcrumb>

    <header class="page-head">
      <div class="page-head__text">
        <h1 class="page-title">项目设置</h1>
        <p class="page-subtitle">
          配置 AGENTS.md、技能包、MCP 服务器、模型与仓库凭证；修改会用于后续流水线运行。
        </p>
      </div>
    </header>

    <el-tabs :key="tabsKey" v-model="activeTab" class="settings-tabs">
      <el-tab-pane label="AGENTS.md" name="agents" lazy>
        <AgentDocEditor :project-id="projectId" />
      </el-tab-pane>

      <el-tab-pane label="Skills" name="skills" lazy>
        <SkillPanel :project-id="projectId" />
      </el-tab-pane>

      <el-tab-pane label="MCP" name="mcp" lazy>
        <McpPanel :project-id="projectId" />
      </el-tab-pane>

      <el-tab-pane label="模型" name="model" lazy>
        <ModelPanel :project-id="projectId" />
      </el-tab-pane>

      <el-tab-pane label="仓库与凭证" name="repo" lazy>
        <RepoPanel :project-id="projectId" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
