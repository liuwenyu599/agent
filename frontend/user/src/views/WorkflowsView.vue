<template>
  <div class="wf-page">
    <div class="wf-main">
      <!-- 页头 -->
      <div class="wf-header">
        <div class="wf-header-left">
          <div class="wf-logo"><el-icon :size="26" color="#fff"><Share /></el-icon></div>
          <div>
            <div class="wf-title">公共工作流</div>
            <div class="wf-sub">提供常用办公流程模板，支持一键创建，智能生成各类材料</div>
          </div>
        </div>
        <el-button type="primary" @click="openCreate(null)"><el-icon><Plus /></el-icon>新建工作流</el-button>
      </div>

      <!-- 分类 -->
      <div class="cat-box">
        <div class="cat-title">工作流分类</div>
        <div class="cat-chips">
          <span class="chip" :class="{ on: category === 'all' }" @click="category = 'all'">全部</span>
          <span v-for="c in categories" :key="c" class="chip" :class="{ on: category === c }" @click="category = c">{{ c }}</span>
        </div>

        <!-- 模板卡片 -->
        <div v-loading="tplLoading" class="tpl-grid">
          <div v-for="t in filteredTemplates" :key="t.code" class="tpl-card" @click="openCreate(t)">
            <div class="tpl-head">
              <div class="tpl-icon" :style="{ background: iconColor(t.code) }">
                <el-icon :size="22" color="#fff"><component :is="iconOf(t.code)" /></el-icon>
              </div>
              <span class="tpl-name">{{ t.name }}</span>
              <el-tag v-if="t.code === 'meeting'" size="small" type="success" effect="dark" class="tpl-tag">常用</el-tag>
            </div>
            <div class="tpl-desc">{{ t.description }}</div>
            <div class="tpl-nodes">
              <div v-for="n in (t.nodes || []).slice(0, 3)" :key="n.name" class="tpl-node">
                · {{ n.name }} <el-icon color="#67c23a"><Check /></el-icon>
              </div>
            </div>
            <el-button class="use-btn" text type="primary">立即使用<el-icon><ArrowRight /></el-icon></el-button>
          </div>
        </div>
      </div>

      <!-- 推荐工作流 -->
      <div class="rec-box">
        <div class="rec-title"><el-icon color="#409eff"><Medal /></el-icon>推荐工作流</div>
        <el-table :data="templates" style="width: 100%">
          <el-table-column prop="name" label="流程名称" width="160" />
          <el-table-column prop="description" label="适用场景" min-width="240" show-overflow-tooltip />
          <el-table-column label="步骤数" width="100" align="center">
            <template #default="{ row }">{{ (row.nodes || []).length }}</template>
          </el-table-column>
          <el-table-column label="操作" width="140" align="center">
            <template #default="{ row }">
              <el-button size="small" type="primary" plain @click="openCreate(row)">立即使用</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- 右栏 -->
    <div class="wf-side">
      <div class="side-card">
        <div class="side-card-head">
          <span><el-icon color="#e6a23c"><Lightning /></el-icon>我的工作流</span>
          <el-button text type="primary" size="small" @click="myExpanded = !myExpanded">查看全部</el-button>
        </div>
        <el-tabs v-model="myTab" stretch>
          <el-tab-pane :label="`进行中 (${myByStatus('running').length})`" name="running" />
          <el-tab-pane :label="`草稿 (${myByStatus('draft').length})`" name="draft" />
          <el-tab-pane :label="`已完成 (${myByStatus('completed').length})`" name="completed" />
        </el-tabs>
        <div v-loading="myLoading">
          <div v-for="inst in myShown" :key="inst.id" class="my-item" @click="$router.push(`/workflows/${inst.id}`)">
            <div class="my-head">
              <div class="my-icon" :style="{ background: iconColor(inst.template_code) }">
                <el-icon :size="18" color="#fff"><component :is="iconOf(inst.template_code)" /></el-icon>
              </div>
              <span class="my-title">{{ inst.title }}</span>
              <el-tag size="small" :type="inst.status === 'completed' ? 'success' : inst.status === 'draft' ? 'info' : 'warning'" effect="light">
                {{ { running: '进行中', draft: '草稿', completed: '已完成' }[inst.status] || inst.status }}
              </el-tag>
            </div>
            <div class="my-progress">
              进度：{{ doneCount(inst) }}/{{ (inst.nodes || []).length }}
              <el-progress :percentage="progressOf(inst)" :stroke-width="6" style="flex: 1" />
            </div>
            <div class="my-foot">
              <span>当前节点：{{ currentNodeName(inst) }}</span>
              <el-button size="small" text type="primary" @click.stop="$router.push(`/workflows/${inst.id}`)">继续办理</el-button>
            </div>
            <div class="my-time">创建时间：{{ inst.created_at }}</div>
          </div>
          <el-empty v-if="!myLoading && !myShown.length" description="暂无工作流" :image-size="70" />
        </div>
      </div>

      <div class="side-card">
        <div class="side-card-head"><span><el-icon color="#409eff"><InfoFilled /></el-icon>使用说明</span></div>
        <ol class="guide">
          <li>选择合适的工作流模板，点击"立即使用"开始创建；</li>
          <li>系统将自动生成流程节点，并提供AI辅助写作；</li>
          <li>支持保存草稿，随时继续办理；</li>
          <li>完成后可在"我的工作流"中查看和管理。</li>
        </ol>
      </div>
    </div>

    <!-- 新建/使用模板 -->
    <el-dialog v-model="createVisible" :title="current ? `使用模板：${current.name}` : '新建工作流'" width="640px">
      <template v-if="!current">
        <div class="dlg-section-title">选择模板</div>
        <div class="dlg-tpl-grid">
          <div v-for="t in templates" :key="t.code" class="dlg-tpl"
            :class="{ selected: selectedCode === t.code }" @click="selectedCode = t.code">
            <div class="dlg-tpl-name">{{ t.name }}</div>
            <div class="dlg-tpl-desc">{{ t.description }}</div>
          </div>
        </div>
      </template>
      <el-form label-position="top" style="margin-top: 14px">
        <el-form-item label="工作流标题">
          <el-input v-model="form.title" placeholder="如：2026年司法行政工作推进会" />
        </el-form-item>
        <el-form-item label="基础信息（每行一条，格式：键：值）">
          <el-input v-model="form.basicText" type="textarea" :rows="4"
            placeholder="会议时间：2026-06-10 09:00&#10;会议地点：局机关三楼会议室&#10;主办部门：办公室" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createInstance">创建并进入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Share, Plus, Check, ArrowRight, Medal, Lightning, InfoFilled,
  User, Flag, Search, Document, Folder,
} from '@element-plus/icons-vue'
import {
  listWorkflowTemplates, listWorkflowInstances, createWorkflowInstance,
} from '@/api/workflow.js'

