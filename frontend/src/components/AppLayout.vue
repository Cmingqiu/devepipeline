<script setup lang="ts">
import { computed } from 'vue'

import { RouterLink, useRoute } from 'vue-router'

const route = useRoute()

const isProjectsActive = computed(
  () => route.path === '/projects' || route.path.startsWith('/requirements') || route.path.startsWith('/projects'),
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
        </nav>

        <el-tag class="app-phase" type="info" effect="plain" size="small">M1 · 需求管理</el-tag>
      </div>
    </header>

    <main class="app-main">
      <div class="app-container">
        <slot />
      </div>
    </main>
  </div>
</template>
