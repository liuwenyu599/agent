<template>
  <div class="knowledge-page">
    <el-row :gutter="16" class="stats-bar">
      <el-col :span="4" v-for="stat in kbStats" :key="stat.label">
        <div class="stat-item">
          <div class="stat-value">{{ stat.value }}</div>
          <div class="stat-label">{{ stat.label }}</div>
        </div>
      </el-col>
    </el-row>
    <el-card class="filter-card" shadow="never">
      <el-form :model="filterForm" inline class="filter-form">
        <el-form-item label="知识库名称">
          <el-input v-model="filterForm.name" placeholder="搜索知识库" clearable prefix-icon="Search" style="width: 200px" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="filterForm.type" placeholder="全部类型" clearable style="width: 140px">
            <el-option label="公共知识库" value="public" />
            <el-option label="个人知识库" value="private" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="applyFilter"><el-icon><Search /></el-icon> 查询</el-button>
          <el-button @click="resetFilter">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button type="primary" @click="openCreateDialog"><el-icon><Plus /></el-icon> 新建知识库</el-button>
        <el-button type="success" @click="openBatchUploadDialog"><el-icon><Upload /></el-icon> 批量上传</el-button>
      </div>
      <div class="toolbar-right">
        <el-radio-group v-model="viewMode" size="small">
          <el-radio-button label="list"><el-icon><List /></el-icon> 列表</el-radio-button>
          <el-radio-button label="card"><el-icon><Grid /></el-icon> 卡片</el-radio-button>
        </el-radio-group>
      </div>
    </div>
    <el-card shadow="never" v-if="viewMode === 'list'">
      <el-table :data="filteredKBList" stripe v-loading="loading" style="width: 100%">
        <el-table-column type="index" width="50" align="center" />
        <el-table-column label="知识库名称" min-width="200">
          <template #default="{ row }">
            <div class="kb-name-cell">
              <el-icon :size="20" class="kb-icon"><Collection /></el-icon>
              <div class="kb-info-text">
                <div class="kb-title">{{ row.name }}</div>
                <div class="kb-desc">{{ row.description || '暂无描述' }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.type === 'public' ? 'success' : 'info'" size="small">{{ row.type === 'public' ? '公共' : '个人' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="文档数" width="100" align="center">
          <template #default="{ row }"><el-badge :value="row.doc_count || 0" class="doc-badge" /></template>
        </el-table-column>
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="enterKB(row)"><el-icon><View /></el-icon> 查看</el-button>
            <el-button link type="primary" @click="editKB(row)">编辑</el-button>
            <el-button link type="danger" @click="deleteKB(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="filteredKBList.length === 0 && !loading" description="暂无知识库" />
    </el-card>
    <el-row :gutter="16" v-if="viewMode === 'card'" v-loading="loading">
      <el-col :span="8" v-for="kb in filteredKBList" :key="kb.id">
        <el-card class="kb-card" shadow="hover" @click="enterKB(kb)">
          <div class="kb-header">
            <el-icon :size="28" class="kb-icon"><Collection /></el-icon>
            <div class="kb-title-area">
              <h3 class="kb-name">{{ kb.name }}</h3>
              <el-tag :type="kb.type === 'public' ? 'success' : 'info'" size="small">{{ kb.type === 'public' ? '公共' : '个人' }}</el-tag>
            </div>
          </div>
          <div class="kb-info">
            <p><el-icon><Document /></el-icon> 文档数: {{ kb.doc_count || 0 }}</p>
            <p><el-icon><Timer /></el-icon> {{ formatDate(kb.created_at) }}</p>
          </div>
          <div class="kb-actions">
            <el-button link type="primary" @click.stop="editKB(kb)">编辑</el-button>
            <el-button link type="danger" @click.stop="deleteKB(kb)">删除</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑知识库' : '新建知识库'" width="500px">
      <el-form :model="kbForm" label-width="100px" :rules="kbRules" ref="kbFormRef">
        <el-form-item label="名称" prop="name"><el-input v-model="kbForm.name" placeholder="请输入知识库名称" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="kbForm.description" type="textarea" :rows="3" placeholder="知识库描述" /></el-form-item>
        <el-form-item label="类型" v-if="isAdmin && !isEdit">
          <el-radio-group v-model="kbForm.kb_type">
            <el-radio-button label="public">公共知识库</el-radio-button>
            <el-radio-button label="personal">个人知识库</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="!isAdmin && !isEdit">
          <el-alert title="普通用户自动创建个人知识库（仅自己可见）" type="info" :closable="false" />
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="submitKB" :loading="submitting">确定</el-button></template>
    </el-dialog>

    <el-dialog v-model="batchUploadVisible" title="批量上传文档" width="500px" destroy-on-close>
      <el-alert title="批量上传说明" description="选择知识库后上传多个文件，系统将自动解析并建立索引。上传后文档状态为'待审核'，需管理员审核后发布。" type="info" :closable="false" style="margin-bottom: 16px" />
      <el-form label-width="100px">
        <el-form-item label="目标知识库" required>
          <el-select v-model="batchTargetKb" placeholder="选择知识库" style="width: 100%">
            <el-option 
              v-for="kb in kbList" 
              :key="kb.id" 
              :label="kb.name + (kb.type === 'public' ? ' [公共]' : ' [个人]')" 
              :value="kb.id" 
            />
          </el-select>
        </el-form-item>
      </el-form>
      <el-upload ref="batchUploadRef" drag :action="batchUploadAction" :headers="uploadHeaders" :before-upload="beforeBatchUpload" :on-success="handleBatchSuccess" :on-error="handleBatchError" multiple accept=".pdf,.doc,.docx,.txt,.md">
        <el-icon class="el-icon--upload" :size="48"><Upload /></el-icon>
        <div class="el-upload__text">拖拽文件到此处或 <em>点击上传</em></div>
        <template #tip><div class="el-upload__tip">支持批量上传，文件格式：PDF、Word、TXT、Markdown</div></template>
      </el-upload>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Upload, Search, Collection, Document, Timer, View, List, Grid } from '@element-plus/icons-vue'
