<template>
  <div class="dashboard-page">
    <!-- 顶部 Banner -->
    <div class="banner">
      <div class="banner-left">
        <h1>欢迎使用司法智能办公平台</h1>
        <p>AI 赋能办公，让工作更高效、更智能</p>
        <el-button type="primary" size="large" class="banner-btn" @click="goToChat">
          开始智能写作 <el-icon style="margin-left:6px"><Right /></el-icon>
        </el-button>
      </div>
      <div class="banner-right">
        <el-icon :size="120" class="banner-deco"><Monitor /></el-icon>
      </div>
    </div>

    <el-row :gutter="20" class="main-row">
      <!-- 左侧主区域 -->
      <el-col :span="16">
        <!-- 快速入口 -->
        <el-card shadow="never" class="section-card">
          <template #header>
            <div class="section-header">快速入口</div>
          </template>
          <div class="quick-grid">
            <div
              v-for="item in quickEntries"
              :key="item.name"
              class="quick-item"
              :class="{ disabled: item.disabled }"
              @click="onQuickEntry(item)"
            >
              <div class="quick-icon" :style="{ background: item.bg, color: item.color }">
                <el-icon :size="26"><component :is="item.icon" /></el-icon>
              </div>
              <div class="quick-name">{{ item.name }}</div>
              <div class="quick-desc">{{ item.desc }}</div>
            </div>
          </div>
        </el-card>

        <!-- 最近文档 + 消息通知 -->
        <el-row :gutter="20" style="margin-top: 20px">
          <el-col :span="12">
            <el-card shadow="never" class="section-card">
              <template #header>
                <div class="section-header">
                  最近文档
                  <el-link type="primary" class="more-link" @click="router.push('/knowledge')">全部 &gt;</el-link>
                </div>
              </template>
              <div v-if="recentDocs.length > 0" class="doc-list">
                <div v-for="doc in recentDocs" :key="doc.id" class="doc-item">
                  <el-icon class="doc-icon" color="#2b6cb0"><Document /></el-icon>
                  <div class="doc-info">
                    <div class="doc-title">{{ doc.title }}</div>
                    <div class="doc-meta">更新时间：{{ doc.time }}<span v-if="doc.kb_name">　来源：{{ doc.kb_name }}</span></div>
                  </div>
                </div>
              </div>
              <el-empty v-else description="暂无文档，可前往知识库上传" :image-size="70" />
            </el-card>
          </el-col>
          <el-col :span="12">
            <el-card shadow="never" class="section-card">
              <template #header>
                <div class="section-header">
                  消息通知
                  <el-link type="primary" class="more-link" disabled>全部已读</el-link>
                </div>
              </template>
              <div class="notice-list">
                <div v-for="(n, i) in notices" :key="i" class="notice-item">
                  <el-avatar :size="30" :icon="n.icon" :style="{ background: n.color }" />
                  <div class="notice-info">
                    <div class="notice-title">{{ n.title }}</div>
                    <div class="notice-time">{{ n.time }}</div>
                  </div>
                </div>
              </div>
            </el-card>
          </el-col>
        </el-row>
      </el-col>

      <!-- 右侧栏 -->
      <el-col :span="8">
        <!-- 我的工作流 -->
        <el-card shadow="never" class="section-card">
          <template #header>
            <div class="section-header">
              我的工作流
              <el-link type="primary" class="more-link" disabled>全部 &gt;</el-link>
            </div>
          </template>
          <div class="workflow-list">
            <div v-for="wf in workflows" :key="wf.name" class="workflow-item">
              <div class="workflow-head">
                <span class="workflow-name">{{ wf.name }}</span>
                <el-tag size="small" :type="wf.statusType" effect="light">{{ wf.status }}</el-tag>
              </div>
              <div class="workflow-meta">{{ wf.type }} ｜ 更新于 {{ wf.time }}</div>
            </div>
          </div>
          <div class="workflow-tip">工作流功能开发中，以上为示例数据</div>
        </el-card>

        <!-- 常用模板 -->
        <el-card shadow="never" class="section-card" style="margin-top: 20px">
          <template #header>
            <div class="section-header">
              常用模板
              <el-link type="primary" class="more-link" @click="router.push('/templates')">全部 &gt;</el-link>
            </div>
          </template>
          <div v-if="templates.length > 0" class="tpl-list">
            <div v-for="t in templates" :key="t.id" class="tpl-item" @click="useTemplate(t)">
              <el-icon class="tpl-icon" color="#e6a23c"><DocumentCopy /></el-icon>
              <div class="tpl-info">
                <div class="tpl-name">{{ t.name }}</div>
                <div class="tpl-desc">{{ t.description || t.category }}</div>
              </div>
              <el-tag size="small" effect="plain" type="primary">{{ t.category }}</el-tag>
            </div>
          </div>
          <el-empty v-else description="暂无模板" :image-size="70" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Right, Monitor, Document, DocumentCopy, Bell, CircleCheck,
  ChatLineRound, Collection, Share, DataAnalysis, UserFilled
} from '@element-plus/icons-vue'
import axios from 'axios'

