
<template>
  <el-dialog
    v-model="visible"
    :title="editingId ? '修改模板' : '新建模板'"
    width="1100px"
    top="4vh"
    destroy-on-close
    class="tpl-create-dialog"
  >
    <div class="dlg-grid">
      <!-- ① 基础信息 -->
      <section class="sec">
        <div class="sec-title"><span class="sec-no">1</span> 基础信息</div>
        <div class="row-2">
          <div class="fld">
            <label>模板名称 <i class="req">*</i></label>
            <el-input v-model="form.name" maxlength="50" show-word-limit placeholder="请输入模板名称" />
          </div>
          <div class="fld">
            <label>所属分类 <i class="req">*</i></label>
            <el-select v-model="form.category" placeholder="请选择分类" style="width:100%">
              <el-option v-for="c in categories" :key="c.code" :label="c.name" :value="c.name" />
            </el-select>
          </div>
        </div>
        <div class="fld">
          <label>模板类型</label>
          <el-radio-group v-model="form.template_kind">
            <el-radio label="official_doc">
              公文模板（有固定结构）
              <div class="radio-sub">适用于请示、报告、通知等正式公文</div>
            </el-radio>
            <el-radio label="writing_ref">
              写作参考模板（无固定结构）
              <div class="radio-sub">适用于外宣、新闻稿、简报等材料</div>
            </el-radio>
          </el-radio-group>
        </div>
        <div class="fld">
          <label>模板标签</label>
          <el-input
            v-model="tagInput"
            placeholder="请输入标签，按回车键添加"
            @keyup.enter="addTag"
            :disabled="form.tags.length >= 10"
          >
            <template #suffix>{{ form.tags.length }}/10</template>
          </el-input>
          <div class="tag-list">
            <el-tag v-for="(tg, i) in form.tags" :key="tg" closable @close="form.tags.splice(i, 1)">{{ tg }}</el-tag>
          </div>
          <div class="hint">可添加多个标签，便于搜索和管理</div>
        </div>
        <div class="fld">
          <label>适用场景</label>
          <el-input v-model="form.scene" type="textarea" :rows="3" maxlength="300" show-word-limit
                    placeholder="请描述该模板适用的具体场景和用途" />
        </div>
      </section>

      <!-- ② 模板说明与写作指引 -->
      <section class="sec">
        <div class="sec-title"><span class="sec-no">2</span> 模板说明与写作指引</div>
        <div class="fld">
          <label>模板说明</label>
          <el-input v-model="form.description" type="textarea" :rows="4" maxlength="500" show-word-limit
                    placeholder="简要说明该模板的作用、特点及使用建议" />
        </div>
        <div class="fld">
          <label>写作要点与注意事项</label>
          <el-input v-model="form.writing_guide" type="textarea" :rows="9" maxlength="2000" show-word-limit
                    placeholder="请写使用该模板时需要注意的要点、写作风格、语言要求等（AI 写作时会遵循）" />
        </div>
      </section>

      <!-- ③ 结构设置（仅公文模板） -->
      <section class="sec" v-if="form.template_kind === 'official_doc'">
        <div class="sec-title"><span class="sec-no">3</span> 结构设置（仅公文模板需要）</div>
        <div class="fld structure-head">
          <label>启用结构</label>
          <el-switch v-model="structureEnabled" />
          <span class="hint">开启后将在使用该模板时提供结构指引</span>
        </div>
        <template v-if="structureEnabled">
          <div v-for="(item, idx) in form.structure" :key="idx" class="structure-item">
            <el-icon class="drag"><Rank /></el-icon>
            <span class="idx">{{ idx + 1 }}</span>
            <el-input v-model="item.name" placeholder="结构项名称，如：请示理由" style="width:200px" />
            <el-input v-model="item.guide" placeholder="请填写该部分的写作要求（选填）" style="flex:1" />
            <el-button link type="danger" @click="form.structure.splice(idx, 1)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
          <el-button link type="primary" @click="form.structure.push({ name: '', guide: '' })">
            <el-icon><Plus /></el-icon> 添加结构项
          </el-button>
        </template>
      </section>

      <!-- ④ 关联参考材料（可选） -->
      <section class="sec">
        <div class="sec-title"><span class="sec-no">4</span> 关联参考材料（可选）</div>
        <div class="hint" style="margin-bottom:10px">
          添加该模板的参考材料，帮助 AI 更好地学习写作风格与结构（只学风格，不会照搬其中事实）
        </div>
        <el-tabs v-model="refTab">
          <el-tab-pane label="上传文档" name="file">
            <el-upload
              drag multiple :show-file-list="false" :auto-upload="false"
              :on-change="onRefFileChange"
              accept=".pdf,.doc,.docx,.txt,.md"
            >
              <el-icon class="upload-ic"><UploadFilled /></el-icon>
              <div class="el-upload__text">点击或拖拽文件到此处上传</div>
              <div class="el-upload__tip">支持 PDF、DOCX、TXT、MD 等格式，单个文件不超过 50MB</div>
            </el-upload>
          </el-tab-pane>
          <el-tab-pane label="粘贴文本" name="text">
            <el-input v-model="refText" type="textarea" :rows="6"
                      placeholder="粘贴参考文本（如历史优秀稿件）" />
            <el-button type="primary" plain size="small" style="margin-top:8px"
                       :disabled="!refText.trim()" @click="addTextRef">添加文本</el-button>
          </el-tab-pane>
          <el-tab-pane label="添加网页链接" name="url">
            <el-input v-model="refUrl" placeholder="https://mp.weixin.qq.com/s/……" />
            <el-button type="primary" plain size="small" style="margin-top:8px"
                       :disabled="!refUrl.trim()" :loading="refUrlLoading" @click="addUrlRef">抓取并添加</el-button>
          </el-tab-pane>
        </el-tabs>
        <div class="ref-list-title">已上传的参考材料（{{ refList.length }}）</div>
        <div v-if="!refList.length" class="ref-empty">
          <el-icon><Document /></el-icon>
          <div>暂无参考材料</div>
          <div class="hint">可上传历史优秀案例、范文、相关文件等作为参考</div>
        </div>
        <div v-for="r in refList" :key="r.id || r._key" class="ref-item">
          <el-icon><Document /></el-icon>
          <span class="ref-name">{{ r.name }}</span>
          <span class="hint">{{ refTypeLabel(r.ref_type) }}<template v-if="r.char_count"> · {{ r.char_count }} 字</template></span>
          <el-button link type="danger" @click="removeRef(r)">删除</el-button>
        </div>
      </section>

      <!-- ⑤ 关联知识库（可选） -->
      <section class="sec">
        <div class="sec-title"><span class="sec-no">5</span> 关联知识库（可选）</div>
        <div class="hint" style="margin-bottom:8px">选择该模板常用的知识库，写作时将优先检索</div>
        <el-select v-model="form.kb_ids" multiple placeholder="请选择知识库" style="width:100%">
          <el-option v-for="kb in kbList" :key="kb.id" :label="kb.name" :value="kb.id" />
        </el-select>
      </section>

      <!-- ⑥ 模板权限与共享 -->
      <section class="sec">
        <div class="sec-title"><span class="sec-no">6</span> 模板权限与共享</div>
        <div class="fld">
          <label>模板类型</label>
          <el-radio-group v-model="form.visibility">
            <el-radio label="official" :disabled="!isAdmin">官方模板（全体可用）</el-radio>
            <el-radio label="personal">个人模板（仅自己可用）</el-radio>
          </el-radio-group>
        </div>
        <div class="fld" v-if="form.visibility === 'official'">
          <label>共享范围</label>
          <el-checkbox-group v-model="shareChecks">
            <el-checkbox label="all">全平台共享</el-checkbox>
            <el-checkbox label="department">指定部门可用</el-checkbox>
            <el-checkbox label="role">指定角色可用</el-checkbox>
          </el-checkbox-group>
          <template v-if="shareChecks.includes('department')">
            <el-select v-model="form.share_departments" multiple placeholder="选择可用部门"
                       style="width:100%;margin-top:8px">
              <el-option v-for="d in departmentOptions" :key="d" :label="d" :value="d" />
            </el-select>
          </template>
          <template v-if="shareChecks.includes('role')">
            <el-select v-model="form.share_roles" multiple placeholder="选择可用角色"
                       style="width:100%;margin-top:8px">
              <el-option label="普通用户" value="user" />
              <el-option label="知识管理员" value="knowledge_admin" />
              <el-option label="系统管理员" value="developer" />
            </el-select>
          </template>
        </div>
      </section>

      <!-- ⑦ 封面与图标（可选） -->
      <section class="sec">
        <div class="sec-title"><span class="sec-no">7</span> 封面与图标（可选）</div>
        <div class="fld">
          <label>模板图标</label>
          <div class="icon-picker">
            <div
              v-for="ic in iconOptions" :key="ic"
              class="icon-opt" :class="{ active: form.icon === ic }"
              @click="form.icon = ic"
            >
              <el-icon><component :is="iconComponent(ic)" /></el-icon>
            </div>
          </div>
        </div>
      </section>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button @click="submit(true)" :loading="saving">保存草稿</el-button>
      <el-button type="primary" @click="submit(false)" :loading="saving">
        {{ editingId ? '保存修改' : '创建模板' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Delete, Rank, Document, UploadFilled } from '@element-plus/icons-vue'
import * as Icons from '@element-plus/icons-vue'
import axios from 'axios'

const emit = defineEmits(['saved'])
const token = localStorage.getItem('token') || ''
const headers = { Authorization: `Bearer ${token}` }

const isAdmin = computed(() => {
  try {
    const u = JSON.parse(localStorage.getItem('user') || '{}')
    return ['developer', 'knowledge_admin', 'admin'].includes(u.role)
  } catch { return false }
})

const visible = ref(false)
const saving = ref(false)
const editingId = ref(null)
const categories = ref([])
const kbList = ref([])

const blankForm = () => ({
  name: '', category: '', template_kind: 'official_doc',
  tags: [], scene: '', description: '', writing_guide: '',
  structure: [], kb_ids: [],
  visibility: isAdmin.value ? 'official' : 'personal',
  share_scope: 'all', share_departments: [], share_roles: [],
  icon: 'Document',
  // 公文模板默认保留的格式字段（不暴露在设计上，沿用后端默认）
  base_type: '公文', params_schema: [], content_template: '', system_prompt: '',
  writing_style: '正式公文', word_count: 1000,
  need_red_header: false, need_signature: true, need_date: true, need_doc_number: false,
  keywords: ''
})
const form = ref(blankForm())
const tagInput = ref('')
const structureEnabled = ref(false)
const shareChecks = ref(['all'])

// ---- 参考材料 ----
const refTab = ref('file')
const refList = ref([])          // 已保存的（编辑模式）+ 待上传的（新建模式，带 _file/_text/_url）
const refText = ref('')
const refUrl = ref('')
const refUrlLoading = ref(false)

const departmentOptions = ['办公室', '普法与依法治理科', '社区矫正科', '公共法律服务管理科', '行政复议应诉科', '政治处']
const iconOptions = ['Document', 'DocumentChecked', 'EditPen', 'Bell', 'Notebook', 'Promotion',
                     'Postcard', 'Flag', 'Star', 'Collection', 'Microphone', 'Calendar', 'Tickets', 'List']
const iconComponent = (name) => Icons[name] || Icons.Document

function refTypeLabel(t) {
  return { file: '文档', text: '文本', url: '网页' }[t] || t
}

function addTag() {
  const v = tagInput.value.trim()
  if (!v) return
  if (form.value.tags.includes(v)) return ElMessage.warning('标签已存在')
  if (form.value.tags.length >= 10) return
  form.value.tags.push(v)
  tagInput.value = ''
}

// 参考材料：新建模式先挂起，编辑模式直接调接口
function onRefFileChange(uploadFile) {
  const f = uploadFile.raw
  if (!f) return
  if (f.size > 50 * 1024 * 1024) return ElMessage.error('文件超过 50MB 限制')
  if (editingId.value) {
    const fd = new FormData()
    fd.append('file', f)
    axios.post(`/api/v1/references/template/${editingId.value}/upload`, fd, { headers })
      .then(res => { refList.value.push(res.data.reference); ElMessage.success('已添加') })
      .catch(e => ElMessage.error(e.response?.data?.detail || '上传失败'))
  } else {
    refList.value.push({ _key: `f${Date.now()}${Math.random()}`, _file: f, name: f.name, ref_type: 'file', char_count: 0, _pending: true })
  }
}

async function addTextRef() {
  const text = refText.value.trim()
  if (!text) return
  if (editingId.value) {
    try {
      const res = await axios.post(`/api/v1/references/template/${editingId.value}/text`,
        { name: '粘贴的参考文本', text }, { headers })
      refList.value.push(res.data.reference)
      refText.value = ''
    } catch (e) { ElMessage.error(e.response?.data?.detail || '添加失败') }
  } else {
    refList.value.push({ _key: `t${Date.now()}`, _text: text, name: '粘贴的参考文本', ref_type: 'text', char_count: text.length, _pending: true })
    refText.value = ''
  }
}

async function addUrlRef() {
  const url = refUrl.value.trim()
  if (!/^https?:\/\//.test(url)) return ElMessage.warning('请输入合法的 http(s) 链接')
  if (editingId.value) {
    refUrlLoading.value = true
    try {
      const res = await axios.post(`/api/v1/references/template/${editingId.value}/url`, { url }, { headers })
      refList.value.push(res.data.reference)
      refUrl.value = ''
      ElMessage.success('已抓取并添加')
    } catch (e) { ElMessage.error(e.response?.data?.detail || '网页获取失败') }
    finally { refUrlLoading.value = false }
  } else {
    // 新建模式：链接先记录，创建模板后由后端抓取
    refList.value.push({ _key: `u${Date.now()}`, _url: url, name: url, ref_type: 'url', char_count: 0, _pending: true })
    refUrl.value = ''
  }
}

async function removeRef(r) {
  if (r.id && !r._pending) {
    try {
      await axios.delete(`/api/v1/references/template/refs/${r.id}`, { headers })
    } catch (e) { ElMessage.error('删除失败'); return }
  }
  refList.value = refList.value.filter(x => (x.id || x._key) !== (r.id || r._key))
}

// 创建成功后，把挂起的参考材料逐个上传
async function flushPendingRefs(templateId) {
  for (const r of refList.value.filter(x => x._pending)) {
    try {
      if (r._file) {
        const fd = new FormData(); fd.append('file', r._file)
        await axios.post(`/api/v1/references/template/${templateId}/upload`, fd, { headers })
      } else if (r._text) {
        await axios.post(`/api/v1/references/template/${templateId}/text`, { name: r.name, text: r._text }, { headers })
      } else if (r._url) {
        await axios.post(`/api/v1/references/template/${templateId}/url`, { url: r._url }, { headers })
      }
    } catch (e) {
      ElMessage.warning(`参考材料「${r.name}」添加失败：${e.response?.data?.detail || e.message}`)
    }
  }
}

async function loadRefs(templateId) {
  try {
    const res = await axios.get(`/api/v1/references/template/${templateId}`, { headers })
    refList.value = res.data.references || []
  } catch { refList.value = [] }
}

async function submit(isDraft) {
  if (!form.value.name.trim()) return ElMessage.warning('请输入模板名称')
  if (!form.value.category) return ElMessage.warning('请选择分类')

  // 共享范围换算：勾了全平台 → all；只勾部门/角色 → 对应；都没勾 → all
  let scope = 'all'
  if (!shareChecks.value.includes('all')) {
    if (shareChecks.value.includes('department')) scope = 'department'
    else if (shareChecks.value.includes('role')) scope = 'role'
  }

  const payload = {
    ...form.value,
    structure: (form.value.template_kind === 'official_doc' && structureEnabled.value)
      ? form.value.structure.filter(s => s.name.trim()) : [],
    share_scope: scope,
    is_draft: isDraft,
    // 公文模板：根据结构自动生成 content_template；写作参考模板：无固定结构
    content_template: form.value.template_kind === 'official_doc' && structureEnabled.value && form.value.structure.length
      ? `本文结构包含：${form.value.structure.filter(s => s.name.trim()).map((s, i) => `${s.name}${s.guide ? '（' + s.guide + '）' : ''}`).join('、')}。`
      : form.value.content_template
  }

  saving.value = true
  try {
    if (editingId.value) {
      await axios.put(`/api/v1/templates/${editingId.value}`, payload, { headers })
      ElMessage.success(isDraft ? '草稿已保存' : '模板已更新')
    } else {
      const res = await axios.post('/api/v1/templates/', payload, { headers })
      await flushPendingRefs(res.data.id)
      ElMessage.success(isDraft ? '草稿已保存' : '模板创建成功')
    }
    visible.value = false
    emit('saved')
  } catch (e) {
    ElMessage.error((editingId.value ? '保存失败：' : '创建失败：') + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

async function open(template = null) {
  const [catRes, kbRes] = await Promise.all([
    axios.get('/api/v1/templates/categories', { headers }),
    axios.get('/api/v1/knowledge/list', { headers }).catch(() => ({ data: [] }))
  ])
  categories.value = catRes.data || []
  kbList.value = kbRes.data || []

  editingId.value = template?.id || null
  if (template) {
    form.value = { ...blankForm(), ...template, tags: template.tags || [], structure: template.structure || [], kb_ids: template.kb_ids || [] }
    structureEnabled.value = (template.structure || []).length > 0
    const sc = template.share_scope || 'all'
    shareChecks.value = sc === 'all' ? ['all'] : [sc]
    await loadRefs(template.id)
  } else {
    form.value = blankForm()
    form.value.category = categories.value[0]?.name || ''
    structureEnabled.value = false
    shareChecks.value = ['all']
    refList.value = []
  }
  refText.value = ''
  refUrl.value = ''
  visible.value = true
}

defineExpose({ open })
</script>

<style scoped>
.dlg-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px 28px;
  max-height: 66vh;
  overflow-y: auto;
  padding-right: 6px;
}
.sec { min-width: 0; }
.sec-title { font-weight: 600; font-size: 14px; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
.sec-no {
  display: inline-flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; border-radius: 50%;
  background: #2f6bff; color: #fff; font-size: 12px;
}
.fld { margin-bottom: 14px; }
.fld > label { display: block; font-size: 13px; color: #303133; margin-bottom: 6px; }
.req { color: #f56c6c; font-style: normal; }
.hint { font-size: 12px; color: #909399; margin-top: 4px; }
.radio-sub { font-size: 12px; color: #909399; font-weight: normal; }
.tag-list { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 6px; }
.structure-head { display: flex; align-items: center; gap: 10px; }
.structure-head .hint { margin-top: 0; }
.structure-item { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.structure-item .idx { width: 22px; text-align: center; color: #909399; }
.structure-item .drag { color: #c0c4cc; cursor: move; }
.upload-ic { font-size: 34px; color: #c0c4cc; margin-bottom: 6px; }
.ref-list-title { font-size: 13px; margin: 12px 0 8px; color: #303133; }
.ref-empty { text-align: center; color: #909399; padding: 18px 0; font-size: 13px; }
.ref-item { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid #ebeef5; border-radius: 6px; margin-bottom: 6px; }
.ref-item .ref-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ref-item .hint { margin-top: 0; }
.icon-picker { display: flex; flex-wrap: wrap; gap: 8px; }
.icon-opt {
  width: 40px; height: 40px; border: 1px solid #dcdfe6; border-radius: 8px;
  display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 18px;
}
.icon-opt.active { border-color: #2f6bff; color: #2f6bff; background: #eef3ff; }
@media (max-width: 900px) {
  .dlg-grid { grid-template-columns: 1fr; }
}
</style>
