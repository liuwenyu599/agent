<template>
  <div class="template-detail-page">
    <el-page-header @back="goBack" :title="templateInfo.name || '模板详情'" />

    <!-- 模板详情卡 -->
    <el-card shadow="never" class="detail-card" v-loading="loading">
      <div class="dt-head">
        <div class="dt-icon" :class="'ic-' + iconColor(templateInfo.category)">
          <el-icon :size="30"><component :is="templateInfo.icon || 'Document'" /></el-icon>
        </div>
        <div class="dt-head-info">
          <div class="dt-name">{{ templateInfo.name }}</div>
          <div class="dt-tags">
            <el-tag size="small" effect="plain" :type="isFormal ? 'primary' : 'success'">
              {{ isFormal ? '规范公文' : '写作参考' }}
            </el-tag>
            <el-tag size="small" effect="plain">{{ templateInfo.category }}</el-tag>
            <el-tag v-if="templateInfo.base_type" size="small" effect="plain" type="info">{{ templateInfo.base_type }}</el-tag>
            <el-tag v-if="templateInfo.is_builtin" size="small" type="warning" effect="light">官方</el-tag>
          </div>
        </div>
        <div class="dt-head-actions">
          <el-button v-if="isFormal" type="primary" size="large" @click="startFormal">
            <el-icon style="margin-right:6px"><EditPen /></el-icon>进入公文助手
          </el-button>
          <el-button v-else type="primary" size="large" @click="goChat">
            <el-icon style="margin-right:6px"><ChatDotRound /></el-icon>用于写作
          </el-button>
        </div>
      </div>

      <el-row :gutter="24" class="dt-body">
        <el-col :span="isFormal ? 14 : 24">
          <div class="dt-sec-title">适用场景</div>
          <p class="dt-desc">{{ templateInfo.description || '暂无描述' }}</p>

          <template v-if="templateInfo.writing_guidance">
            <div class="dt-sec-title">写作说明</div>
            <p class="dt-desc dt-guide">{{ templateInfo.writing_guidance }}</p>
          </template>

          <template v-if="structureItems.length">
            <div class="dt-sec-title">{{ isFormal ? '模板结构' : '示例结构' }}</div>
            <div class="dt-struct" v-for="(item, i) in structureItems" :key="i">
              <span class="dt-struct-no">{{ cnNums[i] }}</span>{{ item }}
            </div>
          </template>

          <template v-if="!isFormal">
            <div class="dt-sec-title">参考资源</div>
            <div class="dt-ref-box">
              <div class="dt-ref-item">参考材料：{{ templateInfo.reference_count || 0 }} 份</div>
              <div class="dt-ref-item" v-if="templateInfo.knowledge_bases && templateInfo.knowledge_bases.length">
                关联知识库：{{ templateInfo.knowledge_bases.join('、') }}
              </div>
              <div class="dt-ref-tip">此类材料不设固定结构，写作时将结合历史材料与知识库内容作为参考，生成风格一致的文稿。</div>
            </div>
          </template>
        </el-col>

        <el-col v-if="isFormal" :span="10">
          <div class="dt-sec-title">格式要求</div>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="写作风格">{{ templateInfo.writing_style || '正式公文' }}</el-descriptions-item>
            <el-descriptions-item label="字数要求">约 {{ templateInfo.word_count || 1000 }} 字</el-descriptions-item>
            <el-descriptions-item label="格式要素">
              <el-tag v-if="templateInfo.need_red_header" size="small" style="margin-right:4px">红头</el-tag>
              <el-tag v-if="templateInfo.need_doc_number" size="small" style="margin-right:4px">文号</el-tag>
              <el-tag v-if="templateInfo.need_signature" size="small" style="margin-right:4px">落款</el-tag>
              <el-tag v-if="templateInfo.need_date" size="small">日期</el-tag>
            </el-descriptions-item>
          </el-descriptions>
        </el-col>
      </el-row>
    </el-card>

    <!-- 公文助手：要素填写 + 生成（仅规范公文） -->
    <template v-if="isFormal && formalStarted">
      <el-row :gutter="20" class="template-layout">
        <el-col :span="10">
          <el-card shadow="never" class="template-info-card">
            <template #header>
              <div class="card-header"><span>填写公文要素</span></div>
            </template>
            <el-form :model="formData" label-position="top" class="template-form">
              <el-form-item
                v-for="field in templateInfo.params_schema"
                :key="field.name"
                :label="field.label + (field.required ? ' *' : '')"
              >
                <el-input v-if="field.type === 'input'" v-model="formData[field.name]" :placeholder="field.placeholder" />
                <el-input v-else-if="field.type === 'textarea'" v-model="formData[field.name]" type="textarea" :rows="field.rows || 3" :placeholder="field.placeholder" />
                <el-select v-else-if="field.type === 'select'" v-model="formData[field.name]" style="width:100%">
                  <el-option v-for="opt in field.options" :key="opt.value" :label="opt.label" :value="opt.value" />
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
        <el-col :span="14">
          <el-card shadow="never" class="result-card" v-loading="generating">
            <template #header>
              <div class="card-header">
                <span>生成结果</span>
                <div v-if="result" class="result-actions">
                  <el-button size="small" text @click="copyResult"><el-icon><CopyDocument /></el-icon> 复制</el-button>
                  <el-button size="small" text @click="openExportDialog"><el-icon><Document /></el-icon> 导出 Word</el-button>
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
    </template>

    <!-- Word 导出对话框 -->
    <el-dialog v-model="exportVisible" title="导出为 Word" width="550px">
      <el-form :model="exportForm" label-width="100px">
        <el-form-item label="文档标题"><el-input v-model="exportForm.title" /></el-form-item>
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
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { EditPen, CopyDocument, Document, ChatDotRound } from '@element-plus/icons-vue'
import axios from 'axios'

