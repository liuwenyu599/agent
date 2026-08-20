import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000
})

// 请求拦截器：添加 token
api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：处理 401
api.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// ========== 知识库 ==========
export const listKBs = () => api.get('/knowledge/list')
export const createKB = (data) => api.post('/knowledge/create', data)
export const updateKB = (id, data) => api.put(`/knowledge/${id}`, data)
export const deleteKB = (id) => api.delete(`/knowledge/${id}`)
export const getKBStats = () => api.get('/knowledge/stats')

// ========== 文档 ==========
export const listDocs = (kbId, params) => api.get(`/knowledge/${kbId}/documents`, { params })
export const uploadDoc = (kbId, file, onProgress) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post(`/knowledge/upload?kb_id=${kbId}`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: onProgress
  })
}
export const getDoc = (docId) => api.get(`/knowledge/documents/${docId}`)
export const updateDocument = (docId, data) => api.put(`/knowledge/documents/${docId}`, data)
export const deleteDoc = (docId) => api.delete(`/knowledge/documents/${docId}`)

// ========== 批量导入 ==========
export const batchUpload = (kbId, files, onProgress) => {
  const formData = new FormData()
  files.forEach(f => formData.append('files', f))
  return api.post(`/knowledge/batch-upload?kb_id=${kbId}`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: onProgress
  })
}

export const getBatchTasks = () => api.get('/knowledge/batch-tasks')
export const getBatchTask = (taskId) => api.get(`/knowledge/batch-tasks/${taskId}`)

// ========== 导出 ==========
export const exportDocx = (data) => api.post('/chat/export/docx', data, { responseType: 'blob' })
export const exportOfficial = (data) => api.post('/chat/export/official', data, { responseType: 'blob' })

// ========== 审核 ==========
export const getPendingDocs = () => api.get('/knowledge/pending')
export const reviewDoc = (data) => api.post('/knowledge/review', data)

// ========== 聊天 ==========
// 写作类生成耗时较长（本地 vLLM 常超 30s），单独放宽到 180s，避免后端已返回但前端误判失败
export const sendChat = (data) => api.post('/chat/send', data, { timeout: 180000 })
export const listSessions = () => api.get('/chat/sessions')
export const getMessages = (sessionId) => api.get(`/chat/sessions/${sessionId}/messages`)
