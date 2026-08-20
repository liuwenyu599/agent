// 工作流 API —— 新建文件：frontend/user/src/api/workflow.js
// 复用项目已有的 createApi() 封装工厂（与 format_check.js、knowledge.js 同一套体系）
import { createApi } from './config.js'

const api = createApi()

// ========== 模板（写死在后端常量，直接返回） ==========
export const listWorkflowTemplates = () => api.get('/workflow/templates')

// ========== 实例 ==========
export const listWorkflowInstances = (params) => api.get('/workflow/instances', { params })
export const createWorkflowInstance = (data) => api.post('/workflow/instances', data)
export const getWorkflowInstance = (id) => api.get(`/workflow/instances/${id}`)
export const updateWorkflowInstance = (id, data) => api.put(`/workflow/instances/${id}`, data)
export const deleteWorkflowInstance = (id) => api.delete(`/workflow/instances/${id}`)

// ========== 节点 ==========
export const updateWorkflowNode = (nodeInstId, data) => api.put(`/workflow/nodes/${nodeInstId}`, data)
export const generateWorkflowNode = (nodeInstId, instruction = '', save = true) =>
  api.post(`/workflow/nodes/${nodeInstId}/generate`, { instruction, save })

// ========== 会议核心上下文（基础信息节点的 AI 入口） ==========
export const parseNaturalLanguage = (instId, text) =>
  api.post(`/workflow/instances/${instId}/parse-natural-language`, { text })
export const parseKeyValue = (instId, text) =>
  api.post(`/workflow/instances/${instId}/parse-key-value`, { text })
export const confirmWorkflowContext = (instId, workflowContext, confirmOverrides = {}) =>
  api.post(`/workflow/instances/${instId}/confirm-context`,
    { workflow_context: workflowContext, confirm_overrides: confirmOverrides })