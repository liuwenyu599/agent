<template>
  <el-container class="chat-container">
    <!-- 左侧会话列表 -->
    <el-aside width="260px" class="session-sidebar">
      <div class="sidebar-header">
        <div class="sidebar-title">
          <el-icon :size="20"><ChatLineRound /></el-icon>
          <span>智能写作</span>
        </div>
        <el-button type="primary" size="small" @click="createNewSession">
          <el-icon><Plus /></el-icon> 新对话
        </el-button>
      </div>

      <div class="session-list" v-loading="sessionLoading">
        <div
          v-for="s in sessions"
          :key="s.id"
          :class="['session-item', { active: sessionId === s.id }]"
          @click="selectSession(s)"
        >
          <div class="session-info">
            <div class="session-title">{{ s.title || '新对话' }}</div>
            <div class="session-time">{{ formatTime(s.created_at) }}</div>
          </div>
          <el-button
            link
            size="small"
            class="session-delete"
            @click.stop="deleteSession(s)"
          >
            <el-icon><Delete /></el-icon>
          </el-button>
        </div>
        <el-empty v-if="sessions.length === 0 && !sessionLoading" description="暂无会话" :image-size="60" />
      </div>
    </el-aside>

    <!-- 右侧聊天区 -->
    <el-main class="chat-main">
      <div class="chat-area">
        <!-- 欢迎页 -->
        <div class="quick-actions" v-if="messages.length === 0">
          <h3>欢迎使用白云司法智能写作助手</h3>
          <p class="subtitle">请选择写作方式：</p>
          <el-row :gutter="16" class="action-cards">
            <el-col :span="8">
              <el-card shadow="hover" class="action-card" @click="goToTemplates">
                <el-icon :size="32" color="#409EFF"><DocumentCopy /></el-icon>
                <h4>写作模板</h4>
                <p>使用预设模板快速生成公文</p>
              </el-card>
            </el-col>
            <el-col :span="8">
              <el-card shadow="hover" class="action-card" @click="focusInput">
                <el-icon :size="32" color="#67C23A"><ChatDotRound /></el-icon>
                <h4>自由写作</h4>
                <p>输入需求或上传材料，AI 辅助写作</p>
              </el-card>
            </el-col>
            <el-col :span="8">
              <el-card shadow="hover" class="action-card" @click="goToKnowledge">
                <el-icon :size="32" color="#E6A23C"><Document /></el-icon>
                <h4>知识库</h4>
                <p>管理文档，增强检索能力</p>
              </el-card>
            </el-col>
          </el-row>

          <div class="quick-templates" v-if="popularTemplates.length > 0">
            <p class="subtitle">常用模板：</p>
            <el-space wrap>
              <el-tag
                v-for="tmpl in popularTemplates"
                :key="tmpl.id"
                type="primary"
                effect="plain"
                size="large"
                class="template-tag"
                @click="quickUseTemplate(tmpl)"
              >
                <el-icon><component :is="tmpl.icon || 'Document'" /></el-icon>
                {{ tmpl.name }}
              </el-tag>
            </el-space>
          </div>
        </div>

        <!-- 消息列表 -->
        <div class="messages" ref="msgRef" v-show="messages.length > 0">
          <div v-for="(msg, idx) in messages" :key="idx" :class="['msg', msg.role]">
            <div class="msg-avatar">
              <el-avatar :icon="msg.role === 'user' ? 'User' : 'ChatDotRound'"
                :style="{ background: msg.role === 'user' ? '#1a5fb4' : '#26a269' }" />
            </div>
            <div class="msg-content">
              <div class="msg-meta">
                <span>{{ msg.role === 'user' ? '我' : '助手' }}</span>
                <el-tag v-if="msg.source === 'template'" size="small" type="warning" style="margin-left:8px">📝 公文生成</el-tag>
                <span class="msg-time" v-if="msg.created_at">{{ formatTime(msg.created_at) }}</span>
              </div>
              <div class="msg-text">
                <!-- 用户消息携带的附件 -->
                <div v-if="msg.attachments?.length" class="msg-attachments">
                  <el-tag
                    v-for="att in msg.attachments" :key="att.id"
                    size="small" effect="plain" class="attachment-tag"
                    :type="att.parse_status === 'failed' ? 'danger' : (att.kind === 'image' ? 'warning' : 'info')"
                  >
                    <el-icon><component :is="att.kind === 'image' ? 'Picture' : 'Document'" /></el-icon>
                    {{ att.filename }}
                    <span v-if="att.parse_status === 'failed'">（解析失败）</span>
                    <span v-else-if="att.kind === 'image'">（OCR）</span>
                  </el-tag>
                </div>
                <div v-if="msg.role === 'assistant'" class="md-body" v-html="renderMd(msg.content)"></div>
                <span v-else>{{ msg.content }}</span>

                <div v-if="msg.role === 'assistant' && msg.sources?.length" class="msg-sources-detailed">
                  <el-divider content-position="left">
                    <el-icon><Link /></el-icon> 回答依据
                  </el-divider>
                  <div v-for="(source, sidx) in msg.sources" :key="sidx" class="source-item">
                    <span class="source-num">[{{ sidx + 1 }}]</span>
                    <span class="source-name">{{ source }}</span>
                  </div>
                </div>

                <div v-if="msg.role === 'assistant'" class="msg-actions">
                  <el-button size="small" text @click="copyText(msg.content)">
                    <el-icon><CopyDocument /></el-icon> 复制
                  </el-button>
                  <el-button size="small" text @click="openExportDialog(msg)">
                    <el-icon><Document /></el-icon> 生成 Word
                  </el-button>
                </div>
              </div>
            </div>
          </div>
          <div v-if="loading" class="msg assistant">
            <div class="msg-avatar">
              <el-avatar icon="Loading" style="background: #26a269" />
            </div>
            <div class="msg-content">
              <el-skeleton :rows="3" animated />
            </div>
          </div>
        </div>

        <!-- 输入区域 -->
        <div class="input-area">
          <!-- 待发送附件 -->
          <div v-if="pendingAttachments.length > 0" class="pending-attachments">
            <el-tag
              v-for="(att, idx) in pendingAttachments" :key="att.localId"
              closable
              :type="att.status === 'error' ? 'danger' : (att.status === 'ready' ? 'success' : 'info')"
              effect="plain"
              class="attachment-tag"
              @close="removePendingAttachment(idx)"
            >
              <el-icon v-if="att.status === 'uploading'" class="is-loading"><Loading /></el-icon>
              <el-icon v-else><component :is="att.kind === 'image' ? 'Picture' : 'Document'" /></el-icon>
              {{ att.filename }}
              <span v-if="att.status === 'error'" class="att-note">（{{ att.note || '解析失败' }}）</span>
              <span v-else-if="att.status === 'ready' && att.kind === 'image'" class="att-note">（OCR 已识别）</span>
            </el-tag>
          </div>
          <el-input
            v-model="input"
            type="textarea"
            :rows="3"
            placeholder="请输入写作需求，可点击下方回形针上传 Word/PDF/TXT/图片材料，例如：请把这份材料整理成一份汇报..."
            @keydown.enter.prevent="send"
            ref="inputRef"
          />
          <div class="input-actions">
            <div class="input-left">
              <el-switch v-model="useRag" active-text="使用知识库" />
              <el-upload
                :show-file-list="false"
                :auto-upload="false"
                :on-change="handleAttachmentSelect"
                multiple
                accept=".docx,.doc,.pdf,.txt,.md,.jpg,.jpeg,.png,.bmp,.webp,.tif,.tiff"
              >
                <el-button size="small" text :disabled="uploadingAttachment">
                  <el-icon><Paperclip /></el-icon> 上传材料
                </el-button>
              </el-upload>
              <el-button size="small" text @click="goToTemplates">
                <el-icon><DocumentCopy /></el-icon> 模板
              </el-button>
            </div>
            <el-button type="primary" @click="send" :loading="loading" :disabled="!canSend">
              <el-icon><Promotion /></el-icon> 发送
            </el-button>
          </div>
        </div>
      </div>
    </el-main>
  </el-container>

  <!-- Word 导出对话框 -->
  <el-dialog v-model="exportDialogVisible" title="导出为 Word 文档" width="550px" destroy-on-close>
    <el-form :model="exportForm" label-width="100px">
      <el-form-item label="文档标题">
        <el-input v-model="exportForm.title" placeholder="如：社区矫正年度工作总结" />
      </el-form-item>
      <el-form-item label="导出格式">
        <el-radio-group v-model="exportForm.format">
          <el-radio label="normal">普通格式</el-radio>
          <el-radio label="official">标准公文格式</el-radio>
        </el-radio-group>
      </el-form-item>
      <template v-if="exportForm.format === 'official'">
        <el-form-item label="发文字号">
          <el-input v-model="exportForm.doc_number" placeholder="如：××司发〔2026〕1号" />
        </el-form-item>
        <el-form-item label="主送机关">
          <el-input v-model="exportForm.recipient" placeholder="如：各区县司法局" />
        </el-form-item>
        <el-form-item label="落款单位">
          <el-input v-model="exportForm.signature" placeholder="如：××市司法局" />
        </el-form-item>
        <el-form-item label="成文日期">
          <el-input v-model="exportForm.date_text" placeholder="如：2026年7月23日" />
        </el-form-item>
      </template>
    </el-form>
    <template #footer>
      <el-button @click="exportDialogVisible = false">取消</el-button>
      <el-button type="primary" @click="exportWord" :loading="exportLoading">导出</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, nextTick, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatLineRound, Document, DocumentCopy, Picture, Loading, Paperclip,
  CopyDocument, Link, Promotion, Plus, Delete
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { sendChat, exportDocx, exportOfficial, listSessions, getMessages } from '@/api/knowledge.js'
import { uploadChatAttachments } from '@/api/format_check.js'
import axios from 'axios'