const router = useRouter()

// ===== 快速入口（与效果图一致；未上线功能点击提示） =====
const quickEntries = ref([
  { name: '信息写作', desc: '自由对话写作', icon: 'ChatLineRound', bg: '#e8f0fe', color: '#2b6cb0', path: '/chat' },
  { name: '公文助手', desc: '文种模板写作', icon: 'DocumentCopy', bg: '#f3eafd', color: '#7c5cd6', path: '/templates' },
  { name: '知识库', desc: '检索与问答', icon: 'Collection', bg: '#e6f7ee', color: '#38a169', path: '/knowledge' },
  { name: '工作流', desc: '任务全流程管理', icon: 'Share', bg: '#fdeee4', color: '#dd6b20', disabled: true },
  { name: '智能PPT', desc: '生成汇报PPT', icon: 'DataAnalysis', bg: '#e3f2fd', color: '#3182ce', disabled: true },
  { name: '格式校验', desc: '文档格式检查', icon: 'CircleCheck', bg: '#e6fffa', color: '#2c9a8a', path: '/format-check' },
])

function onQuickEntry(item) {
  if (item.disabled) {
    ElMessage.info(`「${item.name}」将在后续版本开放`)
    return
  }
  router.push(item.path)
}

// ===== 我的工作流（示例数据，P2 工作流框架上线后接真实接口） =====
const workflows = ref([
  { name: '2026年司法行政工作会议', type: '会议工作流', time: '2026-08-01 14:30', status: '进行中', statusType: 'primary' },
  { name: '社区矫正宣传活动', type: '活动工作流', time: '2026-07-30 10:20', status: '进行中', statusType: 'success' },
  { name: '基层调研工作任务', type: '调研工作流', time: '2026-07-28 16:45', status: '草稿', statusType: 'warning' },
  { name: '年度工作汇报材料', type: '汇报工作流', time: '2026-07-25 09:15', status: '已完成', statusType: 'info' },
])

// ===== 消息通知（示例数据） =====
const notices = ref([
  { title: '欢迎使用司法智能办公平台，信息写作已支持参考模板', time: '刚刚', icon: 'Bell', color: '#2b6cb0' },
  { title: '文档格式校验能力已上线，可在办公工具中使用', time: '1天前', icon: 'CircleCheck', color: '#38a169' },
  { title: '系统公告：请勿在材料中填写涉密信息', time: '3天前', icon: 'UserFilled', color: '#dd6b20' },
])

// ===== 常用模板（真实接口） =====
const templates = ref([])
const recentDocs = ref([])

onMounted(() => {
  loadTemplates()
  loadRecentDocs()
})

async function loadTemplates() {
  try {
    const token = localStorage.getItem('token')
    const res = await axios.get('/api/v1/templates/', {
      headers: { Authorization: `Bearer ${token}` }
    })
    templates.value = (res.data || [])
      .sort((a, b) => (b.use_count || 0) - (a.use_count || 0))
      .slice(0, 4)
  } catch (e) { console.error('加载模板失败', e) }
}

async function loadRecentDocs() {
  // 普通用户无全局"最近文档"接口，这里从可访问知识库的已发布文档中取最新几条
  try {
    const token = localStorage.getItem('token')
    const headers = { Authorization: `Bearer ${token}` }
    const kbRes = await axios.get('/api/v1/knowledge/list', { headers })
    const kbs = kbRes.data || []
    const docs = []
    for (const kb of kbs.slice(0, 3)) {
      try {
        const dRes = await axios.get(`/api/v1/knowledge/${kb.id}/documents`, {
          headers, params: { page: 1, page_size: 3 }
        })
        for (const d of (dRes.data?.data || [])) {
          docs.push({ id: d.id, title: d.title, time: formatTime(d.created_at), kb_name: kb.name })
        }
      } catch { /* 单个库失败不影响整体 */ }
    }
    recentDocs.value = docs.slice(0, 4)
  } catch (e) { console.error('加载最近文档失败', e) }
}

