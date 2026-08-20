<template>
  <div class="ppt-home">
    <!-- ===== 顶部 ===== -->
    <div class="page-head">
      <el-radio-group v-model="pageTab" size="large">
        <el-radio-button value="create">创建 PPT</el-radio-button>
        <el-radio-button value="mine">我的 PPT</el-radio-button>
      </el-radio-group>
      <el-button @click="materialVisible = true">
        <el-icon><Picture /></el-icon>素材库（{{ materials.length }}）
      </el-button>
    </div>

    <!-- ================= 创建 PPT ================= -->
    <template v-if="pageTab === 'create'">
      <!-- 创建方式 -->
      <div class="panel">
        <div class="panel-title">创建方式</div>
        <div class="method-grid">
          <div v-for="m in methods" :key="m.key" class="method-card"
               :class="{ active: method === m.key }" @click="method = m.key">
            <div class="mc-icon" :style="{ background: m.bg, color: m.color }">
              <el-icon :size="24"><component :is="m.icon" /></el-icon>
            </div>
            <div>
              <div class="mc-name">{{ m.name }}</div>
              <div class="mc-desc">{{ m.desc }}</div>
            </div>
            <el-icon v-if="method === m.key" class="mc-check"><CircleCheckFilled /></el-icon>
          </div>
        </div>
      </div>

      <div class="two-col">
        <!-- 左列 -->
        <div class="col-left">
          <div class="panel">
            <div class="panel-title">1. 输入主题与目标</div>
            <el-input v-model="form.topic" type="textarea" :rows="5" maxlength="500" show-word-limit
                      placeholder="帮我制作一份2026年上半年司法行政工作总结汇报PPT，面向局领导汇报，包含工作完成情况、成效、问题和下一步工作安排，控制在15页左右。" />
            <div class="form-row">
              <div class="form-item">
                <label>汇报对象</label>
                <el-select v-model="form.audience" placeholder="请选择">
                  <el-option v-for="o in audiences" :key="o" :label="o" :value="o" />
                </el-select>
              </div>
              <div class="form-item">
                <label>场景用途</label>
                <el-select v-model="form.scene" placeholder="请选择">
                  <el-option v-for="o in scenes" :key="o" :label="o" :value="o" />
                </el-select>
              </div>
              <div class="form-item">
                <label>预计页数</label>
                <el-select v-model="form.slideCount">
                  <el-option v-for="o in pageCounts" :key="o.label" :label="o.label" :value="o.value" />
                </el-select>
              </div>
            </div>
          </div>

          <div class="panel" v-if="method !== 'ai'">
            <div class="panel-title">2. 参考材料<span class="muted">（可多选）</span></div>
            <div class="ref-btns">
              <el-button size="small" :type="refMode === 'doc' ? 'primary' : 'default'" plain
                         @click="refMode = 'doc'">上传文档</el-button>
              <el-button size="small" :type="refMode === 'kb' ? 'primary' : 'default'" plain
                         @click="refMode = 'kb'">选择知识库</el-button>
              <el-button size="small" :type="refMode === 'paste' ? 'primary' : 'default'" plain
                         @click="refMode = 'paste'">粘贴文本</el-button>
            </div>

            <template v-if="refMode === 'doc'">
              <div v-for="(f, i) in files" :key="i" class="file-row">
                <span class="file-icon" :class="fileClass(f.name)">{{ fileExt(f.name) }}</span>
                <span class="file-name">{{ f.name }}</span>
                <span class="file-size">{{ formatSize(f.size) }}</span>
                <el-icon class="file-ok"><CircleCheckFilled /></el-icon>
                <el-icon class="file-del" @click="files.splice(i, 1)"><Close /></el-icon>
              </div>
              <el-upload drag :show-file-list="false" :auto-upload="false" :on-change="onFilePicked" multiple>
                <div class="drag-inner">
                  <el-icon :size="28" color="#4a7ff7"><Upload /></el-icon>
                  <p>点击或拖拽文件到此处上传</p>
                  <p class="muted">支持 Word、PDF、Excel、TXT 等格式，单个文件不超过50MB</p>
                </div>
              </el-upload>
            </template>

            <template v-else-if="refMode === 'kb'">
              <div class="kb-tags">
                <el-tag v-for="kb in selectedKbs" :key="kb.id" closable @close="removeKb(kb)">
                  {{ kb.name }}
                </el-tag>
                <el-button size="small" plain @click="kbDialogVisible = true">
                  <el-icon><Plus /></el-icon>选择知识库
                </el-button>
              </div>
            </template>

            <template v-else>
              <el-input v-model="form.content" type="textarea" :rows="8"
                        placeholder="把文字材料粘贴到这里，AI 将据此提炼大纲" />
            </template>
          </div>

          <div class="panel" v-if="method === 'ai'">
            <div class="panel-title">使用的知识库<span class="muted">（可选）</span></div>
            <div class="kb-tags">
              <el-tag v-for="kb in selectedKbs" :key="kb.id" closable @close="removeKb(kb)">
                {{ kb.name }}
              </el-tag>
              <el-button size="small" plain @click="kbDialogVisible = true">
                <el-icon><Plus /></el-icon>选择知识库
              </el-button>
            </div>
          </div>
        </div>

        <!-- 右列：选择模板 -->
        <div class="panel col-right">
          <div class="panel-title with-action">3. 选择模板
            <el-button text type="primary" size="small" @click="router.push('/ppt/templates')">
              模板库<el-icon><ArrowRight /></el-icon>
            </el-button>
          </div>
          <div class="tpl-tabs">
            <span v-for="c in tplCats" :key="c" class="tpl-tab"
                  :class="{ active: tplCat === c }" @click="tplCat = c">{{ c }}</span>
          </div>
          <div class="tpl-search">
            <el-input v-model="tplKeyword" size="small" placeholder="搜索模板名称" clearable>
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-select v-model="tplSort" size="small" style="width:100px">
              <el-option label="最新" value="new" /><el-option label="最热" value="hot" />
            </el-select>
          </div>
          <div v-loading="tplLoading" class="tpl-grid">
            <div v-for="t in filteredTemplates" :key="t.id" class="tpl-card"
                 :class="{ active: form.templateId === t.id }" @click="form.templateId = t.id">
              <div class="tpl-cover" :style="{ background: 'linear-gradient(135deg, #' + t.colors.primary + ', #' + t.colors.dark + ')' }">
                <span class="tc-deco" :style="{ background: '#' + t.colors.accent }" />
                <span class="tc-title">{{ t.name }}</span>
                <el-icon v-if="form.templateId === t.id" class="tc-check"><CircleCheckFilled /></el-icon>
              </div>
              <div class="tpl-foot">
                <span class="tpl-name">{{ t.name }}</span>
                <span class="tpl-info">{{ t.use_count }}次使用 · 16:9</span>
              </div>
            </div>
            <el-empty v-if="!tplLoading && !filteredTemplates.length" description="暂无模板" :image-size="60" style="grid-column:1/-1" />
          </div>

          <!-- 模板预览 -->
          <div v-if="selectedTemplate" class="tpl-preview-block">
            <div class="pv-head">模板预览<span class="muted">（{{ selectedTemplate.name }}）</span></div>
            <div class="pv-strip">
              <div v-for="p in previewPages" :key="p.label" class="pv-item">
                <div class="pv-mini" :style="pvStyle(p.type)">
                  <span v-if="p.type === 'cover'" class="pv-mini-band" :style="{ background: '#' + selectedTemplate.colors.accent }" />
                  <template v-if="p.type === 'toc'"><i v-for="i in 3" :key="i" /></template>
                  <template v-if="p.type === 'content'"><i v-for="i in 3" :key="i" class="thin" /></template>
                  <template v-if="p.type === 'data'">
                    <b v-for="i in 3" :key="i" :style="{ background: '#' + selectedTemplate.colors.light }" />
                  </template>
                </div>
                <span class="pv-label">{{ p.label }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="next-bar">
        <el-button type="primary" size="large" :loading="aiLoading" @click="nextStep">
          下一步：AI 生成大纲<el-icon><ArrowRight /></el-icon>
        </el-button>
      </div>
    </template>

    <!-- ================= 我的 PPT ================= -->
    <template v-else>
      <div class="panel">
        <div class="section-head">
          <el-radio-group v-model="docTab" size="small" @change="loadDocuments">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button value="draft">草稿</el-radio-button>
            <el-radio-button value="generated">已生成</el-radio-button>
            <el-radio-button value="favorite">收藏</el-radio-button>
          </el-radio-group>
        </div>
        <div v-loading="docLoading" class="doc-grid">
          <div v-for="d in documents" :key="d.id" class="doc-card" @click="editDoc(d)">
            <div class="doc-cover" :style="{ background: coverColor(d) }">
              <span class="doc-cover-title">{{ d.title }}</span>
              <el-tag size="small" effect="dark" :type="d.status === 'generated' ? 'success' : 'info'" class="doc-tag">
                {{ d.status === 'generated' ? '已生成' : '草稿' }}
              </el-tag>
            </div>
            <div class="doc-body">
              <div class="doc-name">{{ d.title }}</div>
              <div class="doc-meta">{{ d.slide_count }} 页 · {{ d.template_name || '默认模板' }} · {{ d.updated_at }}</div>
              <div class="doc-ops" @click.stop>
                <el-button size="small" type="primary" plain @click="editDoc(d)">继续编辑</el-button>
                <el-tooltip content="下载 PPTX"><el-button size="small" circle :icon="Download" :disabled="d.status !== 'generated'" @click="downloadDoc(d)" /></el-tooltip>
                <el-tooltip content="复制"><el-button size="small" circle :icon="CopyDocument" @click="copyDoc(d)" /></el-tooltip>
                <el-tooltip content="收藏"><el-button size="small" circle :icon="Star" :type="d.is_favorite ? 'warning' : 'default'" @click="favDoc(d)" /></el-tooltip>
                <el-tooltip content="删除"><el-button size="small" circle type="danger" plain :icon="Delete" @click="deleteDoc(d)" /></el-tooltip>
              </div>
            </div>
          </div>
          <el-empty v-if="!docLoading && !documents.length" description="还没有 PPT，去创建一个吧" :image-size="70" style="grid-column:1/-1" />
        </div>
      </div>
    </template>

    <!-- ===== AI 大纲编辑对话框 ===== -->
    <el-dialog v-model="outlineVisible" title="AI 生成大纲（可直接修改）" width="680px" destroy-on-close>
      <div class="outline-head">
        <el-input v-model="outline.title" placeholder="PPT 标题" class="outline-title" />
        <el-input v-model="outline.subtitle" placeholder="副标题" size="small" style="width:240px" />
      </div>
      <div class="outline-list">
        <div v-for="(s, i) in outline.slides" :key="s.id || i" class="outline-item">
          <div class="oi-top">
            <el-tag size="small" :type="typeTag(s.type)">{{ typeLabel(s.type) }}</el-tag>
            <el-input v-model="s.title" size="small" class="oi-title" placeholder="页面标题" />
            <el-button size="small" :icon="Delete" circle text type="danger"
                       :disabled="outline.slides.length <= 2" @click="outline.slides.splice(i, 1)" />
          </div>
          <div v-for="(p, j) in s.points" :key="j" class="oi-point">
            <el-input v-model="s.points[j]" size="small" />
            <el-button size="small" text :icon="Close" @click="s.points.splice(j, 1)" />
          </div>
          <el-button size="small" text type="primary" :icon="Plus" @click="s.points.push('')">加一条要点</el-button>
        </div>
      </div>
      <div class="dlg-footer">
        <el-button text size="small" @click="cloudVisible = true">
          <el-icon><Setting /></el-icon>云生成设置{{ cloudCfg.enabled ? '（已开启）' : '（未开启）' }}
        </el-button>
        <el-button @click="addOutlinePage"><el-icon><Plus /></el-icon>新增页面</el-button>
        <el-button v-if="cloudCfg.enabled" type="warning" plain :loading="aiLoading"
                   @click="cloudGenerate">云端生成（脱敏验证）</el-button>
        <el-button type="primary" :loading="aiLoading" @click="createAndEdit">创建并进入编辑器</el-button>
      </div>
    </el-dialog>

    <!-- ===== 云端生成设置 ===== -->
    <el-dialog v-model="cloudVisible" title="云端生成设置（qwen-doc-turbo）" width="520px" destroy-on-close>
      <el-alert type="warning" :closable="false" style="margin-bottom:14px"
                title="注意：云端生成会将材料发送至阿里云，仅限脱敏/虚构材料验证效果，请勿用于真实业务数据" />
      <el-form label-width="110px">
        <el-form-item label="启用云端生成">
          <el-switch v-model="cloudForm.enabled" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="cloudForm.api_key" type="password" show-password
                    :placeholder="cloudCfg.has_key ? '已配置（留空不修改）' : '华北2（北京）地域的 DashScope Key'" />
        </el-form-item>
        <el-form-item label="接口地址">
          <el-input v-model="cloudForm.base_url" />
        </el-form-item>
        <el-form-item label="生成模式">
          <el-radio-group v-model="cloudForm.mode">
            <el-radio value="general">模板模式（可编辑）</el-radio>
            <el-radio value="creative">创意模式（图版，每页为图片）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="cloudForm.mode === 'general'" label="官方模板">
          <el-select v-model="cloudForm.template_id" style="width:100%">
            <el-option label="总结模板 summary_01" value="summary_01" />
            <el-option label="新闻模板 news_01" value="news_01" />
            <el-option label="互联网模板 internet_01" value="internet_01" />
            <el-option label="论文模板 thesis_01" value="thesis_01" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="dlg-footer">
        <el-button @click="cloudVisible = false">取消</el-button>
        <el-button type="primary" :loading="aiLoading" @click="saveCloud">保存设置</el-button>
      </div>
    </el-dialog>

    <!-- ===== 选择知识库 ===== -->
    <el-dialog v-model="kbDialogVisible" title="选择知识库" width="520px" destroy-on-close>
      <el-table :data="kbs" size="small" @selection-change="onKbSelect" ref="kbTableRef">
        <el-table-column type="selection" width="45" />
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="doc_count" label="文档数" width="80" align="center" />
        <el-table-column prop="description" label="说明" min-width="160" show-overflow-tooltip />
      </el-table>
      <div class="dlg-footer">
        <el-button type="primary" @click="kbDialogVisible = false">确定</el-button>
      </div>
    </el-dialog>

    <!-- ===== 素材库抽屉 ===== -->
    <el-drawer v-model="materialVisible" title="素材库（命名后 AI 自动配图）" size="440px">
      <el-upload :show-file-list="false" :http-request="uploadMaterial" accept="image/*">
        <el-button type="primary"><el-icon><Upload /></el-icon>上传图片</el-button>
      </el-upload>
      <div class="mat-list">
        <div v-for="m in materials" :key="m.id" class="mat-item">
          <img :src="m.url" class="mat-img" />
          <div class="mat-fields">
            <el-input v-model="m.name" size="small" placeholder="图片名称（AI 按名称选用）" @change="saveMaterial(m)" />
            <el-input v-model="m.caption" size="small" placeholder="图片说明（帮助 AI 判断插入位置）" @change="saveMaterial(m)" />
          </div>
          <el-button size="small" :icon="Delete" circle text type="danger" @click="removeMaterial(m)" />
        </div>
        <el-empty v-if="!materials.length" description="暂无素材" :image-size="60" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MagicStick, Document, Coin, Collection, CircleCheckFilled, Search, Upload,
         Plus, Close, ArrowRight, Star, Download, CopyDocument, Delete, Picture,
         Setting } from '@element-plus/icons-vue'
