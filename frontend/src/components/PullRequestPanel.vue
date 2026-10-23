<script setup lang="ts">
import type { PullRequest } from '@/api/types'
import { formatDateTime } from '@/utils/datetime'
import { pullRequestProviderMeta, pullRequestStatusMeta } from '@/utils/status'

withDefaults(
  defineProps<{
    pullRequests: PullRequest[]
    loading?: boolean
  }>(),
  {
    loading: false,
  },
)

function shortSha(value: string | null): string {
  return value ? value.slice(0, 8) : '-'
}
</script>

<template>
  <section v-if="loading || pullRequests.length > 0" v-loading="loading" class="surface">
    <header class="section-head">
      <h2 class="section-title">Pull Request</h2>
      <span class="muted">{{ pullRequests.length }} 个</span>
    </header>

    <div class="pr-list">
      <div v-for="pullRequest in pullRequests" :key="pullRequest.id" class="pr-item">
        <div class="pr-item__main">
          <el-tag
            size="small"
            effect="plain"
            :type="pullRequestProviderMeta(pullRequest.provider).type"
          >
            {{ pullRequestProviderMeta(pullRequest.provider).label }}
          </el-tag>
          <span class="pr-item__number mono">#{{ pullRequest.number }}</span>
          <el-tag
            size="small"
            effect="plain"
            :type="pullRequestStatusMeta(pullRequest.status).type"
          >
            {{ pullRequestStatusMeta(pullRequest.status).label }}
          </el-tag>
          <span v-if="pullRequest.repo_full_name" class="muted">
            {{ pullRequest.repo_full_name }}
          </span>
        </div>

        <div class="pr-item__meta">
          <span class="mono">{{ pullRequest.branch }} → {{ pullRequest.base_branch }}</span>
          <span>head {{ shortSha(pullRequest.head_sha) }}</span>
          <span>创建 {{ formatDateTime(pullRequest.created_at) }}</span>
        </div>

        <a
          v-if="pullRequest.url"
          class="pr-item__link"
          :href="pullRequest.url"
          target="_blank"
          rel="noopener"
        >
          {{ pullRequest.url }}
        </a>
      </div>
    </div>
  </section>
</template>