const router = useRouter()
const authStore = useAuthStore()

const input = ref('')
const messages = ref([])
const loading = ref(false)
const useRag = ref(true)
const msgRef = ref(null)
const inputRef = ref(null)
const sessionId = ref(null)
const popularTemplates = ref([])

// 会话列表
const sessions = ref([])
const sessionLoading = ref(false)

// 附件
const pendingAttachments = ref([])  // [{localId, id, filename, kind, status, note}]
const uploadingAttachment = ref(false)
const MAX_ATTACHMENTS = 5
const ALLOWED_EXTS = ['.docx', '.doc', '.pdf', '.txt', '.md', '.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tif', '.tiff']

const canSend = computed(() =>
  (input.value.trim() || pendingAttachments.value.some(a => a.status === 'ready'))
  && !pendingAttachments.value.some(a => a.status === 'uploading')
)

// 导出相关
const exportDialogVisible = ref(false)
const exportLoading = ref(false)
const currentExportMsg = ref(null)
const exportForm = ref({
  title: '',
  format: 'normal',
  doc_number: '',
  recipient: '',
  signature: '',
  date_text: ''
})

onMounted(() => {
  loadSessions()
  loadPopularTemplates()
})

// ========== 会话管理 ==========
async function loadSessions() {
  sessionLoading.value = true
  try {
    const res = await listSessions()
    sessions.value = res.data || []
    if (sessions.value.length > 0 && !sessionId.value) {
      await selectSession(sessions.value[0])
    }
  } catch (e) {
    console.error('加载会话失败', e)
  } finally {
    sessionLoading.value = false
  }
}