const route = useRoute(), router = useRouter()
const templateId = route.params.id

const loading = ref(false)
const generating = ref(false)
const templateInfo = ref({})
const formData = ref({})
const result = ref('')
const formalStarted = ref(false)

const exportVisible = ref(false)
const exportLoading = ref(false)
const exportForm = ref({ title: '', format: 'normal', doc_number: '', recipient: '', signature: '', date_text: '' })

const token = ref(localStorage.getItem('token') || '')
const cnNums = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']

const isFormal = computed(() => templateInfo.value.wtype === 'formal')

const structureItems = computed(() => {
  const t = templateInfo.value
  const ct = t.content_template || ''
  const m = ct.match(/包含[：:](.+?)。/)
  if (m) return m[1].split(/[、，,；;]/).map(x => x.trim()).filter(Boolean)
  return (t.params_schema || []).map(f => f.label)
})

function iconColor(cat) {
  return { '法定公文': 'blue', '工作材料': 'green', '宣传材料': 'orange' }[cat] || 'purple'
}

onMounted(() => { loadTemplate() })

async function loadTemplate() {
  loading.value = true
  try {
    if (!templateId || templateId === 'undefined') {
      ElMessage.error('模板ID无效')
      router.push('/templates')
      return
    }
    const res = await axios.get(`/api/v1/templates/${templateId}`, {
      headers: { Authorization: `Bearer ${token.value}` }
    })
    templateInfo.value = res.data || {}
    const init = {}
    for (const f of templateInfo.value.params_schema || []) init[f.name] = ''
    formData.value = init
    // 规范公文默认直接进入填写区
    if (isFormal.value) formalStarted.value = true
  } catch (e) {
    ElMessage.error('加载模板失败')
  } finally {
    loading.value = false
  }
}

function goBack() { router.push('/templates') }
function startFormal() { formalStarted.value = true }

// 写作参考类：跳转智能写作并携带模板信息
function goChat() {
  router.push({ path: '/chat', query: { template_id: templateId, template_name: templateInfo.value.name || '' } })
}

function resetForm() {
  const init = {}
  for (const f of templateInfo.value.params_schema || []) init[f.name] = ''
  formData.value = init
  result.value = ''
}

