<template>
  <div v-if="hasError" class="error-fallback">
    <el-result icon="error" title="出错了" :sub-title="errorMessage">
      <template #extra>
        <el-button type="primary" @click="reload">刷新页面</el-button>
        <el-button @click="goHome">返回首页</el-button>
      </template>
    </el-result>
  </div>
  <slot v-else />
</template>
<script setup>
import { ref, onErrorCaptured } from 'vue'
import { useRouter } from 'vue-router'
const router = useRouter()
const hasError = ref(false)
const errorMessage = ref('')
onErrorCaptured((err) => { hasError.value = true; errorMessage.value = err.message || '未知错误'; console.error('全局错误:', err); return false })
function reload() { window.location.reload() }
function goHome() { hasError.value = false; router.push('/chat') }
</script>
<style scoped>.error-fallback { height: 100vh; display: flex; align-items: center; justify-content: center; }</style>