import axios from 'axios'
// 项目统一请求：直接基于 axios，自动带 token
const request = axios.create({ baseURL: '/api/v1' })
request.interceptors.request.use(cfg => {
  const t = localStorage.getItem('token')
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

const router = useRouter()
const route = useRoute()
const pageTab = ref('create')
const aiLoading = ref(false)

/* ---------- 创建方式 ---------- */
const method = ref('ai')
const methods = [
  { key: 'ai', name: 'AI 生成 PPT', desc: '输入主题，AI生成完整PPT', icon: MagicStick, bg: '#e8efff', color: '#4a7ff7' },
  { key: 'doc', name: '根据文档生成', desc: '上传文档，自动提炼生成', icon: Document, bg: '#e6f7ec', color: '#2aa25f' },
  { key: 'kb', name: '根据知识库生成', desc: '基于知识库内容生成', icon: Coin, bg: '#f3ecfd', color: '#7b53c1' },
  { key: 'tpl', name: '使用模板创建', desc: '选择模板，快速创作', icon: Collection, bg: '#fdf0e2', color: '#e08a2d' },
]

/* ---------- 表单 ---------- */
const form = ref({ topic: '', content: '', audience: '', scene: '', slideCount: 15, templateId: null })
const audiences = ['局领导', '上级机关', '全体干部职工', '社会公众', '企业代表', '其他']
const scenes = ['工作汇报', '领导汇报', '政策解读', '培训课件', '经验交流', '总结汇报', '宣传展示']
const pageCounts = [
  { label: '10页左右', value: 10 }, { label: '15页左右', value: 15 }, { label: '18页左右', value: 18 }]
const refMode = ref('doc')

/* ---------- 参考材料 ---------- */
const files = ref([])
const onFilePicked = (f) => {
  if (f.size > 50 * 1024 * 1024) return ElMessage.warning('单个文件不超过50MB')
  files.value.push({ name: f.name, size: f.size, raw: f.raw })
}
const fileExt = (n) => (n.split('.').pop() || '').toUpperCase().slice(0, 4)
const fileClass = (n) => {
  const e = fileExt(n)
  if (e.startsWith('DOC')) return 'ft-doc'
  if (e.startsWith('XLS')) return 'ft-xls'
  if (e === 'PDF') return 'ft-pdf'
  return 'ft-txt'
}
const formatSize = (s) => s > 1048576 ? (s / 1048576).toFixed(1) + 'MB' : Math.round(s / 1024) + 'KB'

/* ---------- 知识库 ---------- */
const kbs = ref([]), selectedKbs = ref([]), kbDialogVisible = ref(false)
const loadKbs = async () => { const { data } = await request.get('/ppt/kbs'); kbs.value = data.items }
const onKbSelect = (rows) => { selectedKbs.value = rows }
const removeKb = (kb) => { selectedKbs.value = selectedKbs.value.filter(x => x.id !== kb.id) }

/* ---------- 模板 ---------- */
const templates = ref([]), tplLoading = ref(false), tplKeyword = ref(''), tplSort = ref('new'), tplCat = ref('全部')
const tplCats = ['全部', '工作汇报', '领导汇报', '政策解读', '培训课件', '经验交流']
const loadTemplates = async () => {
  tplLoading.value = true
  try {
    const { data } = await request.get('/ppt/templates', { params: { scope: 'all' } })
    templates.value = data.items
    if (!form.value.templateId && data.items.length) form.value.templateId = data.items[0].id
  } finally { tplLoading.value = false }
}
const filteredTemplates = computed(() => {
  let list = templates.value
  if (tplCat.value !== '全部') list = list.filter(t => t.category === tplCat.value)
  if (tplKeyword.value) list = list.filter(t => t.name.includes(tplKeyword.value))
  if (tplSort.value === 'hot') list = [...list].sort((a, b) => b.use_count - a.use_count)
  return list
})
const selectedTemplate = computed(() => templates.value.find(t => t.id === form.value.templateId))
const previewPages = [
  { type: 'cover', label: '封面页' }, { type: 'toc', label: '目录页' },
  { type: 'section', label: '章节页' }, { type: 'content', label: '内容页' },
  { type: 'data', label: '数据页' }, { type: 'closing', label: '结束页' },
]
const pvStyle = (type) => {
  if (!selectedTemplate.value) return {}
  const c = selectedTemplate.value.colors
  if (['cover', 'section', 'closing'].includes(type))
    return { background: '#' + c.primary }
  return { background: '#fff', borderColor: '#' + c.light }
}

/* ---------- 下一步：生成大纲 ---------- */
const outline = ref({ title: '', subtitle: '', slides: [] })
const outlineVisible = ref(false), docId = ref(null)
const nextStep = async () => {
  if (!form.value.topic.trim() && !files.value.length && !selectedKbs.value.length && !form.value.content.trim())
    return ElMessage.warning('请填写主题，或提供参考材料')
  if (!form.value.templateId) return ElMessage.warning('请选择模板')
  aiLoading.value = true
  try {
    let res
    if (method.value === 'kb' || (method.value === 'ai' && selectedKbs.value.length && !form.value.topic.trim())) {
      const fd = new FormData()
      selectedKbs.value.forEach(k => fd.append('kb_ids', k.id))
      fd.append('topic', form.value.topic); fd.append('audience', form.value.audience)
      fd.append('scene', form.value.scene); fd.append('slide_count', form.value.slideCount)
      res = await request.post('/ppt/outline-from-kb', fd)
    } else if (method.value === 'doc' && files.value.length) {
      // 多文件：逐个提取文本后合并
      const texts = []
      for (const f of files.value) {
        const fd = new FormData()
        fd.append('file', f.raw)
        const r = await request.post('/ppt/extract-text', fd)
        texts.push(`《${f.name}》\n${r.data.text}`)
      }
      res = await request.post('/ppt/outline', {
        source_type: 'document', topic: form.value.topic, content: texts.join('\n\n'),
        slide_count: form.value.slideCount, audience: form.value.audience, scene: form.value.scene })
    } else {
      res = await request.post('/ppt/outline', {
        source_type: method.value === 'ai' || method.value === 'tpl' ? 'topic' : 'text',
        topic: form.value.topic, content: form.value.content,
        slide_count: form.value.slideCount, audience: form.value.audience, scene: form.value.scene })
    }
    outline.value = res.data.outline
    docId.value = res.data.doc_id
    outlineVisible.value = true
  } finally { aiLoading.value = false }
}
const addOutlinePage = () => outline.value.slides.splice(outline.value.slides.length - 1, 0,
  { id: Math.random().toString(36).slice(2, 10), type: 'content', title: '', points: [], blocks: {} })
const typeLabel = (t) => ({ cover: '封面', toc: '目录', section: '章节', content: '正文', data: '数据',
  chart: '图表', case: '案例', timeline: '时间轴', process: '流程', summary: '总结', closing: '结束' }[t] || t)
const typeTag = (t) => ({ cover: 'danger', toc: 'warning', section: 'warning', closing: 'success' }[t] || '')
const createAndEdit = async () => {
  aiLoading.value = true
  try {
    await request.put(`/ppt/documents/${docId.value}/draft`, {
      outline: outline.value, template_id: form.value.templateId })
    outlineVisible.value = false
    router.push(`/ppt/edit/${docId.value}`)
  } finally { aiLoading.value = false }
}

/* ---------- 我的 PPT ---------- */
const docTab = ref('all'), documents = ref([]), docLoading = ref(false)
const loadDocuments = async () => {
  docLoading.value = true
  try {
    const { data } = await request.get('/ppt/documents', { params: { tab: docTab.value } })
    documents.value = data.items
  } finally { docLoading.value = false }
}
const coverColor = (d) => {
  const t = templates.value.find(x => x.id === d.template_id)
  return t ? '#' + t.colors.primary : '#4a7ff7'
}
const editDoc = (d) => router.push(`/ppt/edit/${d.id}`)
const copyDoc = async (d) => { await request.post(`/ppt/documents/${d.id}/copy`); ElMessage.success('已复制'); loadDocuments() }
const favDoc = async (d) => { const { data } = await request.post(`/ppt/documents/${d.id}/favorite`); d.is_favorite = data.is_favorite }
const deleteDoc = async (d) => {
  await ElMessageBox.confirm(`确定删除「${d.title}」？`, '提示', { type: 'warning' })
  await request.delete(`/ppt/documents/${d.id}`)
  ElMessage.success('已删除'); loadDocuments()
}
const downloadDoc = async (d) => {
  const res = await request.get(`/ppt/documents/${d.id}/download`, { responseType: 'blob' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(res.data)
  a.download = `${d.title || 'PPT'}.pptx`
  a.click()
  URL.revokeObjectURL(a.href)
}

/* ---------- 素材库 ---------- */
const materialVisible = ref(false), materials = ref([])
const loadMaterials = async () => { const { data } = await request.get('/ppt/materials'); materials.value = data.items }
const uploadMaterial = async ({ file }) => {
  const fd = new FormData()
  fd.append('file', file); fd.append('name', file.name.replace(/\.\w+$/, '')); fd.append('caption', '')
  await request.post('/ppt/materials', fd)
  ElMessage.success('已上传，请命名并填写说明'); loadMaterials()
}
const saveMaterial = async (m) => {
  const fd = new FormData()
  fd.append('name', m.name); fd.append('caption', m.caption || '')
  await request.put(`/ppt/materials/${m.id}`, fd)
  ElMessage.success('已保存')
}
const removeMaterial = async (m) => { await request.delete(`/ppt/materials/${m.id}`); loadMaterials() }

/* ---------- 云端生成（可选开关，默认关闭） ---------- */
const cloudCfg = ref({ enabled: false, has_key: false })
const cloudVisible = ref(false)
const cloudForm = ref({ enabled: false, api_key: '', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', mode: 'general', template_id: 'summary_01' })
const loadCloud = async () => {
  try {
    const { data } = await request.get('/ppt/cloud-config')
    cloudCfg.value = data
    cloudForm.value = { enabled: !!data.enabled, api_key: '', base_url: data.base_url || cloudForm.value.base_url,
      mode: data.mode || 'general', template_id: data.template_id || 'summary_01' }
  } catch (e) { /* 未配置 */ }
}
const saveCloud = async () => {
  aiLoading.value = true
  try {
    await request.put('/ppt/cloud-config', cloudForm.value)
    cloudVisible.value = false
    ElMessage.success('云端设置已保存')
    loadCloud()
  } catch (e) { ElMessage.error(e.response?.data?.detail || '保存失败') }
  finally { aiLoading.value = false }
}
const cloudGenerate = async () => {
  if (!currentDoc.value?.id) { ElMessage.warning('请先保存草稿再云端生成'); return }
  try {
    await ElMessageBox.confirm('云端生成会将脱敏后的大纲文本发送至阿里云 DashScope，请勿用于真实业务数据。确定继续？',
      '数据安全提示', { type: 'warning', confirmButtonText: '已脱敏，继续', cancelButtonText: '取消' })
  } catch (e) { return }
  aiLoading.value = true
  try {
    await request.put(`/ppt/documents/${docId.value}/draft`, {
      outline: outline.value, template_id: form.value.templateId })
    const { data } = await request.post('/ppt/generate-cloud', {
      doc_id: docId.value, mode: cloudForm.value.mode, template_id: cloudForm.value.template_id
    }, { timeout: 300000 })
    ElMessage.success(data.message || '云端生成完成')
    if (data.download_url) {
      const res = await request.get(data.download_url, { responseType: 'blob' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(res.data)
      a.download = (form.value.topic || '云端生成PPT') + '.pptx'
      a.click(); URL.revokeObjectURL(a.href)
    }
    loadDocuments()
  } catch (e) { ElMessage.error(e.response?.data?.detail || '云端生成失败') }
  finally { aiLoading.value = false }
}

onMounted(async () => {
  loadCloud()
  await Promise.all([loadTemplates(), loadDocuments(), loadMaterials(), loadKbs()])
  if (route.query.template && templates.value.find(t => t.id === route.query.template))
    form.value.templateId = route.query.template
  if (route.query.tab === 'mine') pageTab.value = 'mine'
  request.post('/ppt/templates/seed').then(loadTemplates).catch(() => {})
})
</script>

<style scoped>
.ppt-home { padding: 20px 26px 30px; background: linear-gradient(180deg, #eef2fb 0%, #f5f6fa 220px);
  min-height: 100%; }
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
.panel { background: #fff; border-radius: 12px; padding: 20px 22px; margin-bottom: 18px;
  border: 1px solid #eaeef5; box-shadow: 0 1px 4px rgba(30, 50, 100, .04); }
.panel-title { font-size: 15px; font-weight: 600; color: #303133; margin-bottom: 16px;
  display: flex; align-items: center; }
.panel-title::before { content: ''; display: inline-block; width: 4px; height: 16px;
  background: #4a7ff7; border-radius: 2px; margin-right: 8px; }
.panel-title.with-action { justify-content: flex-start; }
.panel-title.with-action .el-button { margin-left: auto; }
.muted { font-size: 12px; color: #909399; font-weight: 400; }

/* 创建方式 */
.method-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.method-card { display: flex; align-items: center; gap: 13px; border: 1.5px solid #e8ecf3;
  border-radius: 12px; padding: 18px 16px; cursor: pointer; position: relative;
  transition: all .18s; background: #fbfcfe; }
.method-card:hover { border-color: #b3c8f5; transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(74,127,247,.10); }
.method-card.active { border-color: #4a7ff7; background: linear-gradient(180deg, #f5f8ff, #eef4ff);
  box-shadow: 0 6px 16px rgba(74,127,247,.14); }
.mc-icon { width: 46px; height: 46px; border-radius: 12px; display: flex; align-items: center;
  justify-content: center; flex-shrink: 0; }
.mc-name { font-size: 14px; font-weight: 600; color: #303133; }
.mc-desc { font-size: 12px; color: #909399; margin-top: 3px; }
.mc-check { position: absolute; right: 10px; bottom: 10px; color: #4a7ff7; font-size: 18px; }

/* 左右两栏 */
.two-col { display: grid; grid-template-columns: 5fr 7fr; gap: 18px; align-items: start; }
.form-row { display: flex; gap: 12px; margin-top: 14px; }
.form-item { flex: 1; }
.form-item label { font-size: 12px; color: #606266; display: block; margin-bottom: 5px; }
.form-item .el-select { width: 100%; }

/* 参考材料 */
.ref-btns { display: flex; gap: 10px; margin-bottom: 12px; }
.file-row { display: flex; align-items: center; gap: 10px; background: #f7f9fd;
  border: 1px solid #eef1f7; border-radius: 8px; padding: 9px 12px; margin-bottom: 8px; }
.file-icon { width: 30px; height: 34px; border-radius: 5px; color: #fff; font-size: 9px;
  font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.ft-doc { background: #4a7ff7; } .ft-xls { background: #2aa25f; }
.ft-pdf { background: #e05555; } .ft-txt { background: #909399; }
.file-name { flex: 1; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-size { font-size: 12px; color: #909399; }
.file-ok { color: #2aa25f; }
.file-del { color: #c0c4cc; cursor: pointer; } .file-del:hover { color: #e05555; }
.drag-inner { padding: 10px 0; }
.drag-inner p { margin: 4px 0; font-size: 13px; color: #606266; }
.kb-tags { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }

/* 模板 */
.tpl-tabs { display: flex; gap: 20px; margin-bottom: 14px; flex-wrap: wrap; }
.tpl-tab { font-size: 13px; color: #606266; cursor: pointer; padding-bottom: 5px;
  border-bottom: 2px solid transparent; }
.tpl-tab:hover { color: #4a7ff7; }
.tpl-tab.active { color: #4a7ff7; font-weight: 600; border-bottom-color: #4a7ff7; }
.tpl-search { display: flex; gap: 10px; margin-bottom: 14px; }
.tpl-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 13px; }
.tpl-card { border: 1.5px solid #e8ecf3; border-radius: 10px; overflow: hidden; cursor: pointer;
  transition: all .18s; background: #fff; }
.tpl-card:hover { border-color: #b3c8f5; transform: translateY(-2px);
  box-shadow: 0 6px 14px rgba(74,127,247,.12); }
.tpl-card.active { border-color: #4a7ff7; box-shadow: 0 0 0 3px rgba(74,127,247,.14); }
.tpl-cover { height: 92px; position: relative; padding: 13px; display: flex;
  flex-direction: column; justify-content: center; }
.tc-deco { width: 40%; height: 4px; border-radius: 2px; margin-bottom: 8px; opacity: .9; }
.tc-title { color: #fff; font-size: 13px; font-weight: 700; }
.tc-check { position: absolute; right: 8px; top: 8px; color: #fff; font-size: 18px; }
.tpl-foot { padding: 9px 11px; }
.tpl-name { font-size: 13px; font-weight: 600; display: block; }
.tpl-info { font-size: 11px; color: #909399; }

/* 模板预览 */
.tpl-preview-block { margin-top: 18px; border-top: 1px solid #f0f2f7; padding-top: 16px; }
.pv-head { font-size: 13px; font-weight: 600; margin-bottom: 12px; }
.pv-strip { display: flex; gap: 10px; }
.pv-item { flex: 1; text-align: center; }
.pv-mini { height: 56px; border: 1px solid #e8ecf3; border-radius: 6px; display: flex;
  align-items: center; justify-content: center; gap: 3px; padding: 6px; position: relative;
  transition: box-shadow .15s; }
.pv-mini:hover { box-shadow: 0 3px 10px rgba(0,0,0,.08); }
.pv-mini-band { position: absolute; left: 8px; top: 8px; width: 40%; height: 4px; border-radius: 2px; }
.pv-mini i { width: 70%; height: 5px; background: #e4e7ed; border-radius: 2px; display: block; }
.pv-mini i.thin { width: 60%; }
.pv-mini b { width: 12px; height: 16px; border-radius: 2px; }
.pv-label { font-size: 11px; color: #909399; margin-top: 5px; display: block; }

.next-bar { display: flex; justify-content: flex-end; padding: 6px 0 12px; }
.next-bar .el-button { padding: 12px 28px; font-size: 15px; border-radius: 10px;
  box-shadow: 0 4px 12px rgba(74,127,247,.3); }

/* 我的PPT */
.section-head { margin-bottom: 14px; }
.doc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 14px; }
.doc-card { border: 1px solid #e8ecf3; border-radius: 10px; overflow: hidden; cursor: pointer;
  transition: all .18s; background: #fff; }
.doc-card:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(0,0,0,.10); }
.doc-cover { height: 100px; position: relative; display: flex; align-items: center;
  justify-content: center; padding: 0 14px; }
.doc-cover-title { color: #fff; font-weight: 600; font-size: 14px; text-align: center;
  overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.doc-tag { position: absolute; top: 8px; right: 8px; }
.doc-body { padding: 10px 12px; }
.doc-name { font-weight: 600; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.doc-meta { font-size: 12px; color: #909399; margin: 5px 0 8px; }
.doc-ops { display: flex; gap: 6px; }

/* 大纲对话框 */
.outline-head { display: flex; gap: 10px; margin-bottom: 12px; }
.outline-title { flex: 1; font-weight: 700; }
.outline-list { max-height: 400px; overflow: auto; }
.outline-item { border: 1px solid #ebeef5; border-radius: 8px; padding: 10px; margin-bottom: 10px; }
.oi-top { display: flex; gap: 8px; align-items: center; }
.oi-title { flex: 1; }
.oi-point { display: flex; gap: 6px; margin-top: 6px; padding-left: 20px; }
.dlg-footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px; }

/* 素材库 */
.mat-list { margin-top: 14px; }
.mat-item { display: flex; gap: 10px; margin-bottom: 12px; align-items: center; }
.mat-img { width: 80px; height: 56px; object-fit: cover; border-radius: 6px; }
.mat-fields { flex: 1; display: flex; flex-direction: column; gap: 6px; }
</style>