async function generate() {
  for (const f of templateInfo.value.params_schema || []) {
    if (f.required && !formData.value[f.name]?.trim()) {
      ElMessage.warning(`请填写「${f.label}」`)
      return
    }
  }
  generating.value = true
  try {
    const elements = []
    for (const f of templateInfo.value.params_schema || []) {
      const val = formData.value[f.name]
      if (val && val.trim()) elements.push(`${f.label}：${val.trim()}`)
    }
    const t = templateInfo.value
    let systemPrompt = t.system_prompt || '你是一位资深的司法行政公文写作专家。'
    systemPrompt += `\n\n写作要求：\n1. 写作风格：${t.writing_style || '正式公文'}；`
    systemPrompt += `\n2. 字数要求：约 ${t.word_count || 1000} 字；`
    if (t.need_red_header) systemPrompt += '\n3. 需要包含红头（发文机关标识）；'
    if (t.need_signature) systemPrompt += '\n4. 需要包含落款（发文机关署名）；'
    if (t.need_date) systemPrompt += '\n5. 需要包含成文日期；'
    if (t.need_doc_number) systemPrompt += '\n6. 需要包含发文字号；'
    systemPrompt += '\n\n请根据以下要素生成完整的公文正文，不要简单填空，要根据要素展开成流畅、规范的公文。'
    systemPrompt += '\n\n【格式要求】\n1. 不要输出 Markdown 标记（如 **、## 等），不要输出 HTML 标签；\n2. 纯文本输出，段落之间用空行分隔；\n3. 一级标题（如"一、评查范围"）独占一行，前后空一行；\n4. 落款信息（联系人、电话、单位、日期、文号）每项独占一行；\n5. 不要输出解释性文字，直接给公文正文。'

    let userMessage = '请根据以下要素生成公文：\n\n' + elements.join('\n')
    if (t.content_template) userMessage += `\n\n【结构参考】\n${t.content_template}`

    const res = await axios.post('/api/v1/chat/send', {
      message: userMessage,
      system_prompt: systemPrompt,
      use_rag: true,
      source: 'template'
    }, { headers: { Authorization: `Bearer ${token.value}` }, timeout: 180000 })

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
  const cleaned = text
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/^#+\s*/gm, '')
    .replace(/<[^>]+>/g, '')
  return '<div style="white-space:pre-wrap;line-height:1.9;font-size:15px;text-align:justify;">' + cleaned + '</div>'
}

async function copyResult() {
  await navigator.clipboard.writeText(result.value)
  ElMessage.success('已复制')
}

function openExportDialog() {
  const titleMatch = result.value.match(/^#\s+(.+)$/m)
  const today = new Date()
  const dateStr = today.getFullYear() + '年' + (today.getMonth() + 1) + '月' + today.getDate() + '日'
  exportForm.value = {
    title: titleMatch ? titleMatch[1].trim() : (templateInfo.value.name || '公文'),
    format: 'normal', doc_number: '', recipient: '', signature: '', date_text: dateStr
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
    const blob = new Blob([response.data], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })
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
.template-detail-page { padding: 20px; background: #f5f7fa; min-height: 100vh; }
.detail-card { margin-top: 16px; border-radius: 12px; }
.dt-head { display: flex; align-items: center; gap: 16px; }
.dt-icon { width: 56px; height: 56px; border-radius: 12px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.dt-icon.ic-blue { background: #e8f0fe; color: #1d5fd1; }
.dt-icon.ic-green { background: #e6f6ec; color: #1a7f37; }
.dt-icon.ic-orange { background: #fdf2e3; color: #b26a00; }
.dt-icon.ic-purple { background: #f3ecfd; color: #6d28a8; }
.dt-head-info { flex: 1; }
.dt-name { font-size: 20px; font-weight: 700; color: #1f2d3d; }
.dt-tags { margin-top: 6px; display: flex; gap: 6px; }
.dt-head-actions { flex-shrink: 0; }
.dt-body { margin-top: 18px; }
.dt-sec-title { font-size: 14px; font-weight: 600; color: #1f2d3d; margin: 16px 0 8px; padding-left: 10px; border-left: 3px solid #409eff; }
.dt-desc { font-size: 14px; color: #5c6b7a; line-height: 1.8; margin: 0; }
.dt-guide { background: #f6f9fc; border-radius: 8px; padding: 10px 14px; }
.dt-struct { font-size: 14px; color: #303133; line-height: 2; }
.dt-struct-no { display: inline-block; min-width: 26px; height: 22px; line-height: 22px; text-align: center; background: #e8f0fe; color: #1d5fd1; border-radius: 6px; font-size: 12px; margin-right: 8px; }
.dt-ref-box { background: #f6f9fc; border: 1px solid #e4ecf5; border-radius: 8px; padding: 12px 16px; }
.dt-ref-item { font-size: 13px; color: #303133; line-height: 1.9; }
.dt-ref-tip { font-size: 12px; color: #909399; margin-top: 6px; }
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