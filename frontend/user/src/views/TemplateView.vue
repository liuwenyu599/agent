<template>
  <div class="template-use-page">
    <el-page-header @back="goBack" :title="templateInfo.name || '模板写作'" />

    <el-row :gutter="20" class="template-layout">
      <!-- 左侧：模板信息 + 表单 -->
      <el-col :span="10">
        <el-card shadow="never" class="template-info-card" v-loading="loading">
          <template #header>
            <div class="card-header">
              <el-icon :size="20"><component :is="templateInfo.icon || 'Document'" /></el-icon>
              <span>{{ templateInfo.name }}</span>
              <el-tag size="small" type="info" style="margin-left:8px">{{ templateInfo.base_type }}</el-tag>
            </div>
          </template>

          <el-descriptions :column="1" border v-if="templateInfo.name">
            <el-descriptions-item label="分类">{{ templateInfo.category }}</el-descriptions-item>
            <el-descriptions-item label="写作风格">{{ templateInfo.writing_style }}</el-descriptions-item>
            <el-descriptions-item label="字数要求">{{ templateInfo.word_count }} 字</el-descriptions-item>
            <el-descriptions-item label="格式">
              <el-tag v-if="templateInfo.need_red_header" size="small">红头</el-tag>
              <el-tag v-if="templateInfo.need_signature" size="small">落款</el-tag>
              <el-tag v-if="templateInfo.need_date" size="small">日期</el-tag>
              <el-tag v-if="templateInfo.need_doc_number" size="small">文号</el-tag>
            </el-descriptions-item>
          </el-descriptions>

          <el-divider content-position="left">填写要素</el-divider>

          <el-form :model="formData" label-position="top" class="template-form">
            <el-form-item
              v-for="field in templateInfo.params_schema"
              :key="field.name"
              :label="field.label + (field.required ? ' *' : '')"
            >
              <el-input
                v-if="field.type === 'input'"
                v-model="formData[field.name]"
                :placeholder="field.placeholder"
              />
              <el-input
                v-else-if="field.type === 'textarea'"
                v-model="formData[field.name]"
                type="textarea"
                :rows="field.rows || 3"
                :placeholder="field.placeholder"
              />
              <el-select
                v-else-if="field.type === 'select'"
                v-model="formData[field.name]"
                style="width:100%"
              >
                <el-option
                  v-for="opt in field.options"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
            </el-form-item>
          </el-form>

          <div class="form-actions">
            <el-button type="primary" size="large" @click="generate" :loading="generating">
              <el-icon><EditPen /></el-icon> 生成公文
            </el-button>
            <el-button size="large" @click="resetForm">重置</el-button>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：生成结果 -->
      <el-col :span="14">
        <el-card shadow="never" class="result-card" v-loading="generating">
          <template #header>
            <div class="card-header">
              <span>生成结果</span>
              <div v-if="result" class="result-actions">
                <el-button size="small" text @click="copyResult">
                  <el-icon><CopyDocument /></el-icon> 复制
                </el-button>
                <el-button size="small" text @click="openExportDialog">
                  <el-icon><Document /></el-icon> 导出 Word
                </el-button>
              </div>
            </div>
          </template>

          <div v-if="!result" class="empty-result">
            <el-empty description="填写左侧要素后点击生成" :image-size="100" />
          </div>

          <div v-else class="result-content">
            <div class="md-body" v-html="renderMd(result)" />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Word 导出对话框 -->
    <el-dialog v-model="exportVisible" title="导出为 Word" width="550px">
      <el-form :model="exportForm" label-width="100px">
        <el-form-item label="文档标题">
          <el-input v-model="exportForm.title" />
        </el-form-item>
        <el-form-item label="导出格式">
          <el-radio-group v-model="exportForm.format">
            <el-radio label="normal">普通格式</el-radio>
            <el-radio label="official">标准公文格式</el-radio>
          </el-radio-group>
        </el-form-item>
        <template v-if="exportForm.format === 'official'">
          <el-form-item label="发文字号"><el-input v-model="exportForm.doc_number" /></el-form-item>
          <el-form-item label="主送机关"><el-input v-model="exportForm.recipient" /></el-form-item>
          <el-form-item label="落款单位"><el-input v-model="exportForm.signature" /></el-form-item>
          <el-form-item label="成文日期"><el-input v-model="exportForm.date_text" /></el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="exportVisible = false">取消</el-button>
        <el-button type="primary" @click="exportWord" :loading="exportLoading">导出</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { EditPen, CopyDocument, Document } from '@element-plus/icons-vue'
import axios from 'axios'

const route = useRoute(), router = useRouter()
const templateId = route.params.id

const loading = ref(false)
const generating = ref(false)
const templateInfo = ref({})
const formData = ref({})
const result = ref('')

// 导出
const exportVisible = ref(false)
const exportLoading = ref(false)
const exportForm = ref({
  title: '',
  format: 'normal',
  doc_number: '',
  recipient: '',
  signature: '',
  date_text: ''
})

const token = ref(localStorage.getItem('token') || '')

onMounted(() => { loadTemplate() })

async function loadTemplate() {
  loading.value = true
  try {
    const res = await axios.get(`/api/v1/templates/${templateId}`, {
      headers: { Authorization: `Bearer ${token.value}` }
    })
    templateInfo.value = res.data || {}
    // 初始化表单
    const init = {}
    for (const f of templateInfo.value.params_schema || []) {
      init[f.name] = ''
    }
    formData.value = init
  } catch (e) {
    ElMessage.error('加载模板失败')
  } finally {
    loading.value = false
  }
}

