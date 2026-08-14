<template>
  <div class="dashboard-page">
    <div class="dashboard-content">
      <div class="welcome-section">
        <div class="welcome-left">
          <h1>欢迎使用白云司法智能写作助手</h1>
          <p>基于大语言模型，为司法行政工作提供智能公文写作支持</p>
        </div>
        <el-button type="primary" size="large" @click="goToChat">
          <el-icon><EditPen /></el-icon> 开始写作
        </el-button>
      </div>

      <el-row :gutter="16" class="stats-row">
        <el-col :span="6" v-for="stat in statsList" :key="stat.label">
          <div class="stat-card" :class="stat.type" @click="stat.action?.()">
            <div class="stat-icon"><el-icon :size="28"><component :is="stat.icon" /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value">{{ stat.value }}</div>
              <div class="stat-label">{{ stat.label }}</div>
            </div>
          </div>
        </el-col>
      </el-row>

      <el-row :gutter="16" class="main-row">
        <el-col :span="16">
          <el-card shadow="never" class="section-card">
            <template #header>
              <div class="section-header"><el-icon><Grid /></el-icon> 快捷入口</div>
            </template>
            <el-row :gutter="16">
              <el-col :span="8" v-for="item in quickEntries" :key="item.name">
                <div class="quick-card" @click="item.action">
                  <div class="quick-icon" :class="item.color">
                    <el-icon :size="28"><component :is="item.icon" /></el-icon>
                  </div>
                  <div class="quick-title">{{ item.name }}</div>
                  <div class="quick-desc">{{ item.desc }}</div>
                </div>
              </el-col>
            </el-row>
          </el-card>

          <el-card shadow="never" class="section-card" style="margin-top: 16px">
            <template #header>
              <div class="section-header"><el-icon><Document /></el-icon> 常用公文类型</div>
            </template>
            <div class="doc-types">
              <div v-for="doc in docTypes" :key="doc.type" class="doc-type-item" @click="startDocWriting(doc.type)">
                <el-icon :size="18"><component :is="doc.icon" /></el-icon>
                <span>{{ doc.name }}</span>
                <el-tag v-if="doc.hot" size="small" type="danger" effect="dark">常用</el-tag>
              </div>
            </div>
          </el-card>
        </el-col>

        <el-col :span="8">
          <el-card shadow="never" class="section-card">
            <template #header>
              <div class="section-header"><el-icon><Timer /></el-icon> 最近动态</div>
            </template>
            <div class="activity-list" v-if="activities.length > 0">
              <div v-for="act in activities" :key="act.id" class="activity-item">
                <div class="activity-dot" :class="act.type"></div>
                <div class="activity-content">
                  <div class="activity-title">{{ act.title }}</div>
                  <div class="activity-time">{{ act.time }}</div>
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无动态" :image-size="60" />
          </el-card>

          <el-card shadow="never" class="section-card" style="margin-top: 16px">
            <template #header>
              <div class="section-header"><el-icon><Cpu /></el-icon> 系统状态</div>
            </template>
            <div class="status-list">
              <div class="status-item"><span>AI 模型</span><el-tag size="small" type="success" effect="dark">运行中</el-tag></div>
              <div class="status-item"><span>知识库</span><span>{{ kbCount }} 个</span></div>
              <div class="status-item"><span>覆盖部门</span><span>{{ deptCount }} 个</span></div>
              <div class="status-item"><span>模型版本</span><span>Qwen2.5-14B</span></div>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  EditPen, Grid, Document, Timer, Cpu,
  ChatLineRound, Collection, DocumentCopy,
  UserFilled, Bell, Calendar, DataLine, Microphone, Files
} from '@element-plus/icons-vue'
import axios from 'axios'

const router = useRouter()

const statsList = ref([
  { label: '今日写作', value: 0, icon: 'EditPen', type: 'blue', action: () => router.push('/chat') },
  { label: '知识库文档', value: 0, icon: 'Collection', type: 'green', action: () => router.push('/knowledge') },
  { label: '写作模板', value: 0, icon: 'DocumentCopy', type: 'orange', action: () => router.push('/templates') },
  { label: '活跃用户', value: 1, icon: 'UserFilled', type: 'purple', action: () => router.push('/admin') }
])

const quickEntries = ref([
  { name: '智能写作', desc: '输入主题，AI自动生成公文', icon: 'ChatLineRound', color: 'blue', action: () => router.push('/chat') },
  { name: '知识库', desc: '管理司法局文档资料', icon: 'Collection', color: 'green', action: () => router.push('/knowledge') },
  { name: '写作模板', desc: '常用公文模板快速套用', icon: 'DocumentCopy', color: 'orange', action: () => router.push('/templates') }
])

const docTypes = ref([
  { name: '通知通报', type: '通知通报', icon: 'Bell', hot: true },
  { name: '请示报告', type: '请示报告', icon: 'Document', hot: true },
  { name: '会议纪要', type: '会议纪要', icon: 'Calendar', hot: true },
  { name: '工作总结', type: '工作总结', icon: 'DataLine', hot: false },
  { name: '领导讲话', type: '领导讲话', icon: 'Microphone', hot: false },
  { name: '调研报告', type: '调研报告', icon: 'Files', hot: false }
])