import axios from 'axios'

const router = useRouter()
const loading = ref(false), kbList = ref([]), filteredKBList = ref([])

const isAdmin = computed(() => {
  try {
    const user = JSON.parse(localStorage.getItem('user') || '{}')
    return ['developer', 'knowledge_admin', 'admin'].includes(user.role)
  } catch { return false }
})
const viewMode = ref('list')
const filterForm = reactive({ name: '', type: '' })

const kbStats = computed(() => {
  const total = kbList.value.length, publicCount = kbList.value.filter(k => k.type === 'public').length
  const privateCount = kbList.value.filter(k => k.type === 'private').length
  const totalDocs = kbList.value.reduce((sum, k) => sum + (k.doc_count || 0), 0)
  return [
    { label: '知识库总数', value: total }, { label: '公共库', value: publicCount },
    { label: '个人库', value: privateCount }, { label: '文档总数', value: totalDocs }
  ]
})

const dialogVisible = ref(false), isEdit = ref(false), submitting = ref(false)
const kbFormRef = ref(null)
const kbForm = reactive({ id: '', name: '', description: '', kb_type: 'personal' })
const kbRules = { name: [{ required: true, message: '请输入知识库名称', trigger: 'blur' }] }
const token = computed(() => localStorage.getItem('token') || '')
const uploadHeaders = computed(() => ({ Authorization: `Bearer ${token.value}` }))

const batchUploadVisible = ref(false), batchTargetKb = ref(''), batchUploadRef = ref(null)
const batchUploadAction = computed(() => batchTargetKb.value ? `/api/v1/knowledge/batch-upload?kb_id=${batchTargetKb.value}` : '')

onMounted(() => { loadKBList() })

async function loadKBList() {
  loading.value = true
  try {
    const res = await axios.get('/api/v1/knowledge/list', { headers: { Authorization: `Bearer ${token.value}` } })
    kbList.value = res.data || []; applyFilter()
  } catch (e) { ElMessage.error('加载知识库失败') } finally { loading.value = false }
}

function applyFilter() {
  let r = [...kbList.value]
  if (filterForm.name) r = r.filter(k => k.name.toLowerCase().includes(filterForm.name.toLowerCase()))
  if (filterForm.type) r = r.filter(k => k.type === filterForm.type)
  filteredKBList.value = r
}

function resetFilter() { filterForm.name = ''; filterForm.type = ''; applyFilter() }
function openCreateDialog() { isEdit.value = false; Object.assign(kbForm, { id: '', name: '', description: '', kb_type: 'personal' }); dialogVisible.value = true; }

