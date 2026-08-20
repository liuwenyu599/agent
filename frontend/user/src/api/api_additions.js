// 前端 API 封装参考（第四阶段 UI 对接用）
// 建议：知识库部分并入 frontend/user/src/api/knowledge.js，参考材料新建 api/references.js
// 调用风格与现有 api/knowledge.js 保持一致（项目内已有 request 封装，请沿用）

import request from './config' // 按项目现有封装调整

// ===== 知识库：网页链接导入 =====
// 导入若干链接（单个或多个）
export const importUrls = (kbId, urls) =>
  request.post('/knowledge/import-urls', { kb_id: kbId, urls })

// 粘贴一段含链接的文本导入
export const importUrlsText = (kbId, text) =>
  request.post('/knowledge/import-urls-text', { kb_id: kbId, text })

// Excel 批量导入（FormData 上传 .xlsx）
export const importUrlsExcel = (kbId, file) => {
  const fd = new FormData()
  fd.append('file', file)
  return request.post(`/knowledge/import-urls-excel?kb_id=${kbId}`, fd)
}
// 三个接口统一返回：
// { success_count, duplicated_count, failed_count,
//   success: [{url,title,doc_id,status}],
//   duplicated: [{url,title,reason}],
//   failed: [{url,title,reason}] }
// 前端按需求二展示：✓成功 N / ↻已存在 N / ⚠失败 N + 失败列表 + [重新导入失败项]
//（重新导入 = 把 failed 里的 url 再调一次 importUrls）

// ===== 模板固定参考材料 =====
export const listTemplateRefs = (templateId) =>
  request.get(`/references/template/${templateId}`)
export const uploadTemplateRef = (templateId, file) => {
  const fd = new FormData(); fd.append('file', file)
  return request.post(`/references/template/${templateId}/upload`, fd)
}
export const addTemplateTextRef = (templateId, name, text) =>
  request.post(`/references/template/${templateId}/text`, { name, text })
export const addTemplateUrlRef = (templateId, url, name) =>
  request.post(`/references/template/${templateId}/url`, { url, name })
export const deleteTemplateRef = (refId) =>
  request.delete(`/references/template/refs/${refId}`)

// ===== 当前任务佐证材料（不进知识库） =====
export const listTaskRefs = (params) => request.get('/references/task', { params })
export const uploadTaskRef = (file, templateId) => {
  const fd = new FormData(); fd.append('file', file)
  const q = templateId ? `?template_id=${templateId}` : ''
  return request.post(`/references/task/upload${q}`, fd)
}
export const addTaskTextRef = (payload) => request.post('/references/task/text', payload)
export const addTaskUrlRef = (payload) => request.post('/references/task/url', payload)
export const deleteTaskRef = (refId) => request.delete(`/references/task/${refId}`)
// 用户主动"加入知识库"
export const promoteTaskRef = (refId, kbId) =>
  request.post(`/references/task/${refId}/promote`, { kb_id: kbId })

// ===== 智能写作调用 =====
// /chat/send 请求体新增字段：
// {
//   message, reference_template_id,          // 已有
//   task_reference_ids: ["...", "..."],      // 新增：当前写作材料 id 列表
// }
// 模板固定参考材料不需要前端传 id —— 后端按 reference_template_id 自动加载。