async function selectSession(s) {
  sessionId.value = s.id
  messages.value = []
  pendingAttachments.value = []
  loading.value = true
  try {
    const res = await getMessages(s.id)
    const msgs = res.data || []
    messages.value = msgs.map(m => ({
      role: m.role,
      content: m.content,
      sources: m.sources || [],
      attachments: m.attachments || [],
      created_at: m.created_at
    }))
  } catch (e) {
    ElMessage.error('加载历史消息失败')
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

function createNewSession() {
  sessionId.value = null
  messages.value = []
  pendingAttachments.value = []
  nextTick(() => inputRef.value?.focus())
}

async function deleteSession(s) {
  try {
    await ElMessageBox.confirm('确定删除该会话？', '确认', { type: 'warning' })
    const token = localStorage.getItem('token') || ''
    await axios.delete(`/api/v1/chat/admin/sessions/${s.id}`, {
      headers: { Authorization: `Bearer ${token}` }
    })
    ElMessage.success('已删除')
    if (sessionId.value === s.id) {
      sessionId.value = null
      messages.value = []
    }
    loadSessions()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

// ========== 附件上传 ==========
async function handleAttachmentSelect(file) {
  const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
  if (!ALLOWED_EXTS.includes(ext)) {
    ElMessage.error(`不支持的文件类型 ${ext}`)
    return
  }
  if (file.size > 50 * 1024 * 1024) {
    ElMessage.error('文件大小不能超过 50MB')
    return
  }
  if (pendingAttachments.value.length >= MAX_ATTACHMENTS) {
    ElMessage.warning(`最多同时上传 ${MAX_ATTACHMENTS} 个附件`)
    return
  }

  const localId = Date.now() + '_' + Math.random().toString(36).slice(2, 8)
  const isImage = ['.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tif', '.tiff'].includes(ext)
  pendingAttachments.value.push({
    localId, id: null, filename: file.name, kind: isImage ? 'image' : 'doc',
    status: 'uploading', note: ''
  })
  uploadingAttachment.value = true
  try {
    const res = await uploadChatAttachments([file.raw])
    const att = res.data.attachments[0]
    const item = pendingAttachments.value.find(a => a.localId === localId)
    if (item) {
      item.id = att.id
      item.kind = att.kind
      item.note = att.parse_note || ''
      item.status = att.parse_status === 'failed' ? 'error' : 'ready'
    }
    if (att.parse_status === 'failed') {
      ElMessage.warning(`${att.filename} ${att.parse_note || '解析失败'}，发送后 AI 将无法读取该附件内容`)
    } else {
      ElMessage.success(`${att.filename} 已解析${att.kind === 'image' ? '（OCR）' : ''}`)
    }
  } catch (e) {
    const item = pendingAttachments.value.find(a => a.localId === localId)
    if (item) { item.status = 'error'; item.note = e.response?.data?.detail || '上传失败' }
    ElMessage.error(e.response?.data?.detail || '附件上传失败')
  } finally {
    uploadingAttachment.value = false
  }
}

function removePendingAttachment(idx) {
  pendingAttachments.value.splice(idx, 1)
}

// ========== 原有功能 ==========
async function loadPopularTemplates() {
  try {
    const res = await axios.get('/api/v1/templates/', {
      params: { limit: 6 },
      headers: { Authorization: `Bearer ${localStorage.getItem('token')}` }
    })
    popularTemplates.value = (res.data || []).slice(0, 6)
  } catch (e) {
    console.error('加载模板失败', e)
  }
}

function goToTemplates() {
  router.push('/templates')
}

function goToKnowledge() {
  router.push('/knowledge')
}

function focusInput() {
  inputRef.value?.focus()
}

function quickUseTemplate(tmpl) {
  router.push({
    path: '/templates',
    query: { use: tmpl.id }
  })
}

function renderMd(text) {
  if (!text) return ''
  return text
    .replace(/^# (.*$)/gim, '<h1 style="text-align:center;font-size:20px;">$1</h1>')
    .replace(/^## (.*$)/gim, '<h2 style="font-size:17px;margin:12px 0 6px;">$1</h2>')
    .replace(/^### (.*$)/gim, '<h3 style="font-size:15px;">$1</h3>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
}

async function copyText(text) {
  await navigator.clipboard.writeText(text)
  ElMessage.success('已复制')
}

function openExportDialog(msg) {
  currentExportMsg.value = msg
  const titleMatch = msg.content.match(/^#\s+(.+)$/m)
  const today = new Date()
  const dateStr = today.getFullYear() + '年' + (today.getMonth() + 1) + '月' + today.getDate() + '日'
  exportForm.value = {
    title: titleMatch ? titleMatch[1].trim() : '公文',
    format: 'normal',
    doc_number: '',
    recipient: '',
    signature: '',
    date_text: dateStr
  }
  exportDialogVisible.value = true
}

async function exportWord() {
  if (!currentExportMsg.value) return
  exportLoading.value = true
  try {
    const api = exportForm.value.format === 'official' ? exportOfficial : exportDocx
    const payload = {
      content: currentExportMsg.value.content,
      title: exportForm.value.title,
      doc_number: exportForm.value.doc_number,
      recipient: exportForm.value.recipient,
      signature: exportForm.value.signature,
      date_text: exportForm.value.date_text,
      use_red_header: exportForm.value.format === 'official'
    }
    const response = await api(payload)
    const blob = new Blob([response.data], {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = exportForm.value.title + '.docx'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    ElMessage.success('Word 文档导出成功')
    exportDialogVisible.value = false
  } catch (err) {
    console.error('导出失败:', err)
    ElMessage.error('导出失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    exportLoading.value = false
  }
}

function send() {
  if (!canSend.value || loading.value) return
  const message = input.value.trim() || '请阅读并理解我上传的材料。'
  const attachmentIds = pendingAttachments.value
    .filter(a => a.status === 'ready' && a.id)
    .map(a => a.id)
  input.value = ''
  loading.value = true

  sendChat({
    message,
    session_id: sessionId.value,
    use_rag: useRag.value,
    attachment_ids: attachmentIds.length ? attachmentIds : undefined
  }).then(async res => {
    sessionId.value = res.data.session_id
    pendingAttachments.value = []
    // 重新拉取该会话的完整历史，确保时间戳是后端真实时间
    await loadSessionMessages(sessionId.value)
    // 刷新会话列表（更新标题）
    loadSessions()
  }).catch(err => {
    ElMessage.error(err.response?.data?.detail || '发送失败')
    messages.value.push({
      role: 'assistant',
      content: '发送失败，请重试'
    })
  }).finally(() => {
    loading.value = false
  })
}

async function loadSessionMessages(sid) {
  try {
    const res = await getMessages(sid)
    const msgs = res.data || []
    messages.value = msgs.map(m => ({
      role: m.role,
      content: m.content,
      sources: m.sources || [],
      attachments: m.attachments || [],
      created_at: m.created_at
    }))
  } catch (e) {
    console.error('加载消息失败', e)
  }
}

function formatTime(d) {
  if (!d) return ''
  const date = new Date(d)
  const now = new Date()
  const isToday = date.toDateString() === now.toDateString()
  if (isToday) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return (date.getMonth() + 1) + '月' + date.getDate() + '日'
}

function scrollToBottom() {
  nextTick(() => {
    msgRef.value?.scrollTo(0, msgRef.value.scrollHeight)
  })
}

watch(() => messages.value.length, () => {
  scrollToBottom()
})
</script>

<style scoped>
.chat-container { height: 100vh; overflow: hidden; }

/* 左侧会话列表 */
.session-sidebar {
  background: #f5f7fa;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
}
.sidebar-header {
  height: 60px;
  padding: 0 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e4e7ed;
  background: white;
}
.sidebar-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.session-item {
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
  transition: all 0.2s;
}
.session-item:hover {
  background: #ecf5ff;
}
.session-item.active {
  background: #409EFF;
  color: white;
}
.session-item.active .session-time {
  color: rgba(255,255,255,0.7);
}
.session-info {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
.session-title {
  font-size: 14px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.session-time {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.session-delete {
  opacity: 0;
  transition: opacity 0.2s;
  color: inherit;
}
.session-item:hover .session-delete {
  opacity: 1;
}
.session-item.active .session-delete {
  color: white;
}

/* 右侧聊天区 */
.chat-main {
  padding: 0;
  background: #f5f5f5;
  display: flex;
  flex-direction: column;
}
.chat-area {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.quick-actions {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  background: #f5f5f5;
}
.quick-actions h3 {
  font-size: 24px;
  color: #303133;
  margin-bottom: 8px;
}
.quick-actions .subtitle {
  font-size: 14px;
  color: #909399;
  margin-bottom: 30px;
}
.action-cards {
  width: 100%;
  max-width: 800px;
  margin-bottom: 30px;
}
.action-card {
  cursor: pointer;
  text-align: center;
  padding: 24px;
  transition: all 0.3s;
}
.action-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0,0,0,0.1);
}
.action-card h4 {
  margin: 12px 0 8px;
  font-size: 16px;
  color: #303133;
}
.action-card p {
  font-size: 13px;
  color: #909399;
}
.quick-templates {
  text-align: center;
}
.template-tag {
  cursor: pointer;
  padding: 8px 16px;
}
.template-tag:hover {
  background: #ecf5ff;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  background: #f5f5f5;
}
.msg {
  display: flex;
  gap: 15px;
  margin-bottom: 20px;
  max-width: 85%;
}
.msg.user { margin-left: auto; flex-direction: row-reverse; }
.msg-avatar { flex-shrink: 0; }
.msg-content {
  background: white;
  padding: 15px;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
.msg.user .msg-content { background: #1a5fb4; color: white; }
.msg-meta {
  font-size: 12px;
  color: #999;
  margin-bottom: 8px;
  display: flex;
  gap: 10px;
}
.msg.user .msg-meta { color: rgba(255,255,255,0.8); }
.msg-time { color: #c0c4cc; }
.msg-text { word-break: break-all; }
.msg-attachments {
  margin-bottom: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.attachment-tag { display: inline-flex; align-items: center; gap: 4px; }
.att-note { font-size: 11px; opacity: 0.8; }
.msg-sources-detailed {
  margin-top: 16px;
  padding-top: 8px;
  border-top: 1px dashed #e0e0e0;
}
.source-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
  color: #606266;
}
.source-num {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #409EFF;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  flex-shrink: 0;
}
.source-name { color: #409EFF; }
.msg-actions {
  margin-top: 8px;
  border-top: 1px dashed #eee;
  padding-top: 6px;
}
.input-area {
  padding: 20px;
  background: white;
  border-top: 1px solid #e0e0e0;
}
.pending-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}
.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 10px;
}
.input-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.md-body { font-size: 15px; line-height: 1.9; color: #303133; }
.md-body h1 { text-align: center; }
</style>