const router = useRouter()

const templates = ref([])
const myInstances = ref([])
const tplLoading = ref(false)
const myLoading = ref(false)
const myError = ref('')
const category = ref('all')
const myTab = ref('running')
const myExpanded = ref(false)
const createVisible = ref(false)
const creating = ref(false)
const current = ref(null)
const selectedCode = ref('')
const form = ref({ title: '', basicText: '' })

const categories = computed(() => [...new Set(templates.value.map(t => t.category || '通用'))])
const filteredTemplates = computed(() =>
  category.value === 'all' ? templates.value : templates.value.filter(t => t.category === category.value))

function myByStatus(s) { return myInstances.value.filter(i => i.status === s) }
const myShown = computed(() => {
  const list = myByStatus(myTab.value)
  return myExpanded.value ? list : list.slice(0, 3)
})

const ICONS = { meeting: User, activity: Flag, research: Search, report: Document }
const COLORS = { meeting: '#2f5cff', activity: '#22a06b', research: '#8b5cf6', report: '#f59e0b' }
function iconOf(code) { return ICONS[code] || Folder }
function iconColor(code) { return COLORS[code] || '#2f5cff' }

async function loadTemplates() {
  tplLoading.value = true
  try {
    const { data } = await listWorkflowTemplates()
    templates.value = data.templates || []
  } catch (e) {
    ElMessage.error('加载模板失败：' + (e.response?.data?.detail || e.message))
  } finally {
    tplLoading.value = false
  }
}

async function loadMine() {
  myLoading.value = true
  myError.value = ''
  try {
    const { data } = await listWorkflowInstances()
    myInstances.value = data.instances || data || []
  } catch (e) {
    myError.value = e.response?.data?.detail || e.message
    console.error('我的工作流加载失败:', e)
  } finally {
    myLoading.value = false
  }
}

function openCreate(t) {
  current.value = t
  selectedCode.value = t ? t.code : ''
  form.value = { title: '', basicText: '' }
  createVisible.value = true
}

function parseBasicInfo(text) {
  const info = {}
  text.split('\n').forEach(line => {
    const m = line.split(/[：:]/)
    if (m.length >= 2 && m[0].trim()) info[m[0].trim()] = m.slice(1).join('：').trim()
  })
  return info
}