function editKB(kb) {
  isEdit.value = true
  kbForm.id = kb.id
  kbForm.name = kb.name
  kbForm.description = kb.description || ''
  dialogVisible.value = true
}

async function submitKB() {
  const valid = await kbFormRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    if (isEdit.value) {
      await axios.put(`/api/v1/knowledge/${kbForm.id}`, { name: kbForm.name, description: kbForm.description }, { headers: { Authorization: `Bearer ${token.value}` } })
      ElMessage.success('修改成功')
    } else {
      const payload = { name: kbForm.name, description: kbForm.description }
      if (isAdmin.value && kbForm.kb_type) payload.kb_type = kbForm.kb_type
      await axios.post('/api/v1/knowledge/create', payload, { headers: { Authorization: `Bearer ${token.value}` } })
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    loadKBList()
  } catch (e) { ElMessage.error('操作失败: ' + (e.response?.data?.detail || e.message)) } finally { submitting.value = false }
}

function enterKB(kb) { router.push(`/knowledge/${kb.id}`) }

async function deleteKB(kb) {
  try {
    await ElMessageBox.confirm(`确定删除知识库「${kb.name}」？`, '警告', { type: 'warning' })
    await axios.delete(`/api/v1/knowledge/${kb.id}`, { headers: { Authorization: `Bearer ${token.value}` } })
    ElMessage.success('已删除'); loadKBList()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message)) }
}

function openBatchUploadDialog() { batchTargetKb.value = ''; batchUploadVisible.value = true; if (batchUploadRef.value) batchUploadRef.value.clearFiles() }

function beforeBatchUpload(file) {
  if (!batchTargetKb.value) { ElMessage.error('请先选择目标知识库'); return false }
  const exts = ['.pdf', '.doc', '.docx', '.txt', '.md']
  const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
  if (!exts.includes(ext)) { ElMessage.error('不支持的文件格式'); return false }
  if (file.size > 50 * 1024 * 1024) { ElMessage.error('文件大小不能超过 50MB'); return false }
  return true
}

function handleBatchSuccess() { ElMessage.success('批量上传任务已提交'); batchUploadVisible.value = false; loadKBList() }

function handleBatchError(error) {
  let msg = '上传失败'
  try { msg = JSON.parse(error.message || '{}').detail || msg } catch { msg = error.message || msg }
  ElMessage.error(msg)
}

function formatDate(d) { if (!d) return '-'; return new Date(d).toLocaleDateString('zh-CN') }
</script>

<style scoped>
.knowledge-page { padding: 20px; background: #f5f7fa; min-height: 100vh; }
.stats-bar { margin-bottom: 16px; }
.stat-item { background: white; border-radius: 8px; padding: 16px; text-align: center; box-shadow: 0 1px 4px rgba(0,0,0,0.05); transition: transform 0.2s; }
.stat-item:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
.stat-value { font-size: 26px; font-weight: bold; color: #409EFF; line-height: 1; }
.stat-label { font-size: 13px; color: #909399; margin-top: 8px; }
.filter-card { margin-bottom: 16px; }
.filter-form { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.toolbar { margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }
.toolbar-left { display: flex; gap: 10px; }
.kb-name-cell { display: flex; align-items: center; gap: 12px; }
.kb-icon { color: #409EFF; flex-shrink: 0; }
.kb-info-text { display: flex; flex-direction: column; gap: 4px; }
.kb-title { font-size: 15px; font-weight: 500; color: #303133; }
.kb-desc { font-size: 12px; color: #909399; }
.doc-badge :deep(.el-badge__content) { background-color: #67C23A; }
.kb-card { cursor: pointer; margin-bottom: 16px; transition: all 0.3s; }
.kb-card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(0,0,0,0.1) !important; }
.kb-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.kb-name { margin: 0; font-size: 16px; font-weight: 500; }
.kb-info p { margin: 6px 0; font-size: 13px; color: #606266; display: flex; align-items: center; gap: 6px; }
.kb-actions { margin-top: 12px; padding-top: 12px; border-top: 1px solid #ebeef5; }
.el-upload__tip { text-align: center; color: #909399; margin-top: 8px; }
</style>
