<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="surface not-found">
    <el-result icon="warning" title="404" sub-title="页面不存在，或链接已经失效">
      <template #extra>
        <el-button type="primary" @click="router.push('/projects')">返回项目列表</el-button>
      </template>
    </el-result>
  </div>
</template>