async function createInstance() {
  const code = current.value ? current.value.code : selectedCode.value
  if (!code) return ElMessage.warning('请选择模板')
  if (!form.value.title.trim()) return ElMessage.warning('请填写标题')
  creating.value = true
  try {
    const { data } = await createWorkflowInstance({
      template_code: code,
      title: form.value.title.trim(),
      basic_info: parseBasicInfo(form.value.basicText),
    })
    ElMessage.success('创建成功')
    createVisible.value = false
    router.push(`/workflows/${data.id}`)
  } catch (e) {
    ElMessage.error('创建失败：' + (e.response?.data?.detail || e.message))
  } finally {
    creating.value = false
  }
}

function doneCount(inst) { return (inst.nodes || []).filter(n => n.status === 'done').length }
function progressOf(inst) {
  const total = (inst.nodes || []).length
  return total ? Math.round(doneCount(inst) / total * 100) : 0
}
function currentNodeName(inst) {
  const n = (inst.nodes || []).find(n => n.status !== 'done')
  return n ? n.name : '已全部完成'
}

onMounted(() => { loadTemplates(); loadMine() })
</script>

<style scoped>
.wf-page { display: flex; gap: 18px; padding: 20px 24px; align-items: flex-start; }
.wf-main { flex: 1; min-width: 0; }
.wf-side { width: 360px; flex-shrink: 0; display: flex; flex-direction: column; gap: 14px; }

.wf-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.wf-header-left { display: flex; gap: 12px; align-items: center; }
.wf-logo {
  width: 48px; height: 48px; border-radius: 10px; background: #2f5cff;
  display: flex; align-items: center; justify-content: center;
}
.wf-title { font-size: 22px; font-weight: 700; }
.wf-sub { color: #909399; font-size: 13px; margin-top: 2px; }

.cat-box { background: #fff; border: 1px solid #ebeef5; border-radius: 12px; padding: 18px; margin-bottom: 16px; }
.cat-title { font-weight: 700; margin-bottom: 12px; }
.cat-chips { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
.chip {
  padding: 5px 16px; border-radius: 16px; background: #f4f5f8; color: #606266;
  font-size: 13px; cursor: pointer; transition: all .15s;
}
.chip:hover { color: #2f5cff; }
.chip.on { background: #2f5cff; color: #fff; }

.tpl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; }
.tpl-card {
  border: 1.5px solid #ebeef5; border-radius: 10px; padding: 16px; cursor: pointer;
  transition: all .15s; position: relative;
}
.tpl-card:hover { border-color: #2f5cff; box-shadow: 0 2px 10px rgba(47,92,255,.12); }
.tpl-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.tpl-icon { width: 40px; height: 40px; border-radius: 8px; display: flex; align-items: center; justify-content: center; }
.tpl-name { font-weight: 700; font-size: 15px; }
.tpl-tag { margin-left: auto; }
.tpl-desc { color: #606266; font-size: 13px; margin-bottom: 10px; }
.tpl-nodes { font-size: 13px; color: #606266; line-height: 2; margin-bottom: 8px; }
.tpl-node { display: flex; align-items: center; gap: 6px; }
.use-btn { float: right; }
.use-btn::after { content: ''; display: block; clear: both; }

.rec-box { background: #fff; border: 1px solid #ebeef5; border-radius: 12px; padding: 18px; }
.rec-title { font-weight: 700; margin-bottom: 12px; display: flex; align-items: center; gap: 6px; }

.side-card { background: #fff; border: 1px solid #ebeef5; border-radius: 12px; padding: 16px; }
.side-card-head { display: flex; justify-content: space-between; align-items: center; font-weight: 700; margin-bottom: 6px; }
.side-card-head span { display: flex; align-items: center; gap: 6px; }

.my-item { border: 1px solid #f0f0f0; border-radius: 10px; padding: 12px; margin-bottom: 10px; cursor: pointer; }
.my-item:hover { border-color: #2f5cff; }
.my-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.my-icon { width: 34px; height: 34px; border-radius: 8px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.my-title { font-weight: 600; font-size: 14px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.my-progress { display: flex; align-items: center; gap: 10px; font-size: 12px; color: #606266; margin-bottom: 6px; }
.my-foot { display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: #606266; }
.my-time { font-size: 12px; color: #a8abb2; margin-top: 4px; }

.guide { margin: 0; padding-left: 18px; color: #606266; font-size: 13px; line-height: 2.1; }

.dlg-section-title { font-weight: 600; margin-bottom: 10px; }
.dlg-tpl-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.dlg-tpl { border: 1.5px solid #e4e7ed; border-radius: 8px; padding: 12px; cursor: pointer; }
.dlg-tpl:hover { border-color: #2f5cff; }
.dlg-tpl.selected { border-color: #2f5cff; background: #eef3ff; }
.dlg-tpl-name { font-weight: 600; margin-bottom: 4px; }
.dlg-tpl-desc { font-size: 12px; color: #909399; line-height: 1.6; }
</style>