<template>
  <AppLayout v-if="!isLoginPage">
    <router-view />
  </AppLayout>
  <template v-else>
    <router-view />
  </template>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'

const route = useRoute()
const isLoginPage = computed(() => route.path === '/login')
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; color: #303133; background: #f5f7fa; }
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #f1f1f1; border-radius: 3px; }
::-webkit-scrollbar-thumb { background: #c0c4cc; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #909399; }
.el-button { font-weight: 500; }
.el-card { border-radius: 8px; }
.el-dialog { border-radius: 12px; }
</style>
