<template>
  <el-container class="app-layout">
    <el-aside width="220px" class="sidebar">
      <div class="logo">
        <el-icon :size="28"><OfficeBuilding /></el-icon>
        <span>白云司法智能写作助手</span>
      </div>
      <el-menu :default-active="activeMenu" router class="sidebar-menu"
        background-color="transparent" text-color="#b0c4de" active-text-color="#ffffff">
        <el-menu-item index="/dashboard">
          <el-icon><HomeFilled /></el-icon><span>首页</span>
        </el-menu-item>
        <el-menu-item index="/chat">
          <el-icon><ChatLineRound /></el-icon><span>智能写作</span>
        </el-menu-item>
        <el-menu-item index="/templates">
          <el-icon><DocumentCopy /></el-icon><span>写作模板</span>
        </el-menu-item>
        <el-menu-item index="/knowledge">
          <el-icon><Collection /></el-icon><span>知识库</span>
        </el-menu-item>
        <el-menu-item index="/admin" v-if="isAdmin">
          <el-icon><Setting /></el-icon><span>管理后台</span>
        </el-menu-item>
      </el-menu>
      <div class="sidebar-footer">
        <div class="user-info">
          <el-avatar :size="32" :icon="UserFilled" />
          <div class="user-meta">
            <div class="user-name">{{ userName }}</div>
            <div class="user-role">{{ userRole }}</div>
          </div>
        </div>
        <el-button link size="small" @click="logout">
          <el-icon><SwitchButton /></el-icon> 退出
        </el-button>
      </div>
    </el-aside>
    <el-main class="main-content">
      <!-- 去掉 Transition，避免异步组件加载时白屏 -->
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { HomeFilled, ChatLineRound, DocumentCopy, Collection, Setting, UserFilled, SwitchButton, OfficeBuilding } from '@element-plus/icons-vue'

const route = useRoute(), router = useRouter()
const activeMenu = computed(() => route.path)

const isAdmin = computed(() => {
  try {
    const userStr = localStorage.getItem('user')
    if (!userStr) return false
    const user = JSON.parse(userStr)
    return ['developer', 'knowledge_admin', 'admin'].includes(user?.role)
  } catch { return false }
})

const userName = computed(() => {
  try { const user = JSON.parse(localStorage.getItem('user') || '{}'); return user.real_name || user.username || '用户' } catch { return '用户' }
})

const userRole = computed(() => {
  try {
    const user = JSON.parse(localStorage.getItem('user') || '{}')
    const map = { developer: '系统管理员', knowledge_admin: '知识管理员', admin: '管理员', user: '普通用户' }
    return map[user.role] || user.role || ''
  } catch { return '' }
})

function logout() {
  localStorage.removeItem('token'); localStorage.removeItem('user')
  ElMessage.success('已退出登录'); router.push('/login')
}
</script>

<style scoped>
.app-layout { height: 100vh; overflow: hidden; }
.sidebar { background: linear-gradient(180deg, #1a5fb4 0%, #1c4587 100%); display: flex; flex-direction: column; color: white; }
.logo { height: 64px; display: flex; align-items: center; gap: 12px; padding: 0 20px; font-size: 16px; font-weight: 600; border-bottom: 1px solid rgba(255,255,255,0.1); }
.sidebar-menu { flex: 1; border-right: none; padding: 12px 0; }
.sidebar-menu :deep(.el-menu-item) { height: 48px; line-height: 48px; margin: 4px 12px; border-radius: 8px; }
.sidebar-menu :deep(.el-menu-item:hover) { background: rgba(255,255,255,0.1) !important; }
.sidebar-menu :deep(.el-menu-item.is-active) { background: rgba(255,255,255,0.2) !important; font-weight: 600; }
.sidebar-footer { padding: 16px; border-top: 1px solid rgba(255,255,255,0.1); }
.user-info { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.user-meta { flex: 1; overflow: hidden; }
.user-name { font-size: 14px; font-weight: 500; color: white; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.user-role { font-size: 12px; color: rgba(255,255,255,0.6); }
.sidebar-footer .el-button { color: rgba(255,255,255,0.7); width: 100%; justify-content: center; }
.main-content { padding: 0; background: #f0f2f5; overflow-y: auto; }
</style>
