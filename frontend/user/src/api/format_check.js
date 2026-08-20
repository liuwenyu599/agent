import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 180000  // 校验含 AI 辅助，可能较慢
})

api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

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

// ========== 格式校验 ==========
export const checkFormat = (file, useAi = true, ruleIds = null) => {
  const formData = new FormData()
  formData.append('file', file)
  const params = { use_ai: useAi }
  if (ruleIds && ruleIds.length) params.rule_ids = ruleIds.join(',')
  return api.post('/format-check/check', formData, {
    params,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}
export const listCheckRecords = (params) => api.get('/format-check/records', { params })
export const getCheckRecord = (id) => api.get(`/format-check/records/${id}`)

// ========== 审阅模式 ==========
// 源文档段落（左栏）
export const getRecordParagraphs = (id) => api.get(`/format-check/records/${id}/paragraphs`)
// 修正预览（右栏，按已接受的问题实时生成）
export const previewFix = (recordId, acceptedIndices) =>
  api.post('/format-check/preview-fix', {
    record_id: recordId,
    accepted_indices: acceptedIndices
  })
// 下载修正稿（blob）
export const downloadFixed = (recordId, acceptedIndices) =>
  api.post('/format-check/fix', {
    record_id: recordId,
    accepted_indices: acceptedIndices
  }, { responseType: 'blob' })

// ========== 格式规则 ==========
export const listFormatRules = () => api.get('/format-check/rules')
export const createFormatRule = (data) => api.post('/format-check/rules', data)
export const updateFormatRule = (id, data) => api.put(`/format-check/rules/${id}`, data)
export const deleteFormatRule = (id) => api.delete(`/format-check/rules/${id}`)

// ========== 对话附件 ==========
export const uploadChatAttachments = (files) => {
  const formData = new FormData()
  files.forEach(f => formData.append('files', f))
  return api.post('/chat/attachments/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}
export const deleteChatAttachment = (id) => api.delete(`/chat/attachments/${id}`)