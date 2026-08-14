<template>
  <div class="not-found">
    <el-result icon="error" title="404" sub-title="抱歉，您访问的页面不存在">
      <template #extra>
        <el-button type="primary" @click="goHome">返回首页</el-button>
      </template>
    </el-result>
  </div>
</template>
<script setup>
import { useRouter } from 'vue-router'
const router = useRouter()
function goHome() { router.push('/chat') }
</script>
<style scoped>.not-found { height: 100vh; display: flex; align-items: center; justify-content: center; }</style>