function formatTime(d) {
  if (!d) return ''
  const date = new Date(d)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function goToChat() { router.push('/chat') }
function useTemplate(t) { router.push({ path: '/templates', query: { use: t.id } }) }
</script>

<style scoped>
.dashboard-page { min-height: 100vh; background: #f3f5f9; padding: 20px; }

/* ===== Banner ===== */
.banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 36px 48px;
  border-radius: 10px;
  background: linear-gradient(120deg, #1c4f9e 0%, #2b6cb0 60%, #3182ce 100%);
  color: white;
  margin-bottom: 20px;
  overflow: hidden;
}
.banner h1 { margin: 0 0 10px; font-size: 26px; font-weight: 700; }
.banner p { margin: 0 0 22px; font-size: 14px; opacity: 0.85; }
.banner-btn { background: #1a73e8; border-color: #1a73e8; }
.banner-right { opacity: 0.25; }
.banner-deco { color: #fff; }

/* ===== 卡片通用 ===== */
.section-card { border-radius: 10px; border: 1px solid #edf0f5; }
.section-card :deep(.el-card__header) { padding: 14px 20px; border-bottom: 1px solid #f2f4f8; }
.section-header {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 15px; font-weight: 600; color: #303133;
}
.more-link { font-size: 12px; font-weight: 400; }

/* ===== 快速入口 ===== */
.quick-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
}
.quick-item { text-align: center; cursor: pointer; padding: 14px 6px; border-radius: 8px; transition: background 0.2s; }
.quick-item:hover { background: #f7f9fc; }
.quick-item.disabled { cursor: default; opacity: 0.6; }
.quick-icon {
  width: 52px; height: 52px; border-radius: 12px; margin: 0 auto 10px;
  display: flex; align-items: center; justify-content: center;
}
.quick-name { font-size: 14px; font-weight: 600; color: #303133; }
.quick-desc { font-size: 12px; color: #909399; margin-top: 2px; }

/* ===== 最近文档 ===== */
.doc-list { padding: 4px 0; }
.doc-item { display: flex; gap: 10px; padding: 10px 0; border-bottom: 1px solid #f2f4f8; }
.doc-item:last-child { border-bottom: none; }
.doc-icon { margin-top: 3px; flex-shrink: 0; }
.doc-title { font-size: 13px; color: #303133; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.doc-meta { font-size: 12px; color: #a0a5ad; margin-top: 3px; }

/* ===== 消息通知 ===== */
.notice-list { padding: 4px 0; }
.notice-item { display: flex; gap: 10px; padding: 10px 0; border-bottom: 1px solid #f2f4f8; }
.notice-item:last-child { border-bottom: none; }
.notice-title { font-size: 13px; color: #303133; }
.notice-time { font-size: 12px; color: #a0a5ad; margin-top: 3px; }

/* ===== 我的工作流 ===== */
.workflow-list { padding: 4px 0; }
.workflow-item { padding: 10px 0; border-bottom: 1px solid #f2f4f8; }
.workflow-item:last-child { border-bottom: none; }
.workflow-head { display: flex; justify-content: space-between; align-items: center; }
.workflow-name { font-size: 13px; font-weight: 500; color: #303133; }
.workflow-meta { font-size: 12px; color: #a0a5ad; margin-top: 4px; }
.workflow-tip {
  margin-top: 10px; padding-top: 8px; border-top: 1px dashed #e8ecf1;
  font-size: 12px; color: #c0c4cc; text-align: center;
}

/* ===== 常用模板 ===== */
.tpl-list { padding: 4px 0; }
.tpl-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 0; border-bottom: 1px solid #f2f4f8; cursor: pointer;
}
.tpl-item:last-child { border-bottom: none; }
.tpl-item:hover .tpl-name { color: #2b6cb0; }
.tpl-icon { flex-shrink: 0; }
.tpl-info { flex: 1; min-width: 0; }
.tpl-name { font-size: 13px; font-weight: 500; color: #303133; }
.tpl-desc {
  font-size: 12px; color: #a0a5ad; margin-top: 2px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

@media (max-width: 1280px) {
  .quick-grid { grid-template-columns: repeat(3, 1fr); }
}
</style>