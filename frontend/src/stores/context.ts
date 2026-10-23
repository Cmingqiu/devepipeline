import { computed, ref } from 'vue'

import { defineStore } from 'pinia'

import * as contextsApi from '@/api/contexts'
import type {
  AgentDoc,
  AgentDocVersion,
  Credential,
  CredentialCreatePayload,
  McpServer,
  McpServerInput,
  McpTestResult,
  RepoConfig,
  RepoTestResult,
  RepoUpdatePayload,
  Skill,
  SkillDetail,
  SkillFileContent,
} from '@/api/contexts'

export const useContextStore = defineStore('context', () => {
  // ---------- AGENTS.md ----------
  const agentDoc = ref<AgentDoc | null>(null)
  const agentDocLoading = ref(false)
  const agentSaving = ref(false)
  const agentVersions = ref<AgentDocVersion[]>([])
  const agentVersionsLoading = ref(false)

  // ---------- Skills ----------
  const skills = ref<Skill[]>([])
  const skillsLoading = ref(false)
  const skillUploading = ref(false)
  const skillDetail = ref<SkillDetail | null>(null)
  const skillDetailLoading = ref(false)
  const skillFileLoading = ref(false)

  // ---------- MCP ----------
  const mcpServers = ref<McpServer[]>([])
  const mcpLoading = ref(false)
  const mcpSaving = ref(false)
  const mcpTesting = ref(false)
  const mcpTestResults = ref<McpTestResult[]>([])

  // ---------- 仓库与凭证 ----------
  const repo = ref<RepoConfig | null>(null)
  const repoLoading = ref(false)
  const repoSaving = ref(false)
  const repoTesting = ref(false)
  const repoTestResult = ref<RepoTestResult | null>(null)

  const credentials = ref<Credential[]>([])
  const credentialsLoading = ref(false)
  const credentialSubmitting = ref(false)

  const agentConfigured = computed(() => agentDoc.value !== null)
  const skillIsEmpty = computed(() => !skillsLoading.value && skills.value.length === 0)
  const credentialIsEmpty = computed(
    () => !credentialsLoading.value && credentials.value.length === 0,
  )

  async function fetchAgentDoc(projectId: number): Promise<AgentDoc | null> {
    agentDocLoading.value = true
    try {
      const doc = await contextsApi.getAgentDoc(projectId)
      agentDoc.value = doc
      return doc
    } finally {
      agentDocLoading.value = false
    }
  }

  async function saveAgentDoc(projectId: number, content: string): Promise<AgentDoc> {
    agentSaving.value = true
    try {
      const doc = await contextsApi.saveAgentDoc(projectId, content)
      agentDoc.value = doc
      await fetchAgentVersions(projectId).catch(() => undefined)
      return doc
    } finally {
      agentSaving.value = false
    }
  }

  async function fetchAgentVersions(projectId: number): Promise<void> {
    agentVersionsLoading.value = true
    try {
      agentVersions.value = await contextsApi.listAgentDocVersions(projectId)
    } finally {
      agentVersionsLoading.value = false
    }
  }

  async function fetchSkills(projectId: number): Promise<void> {
    skillsLoading.value = true
    try {
      skills.value = await contextsApi.listSkills(projectId)
    } finally {
      skillsLoading.value = false
    }
  }

  async function uploadSkill(projectId: number, file: File): Promise<SkillDetail> {
    skillUploading.value = true
    try {
      const skill = await contextsApi.uploadSkill(projectId, file)
      await fetchSkills(projectId).catch(() => undefined)
      return skill
    } finally {
      skillUploading.value = false
    }
  }

  async function loadSkill(projectId: number, skillId: number): Promise<SkillDetail> {
    skillDetailLoading.value = true
    try {
      const detail = await contextsApi.getSkill(projectId, skillId)
      skillDetail.value = detail
      return detail
    } finally {
      skillDetailLoading.value = false
    }
  }

  async function loadSkillFile(
    projectId: number,
    skillId: number,
    path: string,
  ): Promise<SkillFileContent> {
    skillFileLoading.value = true
    try {
      return await contextsApi.getSkillFile(projectId, skillId, path)
    } finally {
      skillFileLoading.value = false
    }
  }

  async function removeSkill(projectId: number, skillId: number): Promise<void> {
    await contextsApi.deleteSkill(projectId, skillId)
    if (skillDetail.value?.id === skillId) {
      skillDetail.value = null
    }
    await fetchSkills(projectId)
  }

  function clearSkillDetail(): void {
    skillDetail.value = null
  }

  async function fetchMcpServers(projectId: number): Promise<McpServer[]> {
    mcpLoading.value = true
    try {
      mcpServers.value = await contextsApi.listMcpServers(projectId)
      return mcpServers.value
    } finally {
      mcpLoading.value = false
    }
  }

  async function saveMcpServers(
    projectId: number,
    servers: McpServerInput[],
  ): Promise<McpServer[]> {
    mcpSaving.value = true
    try {
      mcpServers.value = await contextsApi.saveMcpServers(projectId, servers)
      return mcpServers.value
    } finally {
      mcpSaving.value = false
    }
  }

  async function testMcpServers(
    projectId: number,
    servers?: McpServerInput[],
  ): Promise<McpTestResult[]> {
    mcpTesting.value = true
    try {
      mcpTestResults.value = await contextsApi.testMcpServers(projectId, servers)
      return mcpTestResults.value
    } finally {
      mcpTesting.value = false
    }
  }

  async function fetchRepo(projectId: number): Promise<RepoConfig> {
    repoLoading.value = true
    try {
      const config = await contextsApi.getRepo(projectId)
      repo.value = config
      return config
    } finally {
      repoLoading.value = false
    }
  }

  async function saveRepo(projectId: number, payload: RepoUpdatePayload): Promise<RepoConfig> {
    repoSaving.value = true
    try {
      const config = await contextsApi.saveRepo(projectId, payload)
      repo.value = config
      return config
    } finally {
      repoSaving.value = false
    }
  }

  async function testRepo(projectId: number): Promise<RepoTestResult> {
    repoTesting.value = true
    try {
      const result = await contextsApi.testRepo(projectId)
      repoTestResult.value = result
      return result
    } finally {
      repoTesting.value = false
    }
  }

  async function fetchCredentials(projectId: number): Promise<void> {
    credentialsLoading.value = true
    try {
      credentials.value = await contextsApi.listCredentials(projectId)
    } finally {
      credentialsLoading.value = false
    }
  }

  async function createCredential(
    projectId: number,
    payload: CredentialCreatePayload,
  ): Promise<Credential> {
    credentialSubmitting.value = true
    try {
      const credential = await contextsApi.createCredential(projectId, payload)
      await fetchCredentials(projectId).catch(() => undefined)
      await fetchRepo(projectId).catch(() => undefined)
      return credential
    } finally {
      credentialSubmitting.value = false
    }
  }

  async function removeCredential(projectId: number, credentialId: number): Promise<void> {
    await contextsApi.deleteCredential(projectId, credentialId)
    await fetchCredentials(projectId)
    await fetchRepo(projectId).catch(() => undefined)
  }

  function reset(): void {
    agentDoc.value = null
    agentVersions.value = []
    skills.value = []
    skillDetail.value = null
    mcpServers.value = []
    mcpTestResults.value = []
    repo.value = null
    repoTestResult.value = null
    credentials.value = []
  }

  return {
    agentDoc,
    agentDocLoading,
    agentSaving,
    agentVersions,
    agentVersionsLoading,
    skills,
    skillsLoading,
    skillUploading,
    skillDetail,
    skillDetailLoading,
    skillFileLoading,
    mcpServers,
    mcpLoading,
    mcpSaving,
    mcpTesting,
    mcpTestResults,
    repo,
    repoLoading,
    repoSaving,
    repoTesting,
    repoTestResult,
    credentials,
    credentialsLoading,
    credentialSubmitting,
    agentConfigured,
    skillIsEmpty,
    credentialIsEmpty,
    fetchAgentDoc,
    saveAgentDoc,
    fetchAgentVersions,
    fetchSkills,
    uploadSkill,
    loadSkill,
    loadSkillFile,
    removeSkill,
    clearSkillDetail,
    fetchMcpServers,
    saveMcpServers,
    testMcpServers,
    fetchRepo,
    saveRepo,
    testRepo,
    fetchCredentials,
    createCredential,
    removeCredential,
    reset,
  }
})