function goBack() { router.push('/templates') }

function resetForm() {
  const init = {}
  for (const f of templateInfo.value.params_schema || []) {
    init[f.name] = ''
  }
  formData.value = init
  result.value = ''
}

// ========== 核心：生成逻辑（要素表 + 结构参考 + 风格要求） ==========
async function generate() {
  // 校验必填
  for (const f of templateInfo.value.params_schema || []) {
    if (f.required && !formData.value[f.name]?.trim()) {
      ElMessage.warning(`请填写「${f.label}」`)
      return
    }
  }

  generating.value = true
  try {
    // 构建"公文要素表"
    const elements = []
    for (const f of templateInfo.value.params_schema || []) {
      const val = formData.value[f.name]
      if (val && val.trim()) {
        elements.push(`${f.label}：${val.trim()}`)
      }
    }

    const t = templateInfo.value

    // 构建 system_prompt（融合风格 + 格式 + 字数）
    let systemPrompt = t.system_prompt || '你是一位资深的司法行政公文写作专家。'
    systemPrompt += `\\n\\n写作要求：\\n1. 写作风格：${t.writing_style || '正式公文'}；`
    systemPrompt += `\\n2. 字数要求：约 ${t.word_count || 1000} 字；`
    if (t.need_red_header) systemPrompt += '\\n3. 需要包含红头（发文机关标识）；'
    if (t.need_signature) systemPrompt += '\\n4. 需要包含落款（发文机关署名）；'
    if (t.need_date) systemPrompt += '\\n5. 需要包含成文日期；'
    if (t.need_doc_number) systemPrompt += '\\n6. 需要包含发文字号；'
    systemPrompt += '\n\n请根据以下要素生成完整的公文正文，不要简单填空，要根据要素展开成流畅、规范的公文。'
    systemPrompt += '\n\n【格式要求】\n1. 不要输出 Markdown 标记（如 **、## 等），不要输出 HTML 标签；\n2. 纯文本输出，段落之间用空行分隔；\n3. 一级标题（如"一、评查范围"）独占一行，前后空一行；\n4. 落款信息（联系人、电话、单位、日期、文号）每项独占一行；\n5. 不要输出解释性文字，直接给公文正文。'

    // 构建 user message（要素表 + 结构参考）
    let userMessage = '请根据以下要素生成公文：\\n\\n'
    userMessage += elements.join('\\n')
    if (t.content_template) {
      userMessage += `\\n\\n【结构参考】\\n${t.content_template}`
    }

    const res = await axios.post('/api/v1/chat/send', {
      message: userMessage,
      system_prompt: systemPrompt,
      use_rag: true,
      source: 'template'
    }, {
      headers: { Authorization: `Bearer ${token.value}` }
    })

    result.value = res.data.reply || ''
    ElMessage.success('生成完成')
  } catch (e) {
    ElMessage.error('生成失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    generating.value = false
  }
}

function renderMd(text) {
  if (!text) return ''
  // 清理 Markdown 标记
  let cleaned = text
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/^#+\s*/gm, '')
    .replace(/<[^>]+>/g, '')
  // 用 pre-wrap 包裹，浏览器会自动保留换行符
  return '<div style="white-space:pre-wrap;line-height:1.9;font-size:15px;text-align:justify;">' + cleaned + '</div>'
}
async function copyResult() {
  await navigator.clipboard.writeText(result.value)
  ElMessage.success('已复制')
}

function openExportDialog() {
  const titleMatch = result.value.match(/^#\\s+(.+)$/m)
  const today = new Date()
  const dateStr = today.getFullYear() + '年' + (today.getMonth() + 1) + '月' + today.getDate() + '日'
  exportForm.value = {
    title: titleMatch ? titleMatch[1].trim() : (templateInfo.value.name || '公文'),
    format: 'normal',
    doc_number: '',
    recipient: '',
    signature: '',
    date_text: dateStr
  }
  exportVisible.value = true
}

async function exportWord() {
  exportLoading.value = true
  try {
    const api = exportForm.value.format === 'official'
      ? () => axios.post('/api/v1/chat/export/official', exportForm.value, { responseType: 'blob', headers: { Authorization: `Bearer ${token.value}` } })
      : () => axios.post('/api/v1/chat/export/docx', { ...exportForm.value, content: result.value, use_red_header: exportForm.value.format === 'official' }, { responseType: 'blob', headers: { Authorization: `Bearer ${token.value}` } })

    const response = await api()
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
    ElMessage.success('Word 导出成功')
    exportVisible.value = false
  } catch (err) {
    ElMessage.error('导出失败')
  } finally {
    exportLoading.value = false
  }
}
</script>

<style scoped>
.template-use-page { padding: 20px; background: #f5f7fa; min-height: 100vh; }
.template-layout { margin-top: 16px; }
.template-info-card { border-radius: 12px; }
.result-card { border-radius: 12px; min-height: 600px; }
.card-header { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.result-actions { margin-left: auto; }
.template-form { margin-top: 8px; }
.form-actions { margin-top: 20px; display: flex; gap: 12px; justify-content: center; }
.empty-result { display: flex; align-items: center; justify-content: center; min-height: 400px; }
.result-content { padding: 16px; line-height: 1.9; font-size: 15px; }
.md-body h1 { text-align: center; }
</style>
