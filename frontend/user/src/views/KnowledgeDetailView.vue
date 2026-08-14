<template>
  <div class="kb-detail-page">
    <el-page-header @back="goBack" :title="kbInfo.name || '知识库详情'" />

    <!-- 文档状态统计（仅知识管理员可见） -->
    <el-row :gutter="12" class="doc-stats-row" v-if="isKnowledgeAdmin">
      <el-col :xs="12" :sm="4" v-for="s in statusList" :key="s.key">
        <div class="doc-stat-card" :class="{ active: docStatus === s.key }" @click="filterByStatus(s.key)">
          <div class="doc-stat-value">{{ docStats[s.key] || 0 }}</div>
          <div class="doc-stat-label">{{ s.label }}</div>
        </div>
      </el-col>
    </el-row>

    <el-card class="kb-info-card" shadow="never" v-loading="kbLoading">
      <el-descriptions :column="3" border v-if="kbInfo.name">
        <el-descriptions-item label="知识库名称" :span="1">{{ kbInfo.name }}</el-descriptions-item>
        <el-descriptions-item label="类型" :span="1">
          <el-tag :type="kbInfo.type === 'public' ? 'success' : 'info'">{{ kbInfo.type === 'public' ? '公共' : '个人' }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="文档数" :span="1">{{ kbInfo.doc_count || 0 }}</el-descriptions-item>
        <el-descriptions-item label="描述" :span="3">{{ kbInfo.description || '暂无描述' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 文档列表 -->
    <el-card class="doc-list-card" shadow="never">
      <template #header>
        <div class="card-header">
          <div class="header-left">
            <span>文档列表</span>
            <el-radio-group v-model="docStatus" size="small" @change="loadDocList" v-if="isKnowledgeAdmin" style="margin-left:16px">
              <el-radio-button label="all">全部</el-radio-button>
              <el-radio-button label="published">已发布</el-radio-button>
              <el-radio-button label="pending">待审核</el-radio-button>
              <el-radio-button label="rejected">已驳回</el-radio-button>
              <el-radio-button label="archived">已归档</el-radio-button>
            </el-radio-group>
          </div>
          <el-button type="primary" size="small" @click="openUploadDialog">
            <el-icon><Upload /></el-icon> 上传文档
          </el-button>
        </div>
      </template>

      <el-table :data="docList" stripe v-loading="docLoading" style="width: 100%" v-if="docList.length > 0 || docLoading">
        <el-table-column type="index" width="50" align="center" />
        <el-table-column label="文档名称" min-width="180">
          <template #default="{ row }">
            <div class="doc-name-cell">
              <el-icon :size="18"><Document /></el-icon>
              <span>{{ row.title || '未命名' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }"><el-tag size="small">{{ row.doc_type || '其他' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="部门" width="120">
          <template #default="{ row }">{{ row.department || '-' }}</template>
        </el-table-column>
        <el-table-column label="文号" width="140">
          <template #default="{ row }">{{ row.doc_number || '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }"><el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="上传者" width="100">
          <template #default="{ row }">{{ row.uploaded_by || '-' }}</template>
        </el-table-column>
        <el-table-column label="上传时间" width="150">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="previewDoc(row)">预览</el-button>
            <el-button link type="primary" @click="editDoc(row)">编辑</el-button>
            <el-button v-if="isKnowledgeAdmin && row.status === 'pending'" link type="success" @click="reviewDoc(row, 'approved')">通过</el-button>
            <el-button v-if="isKnowledgeAdmin && row.status === 'pending'" link type="danger" @click="reviewDoc(row, 'rejected')">驳回</el-button>
            <el-button link type="danger" @click="deleteDoc(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="docList.length === 0 && !docLoading" description="暂无文档" />
    </el-card>

    <!-- 上传对话框 -->
    <el-dialog v-model="uploadVisible" title="上传文档" width="560px" destroy-on-close>
      <el-form :model="uploadForm" label-width="90px">
        <el-form-item label="目标知识库">
          <el-select v-model="uploadTargetKb" style="width:100%" disabled>
            <el-option :label="kbInfo.name + (kbInfo.type === 'public' ? ' [公共]' : ' [个人]')" :value="kbId" />
          </el-select>
          <div class="kb-hint" v-if="kbInfo.type === 'public' && !isAdmin">上传到公共库需管理员审核后发布</div>
          <div class="kb-hint personal" v-if="kbInfo.type === 'personal'">个人知识库，上传后直接发布</div>
        </el-form-item>
        <el-form-item label="选择文件" required>
          <el-upload ref="uploadRef" :auto-upload="false" :on-change="handleFileChange" :limit="1" accept=".pdf,.doc,.docx,.txt,.md">
            <el-button type="primary"><el-icon><Upload /></el-icon> 选择文件</el-button>
          </el-upload>
          <div v-if="uploadForm.file" class="file-selected">已选择: {{ uploadForm.file.name }}</div>
        </el-form-item>
        <el-form-item label="文档标题"><el-input v-model="uploadForm.title" placeholder="默认使用文件名" /></el-form-item>
        <el-form-item label="文档类型">
          <el-select v-model="uploadForm.doc_type" placeholder="自动识别" style="width:100%">
            <el-option label="自动识别" value="" />
            <el-option label="法规" value="法规" />
            <el-option label="公文" value="公文" />
            <el-option label="其他" value="其他" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属部门"><el-input v-model="uploadForm.department" placeholder="如：社区矫正科" /></el-form-item>
        <el-form-item label="发文字号"><el-input v-model="uploadForm.doc_number" placeholder="如：××司发〔2026〕1号" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" @click="submitUpload" :loading="uploadLoading">上传</el-button>
      </template>
    </el-dialog>

    <!-- 预览对话框 -->
    <el-dialog v-model="previewVisible" title="文档预览" width="800px" top="5vh">
      <div v-if="currentDoc" class="doc-preview">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="标题" :span="2"><strong>{{ currentDoc.title }}</strong></el-descriptions-item>
          <el-descriptions-item label="类型">{{ currentDoc.doc_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag :type="statusType(currentDoc.status)">{{ statusText(currentDoc.status) }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="部门">{{ currentDoc.department || '-' }}</el-descriptions-item>
          <el-descriptions-item label="文号">{{ currentDoc.doc_number || '-' }}</el-descriptions-item>
          <el-descriptions-item label="上传者">{{ currentDoc.uploaded_by || '-' }}</el-descriptions-item>
          <el-descriptions-item label="审核意见" :span="2">{{ currentDoc.review_comment || '-' }}</el-descriptions-item>
        </el-descriptions>
        <el-divider />
        <div v-if="currentDoc.content" class="doc-content"><pre>{{ currentDoc.content }}</pre></div>
        <el-empty v-else description="暂无内容预览" />
      </div>
    </el-dialog>

    <!-- 编辑对话框 -->
    <el-dialog v-model="editVisible" title="编辑文档" width="560px">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="文档标题"><el-input v-model="editForm.title" /></el-form-item>
        <el-form-item label="文档类型">
          <el-select v-model="editForm.doc_type" style="width:100%">
            <el-option label="法规" value="法规" />
            <el-option label="公文" value="公文" />
            <el-option label="其他" value="其他" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属部门"><el-input v-model="editForm.department" /></el-form-item>
        <el-form-item label="发文字号"><el-input v-model="editForm.doc_number" /></el-form-item>
        <el-form-item label="状态" v-if="isKnowledgeAdmin">
          <el-select v-model="editForm.status" style="width:100%">
            <el-option label="已发布" value="published" />
            <el-option label="待审核" value="pending" />
            <el-option label="已归档" value="archived" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="submitEdit" :loading="editLoading">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, Document } from '@element-plus/icons-vue'
import axios from 'axios'

const route = useRoute(), router = useRouter(), kbId = route.params.id
const kbInfo = ref({}), kbLoading = ref(false), docList = ref([]), docLoading = ref(false)
const token = ref(localStorage.getItem('token') || '')

const isAdmin = computed(() => {
  try {
    const user = JSON.parse(localStorage.getItem('user') || '{}')
    return ['developer', 'knowledge_admin', 'admin'].includes(user.role)
  } catch { return false }
})

const isKnowledgeAdmin = computed(() => {
  try {
    const user = JSON.parse(localStorage.getItem('user') || '{}')
    return user.role === 'knowledge_admin'
  } catch { return false }
})

const docStatus = ref('published')
const docStats = ref({ all: 0, published: 0, pending: 0, rejected: 0, archived: 0 })
const statusList = [
  { key: 'all', label: '全部文档' },
  { key: 'published', label: '已发布' },
  { key: 'pending', label: '待审核' },
  { key: 'rejected', label: '已驳回' },
  { key: 'archived', label: '已归档' }
]

const uploadVisible = ref(false)
const uploadTargetKb = ref(kbId)
const uploadLoading = ref(false)
const uploadRef = ref(null)
const uploadForm = ref({ file: null, title: '', doc_type: '', department: '', doc_number: '' })

const editVisible = ref(false)
const editLoading = ref(false)
const editForm = ref({ id: '', title: '', doc_type: '', status: '', department: '', doc_number: '' })

const previewVisible = ref(false)
const currentDoc = ref(null)

onMounted(() => { loadKBInfo(); loadDocList(); loadDocStats() })

function filterByStatus(status) {
  docStatus.value = status
  loadDocList()
}

async function loadKBInfo() {
  kbLoading.value = true
  try {
    const res = await axios.get(`/api/v1/knowledge/${kbId}`, { headers: { Authorization: `Bearer ${token.value}` } })
    kbInfo.value = (res.data && typeof res.data === 'object') ? res.data : {}
  } catch (e) { kbInfo.value = {} } finally { kbLoading.value = false }
}

async function loadDocList() {
  docLoading.value = true
  try {
    const params = {}
    if (isAdmin.value) {
      params.status = docStatus.value
    }
    const res = await axios.get(`/api/v1/knowledge/${kbId}/documents`, {
      headers: { Authorization: `Bearer ${token.value}` },
      params
    })
    if (res.data && Array.isArray(res.data.data)) docList.value = res.data.data
    else if (Array.isArray(res.data)) docList.value = res.data
    else docList.value = []
  } catch (e) { docList.value = [] } finally { docLoading.value = false }
}

async function loadDocStats() {
  if (!isAdmin.value) return
  const statuses = ['all', 'published', 'pending', 'rejected', 'archived']
  for (const s of statuses) {
    try {
      const res = await axios.get(`/api/v1/knowledge/${kbId}/documents`, {
        headers: { Authorization: `Bearer ${token.value}` },
        params: { status: s, page_size: 1 }
      })
      docStats.value[s] = res.data.total || 0
    } catch (e) {
      docStats.value[s] = 0
    }
  }
}

function goBack() { router.push('/knowledge') }
function statusType(s) { const m = { published: 'success', pending: 'warning', archived: 'info', rejected: 'danger' }; return m[s] || 'info' }
function statusText(s) { const m = { published: '已发布', pending: '待审核', archived: '已归档', rejected: '已驳回' }; return m[s] || s || '未知' }

function openUploadDialog() {
  uploadForm.value = { file: null, title: '', doc_type: '', department: '', doc_number: '' }
  uploadVisible.value = true
}

function handleFileChange(file) {
  uploadForm.value.file = file.raw
  if (!uploadForm.value.title) uploadForm.value.title = file.name.replace(/\.(docx|pdf|txt|md|doc)$/i, '')
}

async function submitUpload() {
  if (!uploadForm.value.file) { ElMessage.warning('请选择文件'); return }
  uploadLoading.value = true
  try {
    const formData = new FormData()
    formData.append('file', uploadForm.value.file)
    if (uploadForm.value.title) formData.append('title', uploadForm.value.title)
    if (uploadForm.value.doc_type) formData.append('doc_type', uploadForm.value.doc_type)
    if (uploadForm.value.department) formData.append('department', uploadForm.value.department)
    if (uploadForm.value.doc_number) formData.append('doc_number', uploadForm.value.doc_number)

    await axios.post(`/api/v1/knowledge/upload?kb_id=${uploadTargetKb.value || kbId}`, formData, {
      headers: { Authorization: `Bearer ${token.value}`, 'Content-Type': 'multipart/form-data' }
    })
    ElMessage.success('上传成功')
    uploadVisible.value = false
    loadDocList(); loadDocStats(); loadKBInfo()
  } catch (e) { ElMessage.error('上传失败: ' + (e.response?.data?.detail || e.message)) }
  finally { uploadLoading.value = false }
}

async function previewDoc(row) {
  try {
    const res = await axios.get(`/api/v1/knowledge/documents/${row.id}`, { headers: { Authorization: `Bearer ${token.value}` } })
    currentDoc.value = res.data; previewVisible.value = true
  } catch (e) { ElMessage.error('加载失败') }
}

function editDoc(row) {
  editForm.value = { id: row.id, title: row.title, doc_type: row.doc_type || '其他', status: row.status, department: row.department || '', doc_number: row.doc_number || '' }
  editVisible.value = true
}

async function submitEdit() {
  editLoading.value = true
  try {
    const payload = { title: editForm.value.title, doc_type: editForm.value.doc_type, department: editForm.value.department, doc_number: editForm.value.doc_number }
    if (isAdmin.value) payload.status = editForm.value.status
    await axios.put(`/api/v1/knowledge/documents/${editForm.value.id}`, payload, { headers: { Authorization: `Bearer ${token.value}` } })
    ElMessage.success('保存成功'); editVisible.value = false; loadDocList(); loadDocStats()
  } catch (e) { ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message)) }
  finally { editLoading.value = false }
}

async function reviewDoc(row, action) {
  try {
    await axios.post('/api/v1/knowledge/review', { doc_id: row.id, action, comment: action === 'approved' ? '审核通过' : '不符合要求' }, { headers: { Authorization: `Bearer ${token.value}` } })
    ElMessage.success('审核完成'); loadDocList(); loadDocStats(); loadKBInfo()
  } catch (e) { ElMessage.error('审核失败') }
}

async function deleteDoc(row) {
  try {
    await ElMessageBox.confirm(`确定删除文档「${row.title || '未命名'}」？`, '警告', { type: 'warning' })
    await axios.delete(`/api/v1/knowledge/documents/${row.id}`, { headers: { Authorization: `Bearer ${token.value}` } })
    ElMessage.success('已删除'); loadDocList(); loadDocStats(); loadKBInfo()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

function formatDate(d) { if (!d) return '-'; return new Date(d).toLocaleDateString('zh-CN') }
</script>

<style scoped>
.kb-detail-page { padding: 20px; background: #f5f7fa; min-height: 100vh; }
.doc-stats-row { margin: 16px 0; }
.doc-stat-card { background: white; border-radius: 8px; padding: 16px 8px; text-align: center; cursor: pointer; transition: all 0.2s; border: 2px solid transparent; box-shadow: 0 1px 4px rgba(0,0,0,0.05); }
.doc-stat-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
.doc-stat-card.active { border-color: #409EFF; background: #ecf5ff; }
.doc-stat-value { font-size: 24px; font-weight: bold; color: #409EFF; line-height: 1; }
.doc-stat-label { font-size: 13px; color: #909399; margin-top: 6px; }
.kb-info-card { margin: 16px 0; }
.doc-list-card { margin-top: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.header-left { display: flex; align-items: center; }
.doc-name-cell { display: flex; align-items: center; gap: 8px; }
.doc-preview { padding: 10px; }
.doc-content { max-height: 400px; overflow-y: auto; background: #f5f7fa; padding: 16px; border-radius: 8px; }
.doc-content pre { margin: 0; white-space: pre-wrap; word-wrap: break-word; font-size: 14px; line-height: 1.8; color: #303133; }
.file-selected { margin-top: 8px; color: #67C23A; font-size: 13px; }
.kb-hint { margin-top: 6px; font-size: 12px; color: #E6A23C; }
.kb-hint.personal { color: #67C23A; }
</style>
