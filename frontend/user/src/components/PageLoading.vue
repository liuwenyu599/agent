<template>
  <div class="page-loading" v-if="visible">
    <el-icon class="loading-icon" :size="48"><Loading /></el-icon>
    <p class="loading-text">{{ text }}</p>
  </div>
</template>
<script setup>
import { Loading } from '@element-plus/icons-vue'
defineProps({ visible: { type: Boolean, default: false }, text: { type: String, default: '加载中...' } })
</script>
<style scoped>
.page-loading { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(255,255,255,0.9); display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 9999; }
.loading-icon { animation: rotate 1s linear infinite; color: #409EFF; }
.loading-text { margin-top: 16px; color: #606266; font-size: 14px; }
@keyframes rotate { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
</style>
