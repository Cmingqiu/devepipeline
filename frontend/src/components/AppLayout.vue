<script setup lang="ts">
import { computed } from 'vue'

import { RouterLink, useRoute } from 'vue-router'

const route = useRoute()

const isProjectsActive = computed(
  () =>
    route.path === '/projects' ||
    route.path.startsWith('/projects/') ||
    route.path.startsWith('/requirements'),
)

const isRunsActive = computed(
  () => route.path === '/runs' || route.path.startsWith('/runs/'),
)
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="app-header__inner">
        <RouterLink class="app-brand" to="/projects">
          <span class="app-brand__mark">DP</span>
          <span class="app-brand__name">DevPipeline</span>
        </RouterLink>

        <nav class="app-nav" aria-label="主导航">
          <RouterLink class="app-nav__link" :class="{ 'is-active': isProjectsActive }" to="/projects">
            项目
          </RouterLink>
          <RouterLink class="app-nav__link" :class="{ 'is-active': isRunsActive }" to="/runs">
            运行
          </RouterLink>
        </nav>

        <el-tag class="app-phase" type="info" effect="plain" size="small">M2 · 流水线与审批</el-tag>
      </div>
    </header>

    <main class="app-main">
      <div class="app-container">
        <slot />
      </div>
    </main>
  </div>
</template>
