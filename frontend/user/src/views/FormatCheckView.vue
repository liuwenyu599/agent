<template>
  <div class="format-check-page">
    <div class="page-header">
      <div class="header-left">
        <h2>格式校验</h2>
        <p class="subtitle">上传文件，按可配置的格式规则检查公文排版规范（独立功能，与 AI 写作无关）</p>
      </div>
      <div class="header-right" v-if="isAdmin">
        <el-button type="primary" plain @click="openRuleDialog()">
          <el-icon><Plus /></el-icon> 新增规则
        </el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab">
      <!-- ========== 校验 ========== -->
      <el-tab-pane label="文件校验" name="check">
        <el-row :gutter="20">
          <el-col :span="10">
            <el-card shadow="never">
              <template #header><span>上传待检查文件</span></template>

              <el-upload
                drag
                :auto-upload="false"
                :on-change="handleFileChange"
                :limit="1"
                accept=".docx,.txt,.md,.pdf"
                style="width: 100%"
              >
                <el-icon :size="48" color="#409EFF"><Upload /></el-icon>
                <div class="el-upload__text">拖拽文件到此处或 <em>点击选择</em></div>
                <template #tip>
                  <div class="el-upload__tip">
                    支持 .docx（完整校验字体/字号/行距/页边距等）；.txt/.md 仅内容层面检查；.pdf 建议转 Word 后校验
                  </div>
                </template>
              </el-upload>

              <div v-if="checkFile" class="file-selected">
                <el-icon><Document /></el-icon> {{ checkFile.name }}
              </div>

              <el-form label-position="top" style="margin-top: 16px">
                <el-form-item label="AI 辅助判断">
                  <el-switch v-model="useAi" active-text="启用" inactive-text="仅规则" />
                  <div class="form-hint">规则无法判断的复杂问题（如落款缺失、占位符残留）由 AI 辅助分析</div>
                </el-form-item>
                <el-form-item label="本次使用的规则">
                  <el-select v-model="selectedRuleIds" multiple placeholder="默认使用全部默认规则" style="width: 100%">
                    <el-option v-for="r in rules" :key="r.id" :label="`${r.name}（${targetText(r.target)}）`" :value="r.id" />
                  </el-select>
                </el-form-item>
              </el-form>

              <el-button type="primary" size="large" style="width: 100%" @click="runCheck" :loading="checking" :disabled="!checkFile">
                <el-icon><CircleCheck /></el-icon> 开始校验
              </el-button>
            </el-card>

            <!-- 校验历史 -->
            <el-card shadow="never" style="margin-top: 16px">
              <template #header><span>校验历史</span></template>
              <el-table :data="records" size="small" v-loading="recordsLoading" @row-click="loadRecord" highlight-current-row style="cursor:pointer">
                <el-table-column prop="filename" label="文件" min-width="140" show-overflow-tooltip />
                <el-table-column prop="issue_count" label="问题数" width="70" align="center" />
                <el-table-column label="时间" width="90">
                  <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
                </el-table-column>
              </el-table>
              <el-empty v-if="!records.length && !recordsLoading" description="暂无校验记录" :image-size="60" />
            </el-card>
          </el-col>

          <el-col :span="14">
            <el-card shadow="never" class="result-card" v-loading="checking">
              <template #header>
                <div class="result-header">
                  <span>校验结果</span>
                  <template v-if="result">
                    <el-tag type="danger" size="small" v-if="result.issue_count > 0">{{ result.issue_count }} 个问题</el-tag>
                    <el-tag type="success" size="small" v-else>未发现问题</el-tag>
                    <el-tag size="small" type="info" v-if="result.ai_used">含 AI 辅助判断</el-tag>
                  </template>
                </div>
              </template>

              <el-empty v-if="!result" description="上传文件后开始校验" :image-size="100" />

              <template v-else>
                <el-alert v-if="result.file_type !== 'docx'" type="warning" :closable="false" style="margin-bottom: 12px"
                  title="非 Word 文件只能进行有限的检查，建议上传 .docx 文件获得完整的字体/字号/行距等排版校验。" />
                <div v-for="(issue, idx) in result.issues" :key="idx" class="issue-item">
                  <div class="issue-head">
                    <el-tag :type="issue.severity === 'error' ? 'danger' : 'warning'" size="small">
                      {{ issue.severity === 'error' ? '错误' : '提醒' }}
                    </el-tag>
                    <el-tag size="small" effect="plain" :type="issue.source === 'rule' ? 'primary' : 'success'">
                      {{ issue.source === 'rule' ? '规则校验' : 'AI 判断' }}
                    </el-tag>
                    <span class="issue-location">{{ issue.location }}</span>
                    <span class="issue-element">{{ issue.element }}</span>
                  </div>
                  <div class="issue-body">
                    <div v-if="issue.current"><span class="lb">当前：</span>{{ issue.current }}</div>
                    <div v-if="issue.expected"><span class="lb">要求：</span>{{ issue.expected }}</div>
                    <div v-if="issue.suggestion"><span class="lb">建议：</span>{{ issue.suggestion }}</div>
                  </div>
                </div>
                <el-empty v-if="result.issues.length === 0" description="格式符合当前配置的规则" :image-size="80" />
              </template>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <!-- ========== 规则管理 ========== -->
      <el-tab-pane label="规则管理" name="rules">
        <el-alert type="info" :closable="false" style="margin-bottom: 16px"
          title="规则不写死在代码中。司法局正式格式规范确定后，在这里录入即可生效，无需修改代码。带「默认」标记的规则会在用户不选择规则时自动使用。" />
        <el-table :data="rules" stripe v-loading="rulesLoading">
          <el-table-column prop="name" label="规则名称" min-width="160" />
          <el-table-column label="作用对象" width="100">
            <template #default="{ row }">{{ targetText(row.target) }}</template>
          </el-table-column>
          <el-table-column label="检查项" min-width="280">
            <template #default="{ row }">
              <span class="checks-preview">{{ formatChecks(row.checks) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="级别" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="row.severity === 'error' ? 'danger' : 'warning'" size="small">{{ row.severity === 'error' ? '错误' : '提醒' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="默认" width="70" align="center">
            <template #default="{ row }"><el-tag v-if="row.is_default" size="small" type="success">默认</el-tag></template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right" v-if="isAdmin">
            <template #default="{ row }">
              <el-button link type="primary" @click="openRuleDialog(row)">编辑</el-button>
              <el-button link type="danger" @click="removeRule(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!rules.length && !rulesLoading" description="尚未配置格式规则，请联系管理员录入司法局正式规范" />
      </el-tab-pane>
    </el-tabs>

    <!-- ========== 规则编辑对话框 ========== -->
    <el-dialog v-model="ruleDialogVisible" :title="editingRule ? '编辑规则' : '新增规则'" width="640px" destroy-on-close>
      <el-form :model="ruleForm" label-width="100px">
        <el-form-item label="规则名称" required>
          <el-input v-model="ruleForm.name" placeholder="如：标题字体字号" />
        </el-form-item>
        <el-form-item label="作用对象" required>
          <el-select v-model="ruleForm.target" style="width: 100%" @change="ruleForm.checks = {}">
            <el-option v-for="t in targetOptions" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="检查项">
          <div class="check-fields">
            <template v-for="field in availableCheckFields" :key="field.key">
              <div class="check-field-row">
                <el-checkbox
                  :model-value="ruleForm.checks[field.key] !== undefined"
                  @change="toggleCheckField(field.key, $event)"
                >{{ field.label }}</el-checkbox>
                <template v-if="ruleForm.checks[field.key] !== undefined">
                  <el-select v-if="field.type === 'alignment'" v-model="ruleForm.checks[field.key]" style="width: 130px">
                    <el-option label="左对齐" value="left" /><el-option label="居中" value="center" />
                    <el-option label="右对齐" value="right" /><el-option label="两端对齐" value="justify" />
                  </el-select>
                  <el-select v-else-if="field.type === 'bool'" v-model="ruleForm.checks[field.key]" style="width: 110px">
                    <el-option label="是" :value="true" /><el-option label="否" :value="false" />
                  </el-select>
                  <el-input-number v-else-if="field.type === 'number'" v-model="ruleForm.checks[field.key]" :step="field.step || 1" :precision="field.precision ?? 0" style="width: 140px" />
                  <el-input v-else v-model="ruleForm.checks[field.key]" :placeholder="field.placeholder" style="width: 200px" />
                  <span class="unit">{{ field.unit }}</span>
                </template>
              </div>
            </template>
          </div>
          <div class="form-hint">只勾选需要检查的项目；未勾选的项不参与校验</div>
        </el-form-item>
        <el-form-item label="问题级别">
          <el-radio-group v-model="ruleForm.severity">
            <el-radio-button label="error">错误</el-radio-button>
            <el-radio-button label="warning">提醒</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="默认启用">
          <el-switch v-model="ruleForm.is_default" />
        </el-form-item>
        <el-form-item label="备注/依据">
          <el-input v-model="ruleForm.remark" type="textarea" :rows="2" placeholder="如：依据《××司法局公文处理规范》第X条（规范确定后填写）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ruleDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveRule" :loading="ruleSaving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, Document, Plus, CircleCheck } from '@element-plus/icons-vue'
import {
  checkFormat, listCheckRecords, getCheckRecord,
  listFormatRules, createFormatRule, updateFormatRule, deleteFormatRule
} from '@/api/format_check.js'

const activeTab = ref('check')
const isAdmin = computed(() => {
  try {
    const user = JSON.parse(localStorage.getItem('user') || '{}')
    return ['developer', 'knowledge_admin', 'admin'].includes(user.role)
  } catch { return false }
})

// ===== 校验 =====
const checkFile = ref(null)
const useAi = ref(true)
const selectedRuleIds = ref([])
const checking = ref(false)
const result = ref(null)
const records = ref([])
const recordsLoading = ref(false)

function handleFileChange(file) {
  checkFile.value = file.raw
}

async function runCheck() {
  if (!checkFile.value) return
  checking.value = true
  result.value = null
  try {
    const res = await checkFormat(checkFile.value, useAi.value, selectedRuleIds.value.length ? selectedRuleIds.value : null)
    result.value = res.data
    if (res.data.issue_count === 0) ElMessage.success('校验完成，未发现问题')
    else ElMessage.warning(`校验完成，发现 ${res.data.issue_count} 个问题`)
    loadRecords()
  } catch (e) {
    ElMessage.error('校验失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    checking.value = false
  }
}

async function loadRecords() {
  recordsLoading.value = true
  try {
    const res = await listCheckRecords({ page: 1, page_size: 20 })
    records.value = res.data.data || []
  } catch (e) { console.error(e) } finally { recordsLoading.value = false }
}

async function loadRecord(row) {
  try {
    const res = await getCheckRecord(row.id)
    result.value = { ...res.data, ai_used: res.data.issues?.some(i => i.source === 'ai') }
  } catch (e) { ElMessage.error('加载记录失败') }
}

// ===== 规则 =====
const rules = ref([])
const rulesLoading = ref(false)
const ruleDialogVisible = ref(false)
const ruleSaving = ref(false)
const editingRule = ref(null)
const ruleForm = ref({ name: '', target: 'title', checks: {}, severity: 'error', is_default: true, remark: '' })

const targetOptions = [
  { label: '标题', value: 'title' }, { label: '正文', value: 'body' },
  { label: '一级标题（一、）', value: 'heading1' }, { label: '二级标题（（一））', value: 'heading2' },
  { label: '页面设置', value: 'page' }, { label: '落款', value: 'signature' },
  { label: '成文日期', value: 'date' }, { label: '全文通用', value: 'general' }
]

// 各作用对象可配置的检查项
const CHECK_FIELDS = {
  paragraph: [
    { key: 'font_name', label: '字体', type: 'text', placeholder: '如：仿宋_GB2312' },
    { key: 'font_size_pt', label: '字号', type: 'number', step: 0.5, precision: 1, unit: '磅（二号=22，三号=16，小三=15，四号=14，小四=12）' },
    { key: 'bold', label: '加粗', type: 'bool' },
    { key: 'alignment', label: '对齐方式', type: 'alignment' },
    { key: 'line_spacing_pt', label: '行距', type: 'number', step: 1, unit: '磅（固定值）' },
    { key: 'first_line_indent_chars', label: '首行缩进', type: 'number', step: 1, unit: '字符' },
    { key: 'space_before_pt', label: '段前间距', type: 'number', step: 1, unit: '磅' },
    { key: 'space_after_pt', label: '段后间距', type: 'number', step: 1, unit: '磅' },
  ],
  page: [
    { key: 'top_margin_cm', label: '上边距', type: 'number', step: 0.1, precision: 1, unit: '厘米' },
    { key: 'bottom_margin_cm', label: '下边距', type: 'number', step: 0.1, precision: 1, unit: '厘米' },
    { key: 'left_margin_cm', label: '左边距', type: 'number', step: 0.1, precision: 1, unit: '厘米' },
    { key: 'right_margin_cm', label: '右边距', type: 'number', step: 0.1, precision: 1, unit: '厘米' },
    { key: 'page_width_cm', label: '页面宽度', type: 'number', step: 0.1, precision: 1, unit: '厘米（A4=21）' },
    { key: 'page_height_cm', label: '页面高度', type: 'number', step: 0.1, precision: 1, unit: '厘米（A4=29.7）' },
  ],
  general: [
    { key: 'no_extra_blank_lines', label: '不允许连续空行', type: 'bool' },
    { key: 'no_trailing_spaces', label: '不允许行尾空格', type: 'bool' },
  ]
}

const availableCheckFields = computed(() => {
  if (ruleForm.value.target === 'page') return CHECK_FIELDS.page
  if (ruleForm.value.target === 'general') return CHECK_FIELDS.general
  return CHECK_FIELDS.paragraph
})

function toggleCheckField(key, checked) {
  if (checked) {
    const field = availableCheckFields.value.find(f => f.key === key)
    ruleForm.value.checks[key] = field.type === 'bool' ? true : (field.type === 'number' ? 0 : '')
  } else {
    delete ruleForm.value.checks[key]
  }
}

async function loadRules() {
  rulesLoading.value = true
  try {
    const res = await listFormatRules()
    rules.value = res.data || []
  } catch (e) { console.error(e) } finally { rulesLoading.value = false }
}

function openRuleDialog(row) {
  if (!isAdmin.value) { ElMessage.warning('仅管理员可维护规则'); return }
  if (row) {
    editingRule.value = row
    ruleForm.value = {
      name: row.name, target: row.target, checks: { ...(row.checks || {}) },
      severity: row.severity, is_default: row.is_default, remark: row.remark || ''
    }
  } else {
    editingRule.value = null
    ruleForm.value = { name: '', target: 'title', checks: {}, severity: 'error', is_default: true, remark: '' }
  }
  ruleDialogVisible.value = true
}

async function saveRule() {
  if (!ruleForm.value.name.trim()) { ElMessage.warning('请填写规则名称'); return }
  if (!Object.keys(ruleForm.value.checks).length) { ElMessage.warning('请至少勾选一个检查项'); return }
  ruleSaving.value = true
  try {
    if (editingRule.value) {
      await updateFormatRule(editingRule.value.id, ruleForm.value)
      ElMessage.success('规则已更新')
    } else {
      await createFormatRule(ruleForm.value)
      ElMessage.success('规则已创建')
    }
    ruleDialogVisible.value = false
    loadRules()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally { ruleSaving.value = false }
}

async function removeRule(row) {
  try {
    await ElMessageBox.confirm(`确定删除规则「${row.name}」？`, '确认', { type: 'warning' })
    await deleteFormatRule(row.id)
    ElMessage.success('已删除')
    loadRules()
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

function targetText(t) {
  const m = { title: '标题', body: '正文', heading1: '一级标题', heading2: '二级标题', page: '页面', signature: '落款', date: '成文日期', general: '全文通用' }
  return m[t] || t
}

function formatChecks(checks) {
  if (!checks) return '-'
  const names = {
    font_name: '字体', font_size_pt: '字号(磅)', bold: '加粗', alignment: '对齐',
    line_spacing_pt: '行距(磅)', first_line_indent_chars: '首行缩进(字符)',
    space_before_pt: '段前(磅)', space_after_pt: '段后(磅)',
    top_margin_cm: '上边距(cm)', bottom_margin_cm: '下边距(cm)',
    left_margin_cm: '左边距(cm)', right_margin_cm: '右边距(cm)',
    page_width_cm: '页宽(cm)', page_height_cm: '页高(cm)',
    no_extra_blank_lines: '禁连续空行', no_trailing_spaces: '禁行尾空格'
  }
  return Object.entries(checks).map(([k, v]) => `${names[k] || k}=${v}`).join('，')
}

function formatTime(d) {
  if (!d) return ''
  const date = new Date(d)
  return (date.getMonth() + 1) + '-' + date.getDate() + ' ' +
    date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

onMounted(() => { loadRules(); loadRecords() })
</script>

<style scoped>
.format-check-page { padding: 24px; background: #f0f2f5; min-height: 100vh; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-header h2 { margin: 0; font-size: 22px; color: #303133; }
.subtitle { margin: 6px 0 0; font-size: 13px; color: #909399; }
.file-selected { margin-top: 10px; color: #67C23A; font-size: 13px; display: flex; align-items: center; gap: 6px; }
.form-hint { font-size: 12px; color: #909399; margin-top: 4px; }
.result-card { min-height: 500px; }
.result-header { display: flex; align-items: center; gap: 8px; }
.issue-item { border: 1px solid #ebeef5; border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; background: #fafbfc; }
.issue-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.issue-location { font-weight: 600; color: #303133; font-size: 14px; }
.issue-element { color: #909399; font-size: 13px; }
.issue-body { font-size: 13px; color: #606266; line-height: 1.8; }
.issue-body .lb { color: #909399; margin-right: 4px; }
.check-fields { width: 100%; }
.check-field-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.check-field-row .el-checkbox { width: 110px; }
.unit { font-size: 12px; color: #909399; }
.checks-preview { font-size: 12px; color: #606266; }
</style>
