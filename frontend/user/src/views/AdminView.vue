<template>
<div>
  <el-container class="admin-container">
    <el-main class="admin-main">
      <h2>管理后台</h2>
      
      <el-tabs v-model="activeTab" type="border-card" @tab-change="onTabChange">
        <el-tab-pane label="数据概览" name="dashboard">
          <el-row :gutter="20" class="stats-row">
            <el-col :span="6"><el-card shadow="hover" class="stat-card" @click="activeTab = 'users'"><div class="stat-icon blue"><el-icon :size="32"><User /></el-icon></div><div class="stat-info"><div class="stat-num">{{ stats.user_count }}</div><div class="stat-label">总用户数</div></div></el-card></el-col>
            <el-col :span="6"><el-card shadow="hover" class="stat-card" @click="activeTab = 'documents'"><div class="stat-icon green"><el-icon :size="32"><Document /></el-icon></div><div class="stat-info"><div class="stat-num">{{ stats.doc_count }}</div><div class="stat-label">文档总数</div></div></el-card></el-col>
            <el-col :span="6"><el-card shadow="hover" class="stat-card" @click="activeTab = 'sessions'"><div class="stat-icon orange"><el-icon :size="32"><ChatDotRound /></el-icon></div><div class="stat-info"><div class="stat-num">{{ stats.session_count }}</div><div class="stat-label">会话总数</div></div></el-card></el-col>
            <el-col :span="6"><el-card shadow="hover" class="stat-card" @click="activeTab = 'knowledge'"><div class="stat-icon purple"><el-icon :size="32"><Collection /></el-icon></div><div class="stat-info"><div class="stat-num">{{ stats.kb_count }}</div><div class="stat-label">知识库数</div></div></el-card></el-col>
          </el-row>
        </el-tab-pane>
        
        <el-tab-pane label="用户管理" name="users">
          <div class="toolbar">
            <el-input v-model="userSearch" placeholder="搜索用户名/姓名/部门" clearable style="width: 300px" @input="filterUsers"><template #prefix><el-icon><Search /></el-icon></template></el-input>
            <el-button type="primary" @click="openCreateUserDialog"><el-icon><Plus /></el-icon> 新建用户</el-button>
          </div>
          <el-table :data="filteredUsers" stripe v-loading="userLoading">
            <el-table-column type="index" width="50" />
            <el-table-column prop="username" label="用户名" width="120" />
            <el-table-column prop="real_name" label="真实姓名" width="120" />
            <el-table-column prop="email" label="邮箱" width="180" />
            <el-table-column prop="department" label="部门" width="150" />
            <el-table-column prop="role" label="角色" width="120"><template #default="{ row }"><el-tag :type="roleType(row.role)">{{ roleText(row.role) }}</el-tag></template></el-table-column>
            <el-table-column prop="is_active" label="状态" width="100"><template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'danger'">{{ row.is_active ? '正常' : '禁用' }}</el-tag></template></el-table-column>
            <el-table-column prop="created_at" label="注册时间" width="180"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="editUser(row)">编辑</el-button>
                <el-button link type="primary" @click="resetPassword(row)">重置密码</el-button>
                <el-button link :type="row.is_active ? 'danger' : 'success'" @click="toggleUserStatus(row)">{{ row.is_active ? '禁用' : '启用' }}</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        
        <el-tab-pane label="知识库管理" name="knowledge">
          <div class="toolbar"><el-button type="primary" @click="openCreateKBDialog"><el-icon><Plus /></el-icon> 新建知识库</el-button></div>
          <el-table :data="kbList" stripe v-loading="kbLoading">
            <el-table-column type="index" width="50" />
            <el-table-column prop="name" label="知识库名称" min-width="200" />
            <el-table-column prop="type" label="类型" width="100"><template #default="{ row }"><el-tag :type="row.type === 'public' ? 'success' : 'info'">{{ row.type === 'public' ? '公共' : '个人' }}</el-tag></template></el-table-column>
            <el-table-column prop="doc_count" label="文档数" width="100" align="center" />
            <el-table-column prop="created_at" label="创建时间" width="180"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
            <el-table-column label="操作" width="200" fixed="right"><template #default="{ row }"><el-button link type="danger" @click="deleteKB(row)">删除</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>
        
        <el-tab-pane label="文档审核" name="documents">
          <el-tabs v-model="docTab" @tab-change="onDocTabChange">
            <el-tab-pane label="待审核" name="pending">
              <el-table :data="pendingDocs" stripe v-loading="docLoading">
                <el-table-column type="index" width="50" />
                <el-table-column prop="title" label="文档标题" min-width="200" show-overflow-tooltip />
                <el-table-column prop="doc_type" label="类型" width="100" />
                <el-table-column prop="kb_name" label="所属知识库" width="150" />
                <el-table-column prop="uploader_name" label="上传者" width="120" />
                <el-table-column prop="created_at" label="上传时间" width="170"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
                <el-table-column label="操作" width="100" fixed="right">
                  <template #default="{ row }">
                    <el-button size="small" type="primary" @click="previewDoc(row)">预览</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="已发布" name="published">
              <el-table :data="publishedDocs" stripe v-loading="docLoading">
                <el-table-column type="index" width="50" />
                <el-table-column prop="title" label="文档标题" min-width="200" show-overflow-tooltip />
                <el-table-column prop="doc_type" label="类型" width="100" />
                <el-table-column prop="kb_name" label="所属知识库" width="150" />
                <el-table-column prop="uploader_name" label="上传者" width="120" />
                <el-table-column prop="reviewer_name" label="审核人" width="120" />
                <el-table-column prop="reviewed_at" label="审核时间" width="170"><template #default="{ row }">{{ formatDate(row.reviewed_at) }}</template></el-table-column>
                <el-table-column label="操作" width="150" fixed="right">
                  <template #default="{ row }">
                    <el-button link type="primary" @click="previewDoc(row)">预览</el-button>
                    <el-button link type="danger" @click="archiveDoc(row)">归档</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="已驳回" name="rejected">
              <el-table :data="rejectedDocs" stripe v-loading="docLoading">
                <el-table-column type="index" width="50" />
                <el-table-column prop="title" label="文档标题" min-width="200" show-overflow-tooltip />
                <el-table-column prop="kb_name" label="所属知识库" width="150" />
                <el-table-column prop="uploader_name" label="上传者" width="120" />
                <el-table-column prop="review_comment" label="驳回原因" min-width="200" show-overflow-tooltip />
                <el-table-column label="操作" width="100" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="previewDoc(row)">预览</el-button></template></el-table-column>
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>
        
        <el-tab-pane label="会话管理" name="sessions">
          <div class="toolbar"><el-input v-model="sessionSearch" placeholder="搜索会话标题" clearable style="width: 300px" @input="filterSessions" /></div>
          <el-table :data="filteredSessions" stripe v-loading="sessionLoading">
            <el-table-column type="index" width="50" />
            <el-table-column prop="title" label="会话标题" min-width="200" show-overflow-tooltip />
            <el-table-column prop="user_name" label="用户" width="120" />
            <el-table-column prop="message_count" label="消息数" width="100" align="center" />
            <el-table-column prop="created_at" label="创建时间" width="170"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="viewSession(row)">查看</el-button>
                <el-button link type="danger" @click="deleteSession(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        
        <el-tab-pane label="系统设置" name="settings">
          <el-card class="settings-card" shadow="never">
            <template #header><span>模型配置</span></template>
            <el-form :model="settings" label-width="150px">
              <el-form-item label="模型名称"><el-input v-model="settings.model_name" placeholder="Qwen2.5-14B-Instruct" /></el-form-item>
              <el-form-item label="Temperature"><el-slider v-model="settings.temperature" :min="0" :max="1" :step="0.1" show-stops /></el-form-item>
              <el-form-item label="Max Tokens"><el-input-number v-model="settings.max_tokens" :min="512" :max="8192" :step="512" /></el-form-item>
              <el-form-item label="RAG 检索数量"><el-input-number v-model="settings.rag_top_k" :min="1" :max="20" /></el-form-item>
              <el-form-item label="相似度阈值"><el-slider v-model="settings.rag_threshold" :min="0" :max="1" :step="0.05" show-stops /></el-form-item>
            </el-form>
          </el-card>
          <el-card class="settings-card" shadow="never">
            <template #header><span>系统参数</span></template>
            <el-form :model="settings" label-width="150px">
              <el-form-item label="Token 有效期(小时)"><el-input-number v-model="settings.token_expire" :min="1" :max="168" /></el-form-item>
              <el-form-item label="最大上传文件大小(MB)"><el-input-number v-model="settings.max_upload_size" :min="1" :max="8192" /></el-form-item>
            </el-form>
          </el-card>
          <div class="settings-actions">
            <el-button type="primary" @click="saveSettings" :loading="saving">保存设置</el-button>
            <el-button @click="resetSettings">重置</el-button>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-main>
  </el-container>
  
  <el-dialog v-model="userDialogVisible" :title="isEditUser ? '编辑用户' : '新建用户'" width="450px">
    <el-form :model="userForm" label-width="90px" :rules="userRules" ref="userFormRef">
      <el-form-item label="用户名" prop="username"><el-input v-model="userForm.username" :disabled="isEditUser" /></el-form-item>
      <el-form-item label="邮箱" prop="email"><el-input v-model="userForm.email" /></el-form-item>
      <el-form-item label="密码" prop="password" v-if="!isEditUser"><el-input v-model="userForm.password" type="password" show-password /></el-form-item>
      <el-form-item label="真实姓名"><el-input v-model="userForm.real_name" /></el-form-item>
      <el-form-item label="部门"><el-input v-model="userForm.department" /></el-form-item>
      <el-form-item label="角色">
        <el-select v-model="userForm.role" style="width: 100%">
          <el-option label="普通用户" value="user" />
          <el-option label="知识管理员" value="knowledge_admin" />
          <el-option label="系统管理员" value="developer" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="userDialogVisible = false">取消</el-button>
      <el-button type="primary" @click="submitUser" :loading="userSubmitting">确定</el-button>
    </template>
  </el-dialog>
  
  <el-dialog v-model="resetPwdVisible" title="重置密码" width="400px">
    <el-form :model="pwdForm" label-width="90px">
      <el-form-item label="新密码"><el-input v-model="pwdForm.password" type="password" show-password /></el-form-item>
      <el-form-item label="确认密码"><el-input v-model="pwdForm.confirm" type="password" show-password /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="resetPwdVisible = false">取消</el-button>
      <el-button type="primary" @click="submitResetPwd" :loading="pwdLoading">确定</el-button>
    </template>
  </el-dialog>
  
  <el-dialog v-model="previewVisible" title="文档预览" width="800px" top="5vh">
    <div v-if="currentDoc" class="doc-preview">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="标题" :span="2"><strong>{{ currentDoc.title }}</strong></el-descriptions-item>
        <el-descriptions-item label="类型">{{ currentDoc.doc_type }}</el-descriptions-item>
        <el-descriptions-item label="状态"><el-tag :type="statusType(currentDoc.status)">{{ statusText(currentDoc.status) }}</el-tag></el-descriptions-item>
        <el-descriptions-item label="上传者">{{ currentDoc.uploader_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="审核人">{{ currentDoc.reviewer_name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="审核意见" :span="2">{{ currentDoc.review_comment || '-' }}</el-descriptions-item>
      </el-descriptions>
    </div>
  </el-dialog>
  
  <el-dialog v-model="sessionDetailVisible" title="会话详情" width="700px">
    <div v-if="currentSession" class="session-detail">
      <p><strong>标题：</strong>{{ currentSession.title }}</p>
      <p><strong>用户：</strong>{{ currentSession.user_name }}</p>
      <p><strong>创建时间：</strong>{{ formatDate(currentSession.created_at) }}</p>
      <el-divider />
      <div class="session-messages">
        <div v-for="(msg, idx) in currentSession.messages" :key="idx" :class="['session-msg', msg.role]">
          <el-tag :type="msg.role === 'user' ? 'primary' : 'success'" size="small">{{ msg.role === 'user' ? '用户' : '助手' }}</el-tag>
          <div class="msg-content-text">{{ msg.content }}</div>
        </div>
      </div>
    </div>
  </el-dialog>
</div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { User, Collection, Document, ChatDotRound, Plus, Search } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import axios from 'axios'

const router = useRouter()
const authStore = useAuthStore()

const activeTab = ref('dashboard')
const stats = ref({ user_count: 0, doc_count: 0, session_count: 0, kb_count: 0 })
const userList = ref([])
const filteredUsers = ref([])
const userSearch = ref('')
const userLoading = ref(false)
const userDialogVisible = ref(false)
const isEditUser = ref(false)
const userSubmitting = ref(false)
const userFormRef = ref(null)
const userForm = ref({ username: '', email: '', password: '', real_name: '', department: '', role: 'user' })
const userRules = { username: [{ required: true, message: '请输入用户名', trigger: 'blur' }], email: [{ required: true, message: '请输入邮箱', trigger: 'blur' }], password: [{ required: true, message: '请输入密码', trigger: 'blur' }] }
const resetPwdVisible = ref(false)
const pwdLoading = ref(false)
const pwdForm = ref({ user_id: '', password: '', confirm: '' })
const kbList = ref([])
const kbLoading = ref(false)
const docTab = ref('pending')
const pendingDocs = ref([])
const publishedDocs = ref([])
const rejectedDocs = ref([])
const docLoading = ref(false)
const previewVisible = ref(false)
const currentDoc = ref(null)
const sessionList = ref([])
const filteredSessions = ref([])
const sessionSearch = ref('')
const sessionLoading = ref(false)
const sessionDetailVisible = ref(false)
const currentSession = ref(null)
const settings = ref({ model_name: 'Qwen2.5-14B-Instruct', temperature: 0.3, max_tokens: 8192, rag_top_k: 5, rag_threshold: 0.5, token_expire: 24, max_upload_size: 50 })
const saving = ref(false)
const token = computed(() => localStorage.getItem('token') || '')
const headers = computed(() => ({ Authorization: `Bearer ${token.value}` }))

onMounted(() => { loadStats(); loadUsers(); loadKBs(); loadPendingDocs(); loadPublishedDocs(); loadRejectedDocs(); loadSessions(); })

function onTabChange(tab) {
  switch (tab) {
    case 'users': loadUsers(); break
    case 'knowledge': loadKBs(); break
    case 'documents': loadPendingDocs(); break
    case 'sessions': loadSessions(); break
  }
}

async function loadStats() { try { const res = await axios.get('/api/v1/knowledge/stats', { headers: headers.value }); stats.value = res.data; } catch (e) { console.error('加载统计失败', e) } }
async function loadUsers() { userLoading.value = true; try { const res = await axios.get('/api/v1/users/', { headers: headers.value }); userList.value = res.data || []; filterUsers(); } catch (e) { ElMessage.error('加载用户失败') } finally { userLoading.value = false } }
function filterUsers() { if (!userSearch.value) { filteredUsers.value = userList.value; return } const kw = userSearch.value.toLowerCase(); filteredUsers.value = userList.value.filter(u => (u.username?.toLowerCase().includes(kw)) || (u.real_name?.toLowerCase().includes(kw)) || (u.department?.toLowerCase().includes(kw))) }
function openCreateUserDialog() { isEditUser.value = false; userForm.value = { username: '', email: '', password: '', real_name: '', department: '', role: 'user' }; userDialogVisible.value = true; }
function editUser(row) { isEditUser.value = true; userForm.value = { ...row, password: '' }; userDialogVisible.value = true; }
async function submitUser() { const valid = await userFormRef.value?.validate().catch(() => false); if (!valid) return; userSubmitting.value = true; try { if (isEditUser.value) { await axios.put(`/api/v1/users/${userForm.value.id}`, { real_name: userForm.value.real_name, department: userForm.value.department, role: userForm.value.role }, { headers: headers.value }); ElMessage.success('修改成功'); } else { await axios.post('/api/v1/users/', userForm.value, { headers: headers.value }); ElMessage.success('创建成功'); } userDialogVisible.value = false; loadUsers(); } catch (e) { ElMessage.error('操作失败: ' + (e.response?.data?.detail || e.message)) } finally { userSubmitting.value = false } }
function resetPassword(row) { pwdForm.value = { user_id: row.id, password: '', confirm: '' }; resetPwdVisible.value = true; }
async function submitResetPwd() { if (pwdForm.value.password !== pwdForm.value.confirm) { ElMessage.error('两次密码不一致'); return } if (!pwdForm.value.password || pwdForm.value.password.length < 6) { ElMessage.error('密码至少6位'); return } pwdLoading.value = true; try { await axios.post(`/api/v1/users/${pwdForm.value.user_id}/reset-password`, { password: pwdForm.value.password }, { headers: headers.value }); ElMessage.success('密码重置成功'); resetPwdVisible.value = false; } catch (e) { ElMessage.error('重置失败: ' + (e.response?.data?.detail || e.message)) } finally { pwdLoading.value = false } }
async function toggleUserStatus(row) { try { await ElMessageBox.confirm(`确定${row.is_active ? '禁用' : '启用'}用户「${row.username}」？`, '确认', { type: 'warning' }); await axios.put(`/api/v1/users/${row.id}`, { is_active: !row.is_active }, { headers: headers.value }); ElMessage.success('操作成功'); loadUsers(); } catch (e) { if (e !== 'cancel') ElMessage.error('操作失败') } }
async function loadKBs() { kbLoading.value = true; try { const res = await axios.get('/api/v1/knowledge/list', { headers: headers.value }); kbList.value = res.data || []; } catch (e) { ElMessage.error('加载知识库失败') } finally { kbLoading.value = false } }
function openCreateKBDialog() { router.push('/knowledge') }
async function deleteKB(row) { try { await ElMessageBox.confirm(`确定删除知识库「${row.name}」？`, '警告', { type: 'warning' }); await axios.delete(`/api/v1/knowledge/${row.id}`, { headers: headers.value }); ElMessage.success('已删除'); loadKBs(); } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') } }
async function loadPendingDocs() { docLoading.value = true; try { const res = await axios.get('/api/v1/knowledge/pending', { headers: headers.value }); pendingDocs.value = res.data || []; } catch (e) { console.error('加载待审核失败', e) } finally { docLoading.value = false } }
async function loadPublishedDocs() { try { const res = await axios.get('/api/v1/knowledge/documents?status=published', { headers: headers.value }); publishedDocs.value = res.data.data || []; } catch (e) { console.error('加载已发布失败', e) } }
async function loadRejectedDocs() { try { const res = await axios.get('/api/v1/knowledge/documents?status=rejected', { headers: headers.value }); rejectedDocs.value = res.data.data || []; } catch (e) { console.error('加载已驳回失败', e) } }
function onDocTabChange(tab) { if (tab === 'pending') loadPendingDocs(); else if (tab === 'published') loadPublishedDocs(); else if (tab === 'rejected') loadRejectedDocs(); }
async function reviewDoc(row, action) { try { await axios.post('/api/v1/knowledge/review', { doc_id: row.id, action, comment: action === 'approved' ? '审核通过' : '不符合要求' }, { headers: headers.value }); ElMessage.success('审核完成'); loadPendingDocs(); loadPublishedDocs(); loadRejectedDocs(); loadStats(); } catch (e) { ElMessage.error('审核失败') } }
function previewDoc(row) { currentDoc.value = row; previewVisible.value = true; }
async function archiveDoc(row) { try { await ElMessageBox.confirm('确定归档该文档？', '确认', { type: 'warning' }); await axios.post(`/api/v1/knowledge/documents/${row.id}/archive`, {}, { headers: headers.value }); ElMessage.success('已归档'); loadPublishedDocs(); loadStats(); } catch (e) { if (e !== 'cancel') ElMessage.error('归档失败') } }
async function loadSessions() { sessionLoading.value = true; try { const res = await axios.get('/api/v1/chat/admin/sessions', { headers: headers.value }); sessionList.value = res.data.data || []; filterSessions(); } catch (e) { console.error('加载会话失败', e) } finally { sessionLoading.value = false } }
function filterSessions() { if (!sessionSearch.value) { filteredSessions.value = sessionList.value; return } const kw = sessionSearch.value.toLowerCase(); filteredSessions.value = sessionList.value.filter(s => s.title?.toLowerCase().includes(kw)); }
async function viewSession(row) { try { const res = await axios.get(`/api/v1/chat/sessions/${row.id}/messages`, { headers: headers.value }); currentSession.value = { ...row, messages: res.data || [] }; sessionDetailVisible.value = true; } catch (e) { ElMessage.error('加载会话详情失败') } }
async function deleteSession(row) { try { await ElMessageBox.confirm('确定删除该会话？此操作不可恢复。', '确认', { type: 'danger' }); await axios.delete(`/api/v1/chat/admin/sessions/${row.id}`, { headers: headers.value }); ElMessage.success('已删除'); loadSessions(); } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') } }
function saveSettings() { localStorage.setItem('admin_settings', JSON.stringify(settings.value)); ElMessage.success('设置已保存（仅本地存储）'); }
function resetSettings() { settings.value = { model_name: 'Qwen2.5-14B-Instruct', temperature: 0.3, max_tokens: 8192, rag_top_k: 5, rag_threshold: 0.5, token_expire: 24, max_upload_size: 50 }; }
function roleType(role) { const map = { developer: 'danger', knowledge_admin: 'warning', user: 'info' }; return map[role] || 'info'; }
function roleText(role) { const map = { developer: '系统管理员', knowledge_admin: '知识管理员', user: '普通用户' }; return map[role] || role; }
function statusType(s) { const map = { published: 'success', pending: 'warning', archived: 'info', rejected: 'danger' }; return map[s] || 'info'; }
function statusText(s) { const map = { published: '已发布', pending: '待审核', archived: '已归档', rejected: '已驳回' }; return map[s] || s; }
function formatDate(d) { if (!d) return '-'; return new Date(d).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }); }
</script>

<style scoped>
.admin-container { height: 100vh; }
.admin-main { background: #f0f2f5; padding: 20px; overflow-y: auto; }
.admin-main h2 { margin: 0 0 20px 0; font-size: 20px; color: #303133; }
.stats-row { margin-bottom: 20px; }
.stat-card { display: flex; align-items: center; padding: 20px; cursor: pointer; }
.stat-card :deep(.el-card__body) { display: flex; align-items: center; gap: 16px; padding: 0; }
.stat-icon { width: 60px; height: 60px; border-radius: 12px; display: flex; align-items: center; justify-content: center; color: #fff; }
.stat-icon.blue { background: linear-gradient(135deg, #409EFF, #79bbff); }
.stat-icon.green { background: linear-gradient(135deg, #67C23A, #95d475); }
.stat-icon.orange { background: linear-gradient(135deg, #E6A23C, #f3d19e); }
.stat-icon.purple { background: linear-gradient(135deg, #9b59b6, #c39bd3); }
.stat-info { flex: 1; }
.stat-num { font-size: 32px; font-weight: bold; color: #303133; line-height: 1; }
.stat-label { font-size: 14px; color: #909399; margin-top: 8px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.settings-card { margin-bottom: 20px; max-width: 800px; }
.settings-actions { display: flex; gap: 12px; margin-top: 20px; }
.doc-preview { padding: 10px; }
.session-detail { padding: 10px; }
.session-messages { max-height: 500px; overflow-y: auto; }
.session-msg { margin-bottom: 15px; padding: 12px; border-radius: 8px; background: #f5f7fa; }
.session-msg.user { background: #ecf5ff; }
.msg-content-text { margin-top: 8px; font-size: 14px; line-height: 1.8; white-space: pre-wrap; }
</style>
