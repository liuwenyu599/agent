<template>
  <el-container class="app-layout">
    <el-aside :width="collapsed ? '64px' : '220px'" class="sidebar">
      <div class="logo" v-if="!collapsed">
        <el-icon :size="26"><OfficeBuilding /></el-icon>
        <div class="logo-text">
          <span>司法智能办公平台</span>
          <span class="logo-sub">智能 · 高效 · 安全</span>
        </div>
      </div>
      <div class="logo" v-else>
        <el-icon :size="26"><OfficeBuilding /></el-icon>
      </div>

      <el-menu :default-active="activeMenu" router :collapse="collapsed" class="sidebar-menu"
        background-color="transparent" text-color="#b0c4de" active-text-color="#ffffff">
        <el-menu-item index="/dashboard">
          <el-icon><HomeFilled /></el-icon><span>首页</span>
        </el-menu-item>

        <el-sub-menu index="writing">
          <template #title><el-icon><ChatLineRound /></el-icon><span>智能写作</span></template>
          <el-menu-item index="/chat">信息写作</el-menu-item>
          <el-menu-item index="/templates">公文助手</el-menu-item>
          <el-menu-item index="/knowledge">知识库</el-menu-item>
        </el-sub-menu>

        <el-menu-item index="/workflows">
          <el-icon><Share /></el-icon><span>工作流</span>
        </el-menu-item>

        <el-menu-item index="/ppt">
          <el-icon><Film /></el-icon><span>PPT助手</span>
        </el-menu-item>

        <el-menu-item index="/format-check">
          <el-icon><CircleCheck /></el-icon><span>格式校验</span>
        </el-menu-item>

        <el-menu-item index="/admin" v-if="isAdmin">
          <el-icon><Setting /></el-icon><span>管理后台</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-footer" v-if="!collapsed">
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

    <el-container>
      <el-header class="topbar" height="56px">
        <el-button text @click="collapsed = !collapsed">
          <el-icon><Fold v-if="!collapsed" /><Expand v-else /></el-icon>
        </el-button>
        <span class="page-title">{{ pageTitle }}</span>
        <div class="topbar-right">
          <el-badge :value="0" :hidden="true"><el-icon :size="18"><Bell /></el-icon></el-badge>
          <el-dropdown @command="onUserCmd">
            <span class="topbar-user">
              <el-avatar :size="28" :icon="UserFilled" /> {{ userName }}
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="main-content">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  OfficeBuilding, HomeFilled, ChatLineRound, Share, CircleCheck,
  Setting, UserFilled, SwitchButton, Fold, Expand, Bell, Film,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const collapsed = ref(false)

const activeMenu = computed(() =>
  route.path.startsWith('/workflows') ? '/workflows' : route.path)

const TITLES = {
  '/dashboard': '首页', '/chat': '信息写作', '/templates': '公文助手',
  '/knowledge': '知识库', '/workflows': '工作流', '/ppt': 'PPT助手',
  '/format-check': '格式校验', '/admin': '管理后台',
}
const pageTitle = computed(() =>
  route.path.startsWith('/workflows/') && route.path !== '/workflows'
    ? '工作流详情'
    : TITLES[route.path] || '')

const isAdmin = computed(() => {
  try {
    const user = JSON.parse(localStorage.getItem('user') || 'null')
    return ['developer', 'knowledge_admin', 'admin'].includes(user?.role)
  } catch { return false }
})

const userName = computed(() => {
  try {
    const user = JSON.parse(localStorage.getItem('user') || '{}')
    return user.real_name || user.username || '用户'
  } catch { return '用户' }
})

const userRole = computed(() => {
  try {
    const user = JSON.parse(localStorage.getItem('user') || '{}')
    const map = { developer: '系统管理员', knowledge_admin: '知识管理员', admin: '管理员', user: '普通用户' }
    return map[user.role] || user.role || ''
  } catch { return '' }
})

function logout() {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
  ElMessage.success('已退出登录')
  router.push('/login')
}
function onUserCmd(cmd) { if (cmd === 'logout') logout() }
</script>

<style scoped>
.app-layout { height: 100vh; overflow: hidden; }
.sidebar {
  background: #16223f; display: flex; flex-direction: column; color: white;
  transition: width .2s;
}
.logo {
  height: 64px; display: flex; align-items: center; gap: 10px; padding: 0 16px;
  border-bottom: 1px solid rgba(255,255,255,0.08); overflow: hidden;
}
.logo-text { display: flex; flex-direction: column; }
.logo-text span:first-child { font-size: 15px; font-weight: 600; white-space: nowrap; }
.logo-sub { font-size: 11px; color: rgba(255,255,255,0.5); }
.sidebar-menu { flex: 1; border-right: none; padding: 10px 0; }
.sidebar-menu :deep(.el-menu-item), .sidebar-menu :deep(.el-sub-menu__title) {
  height: 44px; line-height: 44px; margin: 2px 10px; border-radius: 8px;
}
.sidebar-menu :deep(.el-sub-menu .el-menu-item) { min-width: 0; padding-left: 48px !important; }
.sidebar-menu :deep(.el-menu-item:hover), .sidebar-menu :deep(.el-sub-menu__title:hover) {
  background: rgba(255,255,255,0.08) !important;
}
.sidebar-menu :deep(.el-menu-item.is-active) {
  background: #2f5cff !important; font-weight: 600;
}
.sidebar-footer { padding: 14px; border-top: 1px solid rgba(255,255,255,0.08); }
.user-info { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.user-meta { flex: 1; overflow: hidden; }
.user-name { font-size: 14px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.user-role { font-size: 12px; color: rgba(255,255,255,0.55); }
.sidebar-footer .el-button { color: rgba(255,255,255,0.7); width: 100%; justify-content: center; }

.topbar {
  background: #fff; border-bottom: 1px solid #ebeef5;
  display: flex; align-items: center; gap: 12px; padding: 0 16px;
}
.page-title { font-size: 15px; font-weight: 600; }
.topbar-right { margin-left: auto; display: flex; align-items: center; gap: 18px; }
.topbar-user { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 14px; }
.main-content { padding: 0; background: #f0f2f5; overflow-y: auto; }
</style>