const activities = ref([])
const kbCount = ref(0)
const deptCount = ref(0)

onMounted(() => { loadStats() })

async function loadStats() {
  try {
    const token = localStorage.getItem('token')
    const tplRes = await axios.get('/api/v1/templates/', { headers: { Authorization: `Bearer ${token}` } })
    statsList.value[2].value = (tplRes.data || []).length
    const kbRes = await axios.get('/api/v1/knowledge/list', { headers: { Authorization: `Bearer ${token}` } })
    const kbs = kbRes.data || []
    kbCount.value = kbs.length
    statsList.value[1].value = kbs.reduce((sum, k) => sum + (k.doc_count || 0), 0)
    const depts = new Set(kbs.map(k => k.department).filter(Boolean))
    deptCount.value = depts.size
  } catch (e) { console.error('加载统计失败', e) }
}

function goToChat() { router.push('/chat') }
function startDocWriting(type) { router.push({ path: '/chat', query: { docType: type } }) }
</script>

<style scoped>
.dashboard-page { min-height: 100vh; background: #f0f2f5; }
.dashboard-content { padding: 24px; }

.welcome-section {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding: 24px 32px;
  background: linear-gradient(135deg, #1a5fb4 0%, #3584e4 100%);
  border-radius: 12px;
  color: white;
}

.welcome-section h1 { margin: 0 0 8px 0; font-size: 22px; }
.welcome-section p { margin: 0; font-size: 14px; opacity: 0.85; }

.stats-row { margin-bottom: 24px; }
.stat-card {
  cursor: pointer;
  background: white;
  border-radius: 12px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  transition: all 0.3s;
}
.stat-card:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.08); }

.stat-icon {
  width: 52px; height: 52px; border-radius: 12px;
  display: flex; align-items: center; justify-content: center;
  background: #f5f7fa; color: #909399;
}
.stat-card.blue .stat-icon { background: #ecf5ff; color: #409EFF; }
.stat-card.green .stat-icon { background: #f0f9eb; color: #67C23A; }
.stat-card.orange .stat-icon { background: #fdf6ec; color: #E6A23C; }
.stat-card.purple .stat-icon { background: #f5f0ff; color: #9254DE; }

.stat-info { flex: 1; }
.stat-value { font-size: 26px; font-weight: 700; color: #303133; line-height: 1; margin-bottom: 6px; }
.stat-label { font-size: 13px; color: #909399; }

.main-row { margin: 0 !important; }
.section-card { border-radius: 12px; }
.section-card :deep(.el-card__header) { padding: 16px 20px; border-bottom: 1px solid #f0f2f5; }
.section-header { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: #303133; }
.section-header .el-icon { color: #409EFF; }

.quick-card {
  padding: 20px 16px; text-align: center; border-radius: 12px;
  background: #fafbfc; border: 1px solid #ebeef5;
  cursor: pointer; transition: all 0.3s; margin-bottom: 16px;
}
.quick-card:hover {
  background: white; border-color: #409EFF;
  box-shadow: 0 8px 24px rgba(64,158,255,0.15);
  transform: translateY(-4px);
}
.quick-icon {
  width: 48px; height: 48px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 10px; background: #f5f7fa; color: #909399;
}
.quick-icon.blue { background: #ecf5ff; color: #409EFF; }
.quick-icon.green { background: #f0f9eb; color: #67C23A; }
.quick-icon.orange { background: #fdf6ec; color: #E6A23C; }
.quick-title { font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 4px; }
.quick-desc { font-size: 12px; color: #909399; }

.doc-types { display: flex; flex-wrap: wrap; gap: 10px; }
.doc-type-item {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 16px; border-radius: 8px;
  background: #f5f7fa; border: 1px solid transparent;
  cursor: pointer; transition: all 0.2s;
  font-size: 13px; color: #606266;
}
.doc-type-item:hover { background: #ecf5ff; border-color: #409EFF; color: #409EFF; }

.activity-list { padding: 8px 0; }
.activity-item { display: flex; align-items: flex-start; gap: 12px; padding: 10px 0; border-bottom: 1px solid #f0f2f5; }
.activity-item:last-child { border-bottom: none; }
.activity-dot { width: 8px; height: 8px; border-radius: 50%; margin-top: 5px; flex-shrink: 0; }
.activity-dot.system { background: #409EFF; }
.activity-title { font-size: 13px; color: #303133; }
.activity-time { font-size: 12px; color: #c0c4cc; margin-top: 2px; }

.status-list { padding: 8px 0; }
.status-item { display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #f0f2f5; }
.status-item:last-child { border-bottom: none; }
.status-item span:first-child { font-size: 13px; color: #606266; }
.status-item span:last-child { font-size: 13px; color: #303133; font-weight: 500; }
</style>
