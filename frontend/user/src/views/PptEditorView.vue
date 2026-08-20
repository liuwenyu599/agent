<template>
  <div class="editor">
    <!-- ===== 顶栏 ===== -->
    <div class="topbar">
      <el-button text @click="goBack"><el-icon><ArrowLeft /></el-icon>返回</el-button>
      <el-input v-model="doc.title" class="title-input" @input="markDirty" />
      <span class="save-state">{{ saveState }}</span>
      <el-select v-model="doc.template_id" placeholder="更换模板" style="width:170px" @change="switchTemplate">
        <el-option-group label="官方模板">
          <el-option v-for="t in officialTemplates" :key="t.id" :label="t.name" :value="t.id" />
        </el-option-group>
        <el-option-group v-if="myTemplates.length" label="我的模板">
          <el-option v-for="t in myTemplates" :key="t.id" :label="t.name" :value="t.id" />
        </el-option-group>
      </el-select>
      <el-button :loading="saving" @click="saveNow">保存</el-button>
      <el-button type="primary" :loading="exporting" @click="exportPptx">
        <el-icon><Download /></el-icon>导出 PPTX
      </el-button>
    </div>

    <div class="editor-body">
      <!-- ===== 左：页面缩略图 ===== -->
      <div class="thumb-pane">
        <div class="thumb-head">
          <span>页面（{{ slides.length }}）</span>
          <el-button size="small" text type="primary" :icon="Plus" @click="addSlide">添加</el-button>
        </div>
        <div v-for="(s, i) in slides" :key="s.id || i" class="thumb"
             :class="{ active: cur === i }" @click="cur = i">
          <span class="thumb-no">{{ i + 1 }}</span>
          <div class="thumb-mini" :style="thumbStyle(s)">
            <span class="thumb-title">{{ s.title || typeLabel(s.type) }}</span>
          </div>
          <span class="thumb-type">{{ typeLabel(s.type) }}</span>
        </div>
        <div class="thumb-ops" v-if="current">
          <el-button size="small" @click="dupSlide"><el-icon><CopyDocument /></el-icon>复制</el-button>
          <el-button size="small" :disabled="cur <= 1" @click="moveSlide(-1)"><el-icon><Top /></el-icon></el-button>
          <el-button size="small" :disabled="cur >= slides.length - 2" @click="moveSlide(1)"><el-icon><Bottom /></el-icon></el-button>
          <el-button size="small" type="danger" plain :disabled="slides.length <= 2" @click="delSlide">
            <el-icon><Delete /></el-icon></el-button>
        </div>
      </div>

      <!-- ===== 中：画布预览 ===== -->
      <div class="canvas-pane" v-if="current">
        <div class="canvas" :style="{ fontFamily: tpl.font }">
          <!-- 封面 / 结束页 -->
          <div v-if="current.type === 'cover' || current.type === 'closing'" class="cv-full"
               :style="{ background: 'linear-gradient(135deg, #' + tpl.colors.primary + ', #' + tpl.colors.dark + ')' }">
            <div class="cv-band" :style="{ background: '#' + tpl.colors.accent }" />
            <input v-model="current.title" class="cv-title" @input="markDirty" />
            <input v-if="current.type === 'cover'" v-model="current.subtitle" class="cv-sub"
                   placeholder="副标题" @input="markDirty" />
          </div>
          <template v-else>
            <div class="pg-head" :style="headStyle">
              <span v-if="(tpl.layouts.content || 'bar_title') === 'bar_title'" class="pg-bar"
                    :style="{ background: '#' + tpl.colors.primary }" />
              <input v-model="current.title" class="pg-title"
                     :style="headTextStyle" @input="markDirty" />
            </div>
            <div class="pg-body">
              <!-- 目录 -->
              <template v-if="current.type === 'toc'">
                <div v-for="(p, j) in current.points" :key="j" class="toc-row">
                  <span class="toc-no" :style="{ background: '#' + tpl.colors.primary }">{{ j + 1 }}</span>
                  <el-input v-model="current.points[j]" size="default" @input="markDirty" />
                  <span class="row-del" @click="current.points.splice(j, 1); markDirty()">×</span>
                </div>
                <a class="pt-add" @click="current.points.push(''); markDirty()">+ 添加目录项</a>
              </template>
              <!-- 数据卡片 -->
              <template v-else-if="current.type === 'data'">
                <div class="data-cards">
                  <div v-for="(c, j) in (current.blocks.cards || [])" :key="j" class="data-card"
                       :style="{ background: '#' + tpl.colors.light, borderTopColor: '#' + tpl.colors.primary }">
                    <input v-model="c.value" class="dc-value" :style="{ color: '#' + tpl.colors.primary }"
                           @input="markDirty" />
                    <input v-model="c.label" class="dc-label" @input="markDirty" />
                  </div>
                </div>
                <div class="pt-list">
                  <div v-for="(p, j) in current.points" :key="j" class="pt-row">
                    <span class="pt-dot" :style="{ background: '#' + tpl.colors.accent }" />
                    <el-input v-model="current.points[j]" size="default" @input="markDirty" />
                    <span class="row-del" @click="current.points.splice(j, 1); markDirty()">×</span>
                  </div>
                  <a class="pt-add" @click="current.points.push(''); markDirty()">+ 添加要点</a>
                </div>
              </template>
              <!-- 图表 -->
              <template v-else-if="current.type === 'chart'">
                <div v-if="hasChart" class="chart-box">
                  <div v-for="(cat, ci) in current.blocks.chart.categories" :key="ci" class="bar-col">
                    <div class="bar-group">
                      <div v-for="(se, si) in current.blocks.chart.series" :key="si" class="bar"
                           :title="se.name + ': ' + se.values[ci]"
                           :style="{ height: barHeight(se.values[ci]),
                                     background: si % 2 ? '#' + tpl.colors.accent : '#' + tpl.colors.primary }" />
                    </div>
                    <span class="bar-cat">{{ cat }}</span>
                  </div>
                </div>
                <div v-else class="chart-empty">暂无图表数据，可点右侧「图表」由 AI 生成</div>
                <div class="chart-tip">导出后为 PowerPoint 原生图表，可继续编辑数据</div>
                <div class="pt-list">
                  <div v-for="(p, j) in current.points" :key="j" class="pt-row">
                    <span class="pt-dot" :style="{ background: '#' + tpl.colors.accent }" />
                    <el-input v-model="current.points[j]" size="default" @input="markDirty" />
                    <span class="row-del" @click="current.points.splice(j, 1); markDirty()">×</span>
                  </div>
                  <a class="pt-add" @click="current.points.push(''); markDirty()">+ 添加要点</a>
                </div>
              </template>
              <!-- 时间轴 -->
              <template v-else-if="current.type === 'timeline'">
                <div class="tl-line" :style="{ background: '#' + tpl.colors.accent }" />
                <div class="tl-row">
                  <div v-for="(t, j) in (current.blocks.timeline || [])" :key="j" class="tl-item">
                    <input v-model="t.time" class="tl-time" :style="{ color: '#' + tpl.colors.primary }"
                           @input="markDirty" />
                    <span class="tl-dot" :style="{ background: '#' + tpl.colors.primary }" />
                    <el-input v-model="t.text" size="small" type="textarea" :rows="2" @input="markDirty" />
                  </div>
                </div>
              </template>
              <!-- 流程 -->
              <template v-else-if="current.type === 'process'">
                <div class="pc-row">
                  <div v-for="(st, j) in (current.blocks.process || [])" :key="j" class="pc-step"
                       :style="{ background: j % 2 ? '#' + tpl.colors.dark : '#' + tpl.colors.primary }">
                    <input v-model="current.blocks.process[j]" class="pc-input" @input="markDirty" />
                  </div>
                </div>
              </template>
              <!-- 正文 / 章节 / 案例 / 总结 -->
              <template v-else>
                <div class="pt-list">
                  <div v-for="(p, j) in current.points" :key="j" class="pt-row">
                    <span class="pt-dot" :style="{ background: '#' + tpl.colors.accent }" />
                    <el-input v-model="current.points[j]" size="default" @input="markDirty" />
                    <span class="row-del" @click="current.points.splice(j, 1); markDirty()">×</span>
                  </div>
                  <a class="pt-add" @click="current.points.push(''); markDirty()">+ 添加要点</a>
                </div>
                <div v-if="current.image_name" class="img-hint">已配图：{{ current.image_name }}</div>
              </template>
            </div>
          </template>
          <div class="pg-note">
            <el-input v-model="current.note" size="small" placeholder="演讲备注（可选）" @input="markDirty" />
          </div>
        </div>

        <!-- 页型 / 版式 / 配图 -->
        <div class="page-toolbar">
          <span class="muted">页型</span>
          <el-select v-model="current.type" size="small" style="width:110px" @change="onTypeChange">
            <el-option v-for="pt in pageTypes" :key="pt.value" :label="pt.label" :value="pt.value" />
          </el-select>
          <template v-if="layoutVariants(current.type).length">
            <span class="muted">版式</span>
            <el-select v-model="current.layout" size="small" style="width:150px" clearable
                       placeholder="模板默认" @change="markDirty">
              <el-option v-for="v in layoutVariants(current.type)" :key="v.value" :label="v.label" :value="v.value" />
            </el-select>
          </template>
          <span class="muted">配图</span>
          <el-select v-model="current.image_name" size="small" style="width:160px" clearable
                     placeholder="选择素材图片" @change="markDirty">
            <el-option v-for="m in materials" :key="m.id" :label="m.name" :value="m.name" />
          </el-select>
        </div>
      </div>

      <!-- ===== 右：AI 助手 ===== -->
      <div class="ai-pane">
        <div class="ai-head">AI 助手</div>
        <div class="ai-section">
          <div class="ai-sec-title">单页改写</div>
          <div class="ai-btns">
            <el-button size="small" :loading="aiBusy" @click="aiSlide('rewrite')">重写</el-button>
            <el-button size="small" :loading="aiBusy" @click="aiSlide('expand')">扩写</el-button>
            <el-button size="small" :loading="aiBusy" @click="aiSlide('condense')">精简</el-button>
          </div>
        </div>
        <div class="ai-section">
          <div class="ai-sec-title">生成可视化</div>
          <div class="ai-btns">
            <el-button size="small" :loading="aiBusy" @click="aiVisual('chart')">图表</el-button>
            <el-button size="small" :loading="aiBusy" @click="aiVisual('timeline')">时间轴</el-button>
            <el-button size="small" :loading="aiBusy" @click="aiVisual('process')">流程图</el-button>
            <el-button size="small" :loading="aiBusy" @click="aiVisual('data')">数据卡片</el-button>
          </div>
        </div>
        <div class="ai-section">
          <div class="ai-sec-title">页面结构</div>
          <div class="ai-btns">
            <el-button size="small" :loading="aiBusy" @click="aiStructure('add')">AI 增加一页</el-button>
            <el-button size="small" :loading="aiBusy" @click="aiStructure('split')">拆分本页</el-button>
            <el-button size="small" :loading="aiBusy" @click="aiStructure('merge')">合并到上页</el-button>
          </div>
        </div>
        <div class="ai-section">
          <div class="ai-sec-title">自定义指令</div>
          <el-input v-model="aiInstruction" type="textarea" :rows="3"
                    placeholder="如：把这一页改成突出数据和成效" />
          <el-button size="small" type="primary" style="margin-top:8px;width:100%"
                     :loading="aiBusy" @click="aiSlide('custom')">执行</el-button>
        </div>
        <div class="ai-log">
          <div v-for="(l, i) in aiLog" :key="i" class="ai-log-item" :class="{ err: !l.ok }">{{ l.text }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Download, Plus, Delete, CopyDocument, Top, Bottom } from '@element-plus/icons-vue'
import axios from 'axios'
// 项目统一请求：直接基于 axios，自动带 token
const request = axios.create({ baseURL: '/api/v1' })
request.interceptors.request.use(cfg => {
  const t = localStorage.getItem('token')
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

const route = useRoute()
const router = useRouter()
const docId = route.params.id

const doc = ref({ title: '', subtitle: '', template_id: null })
const slides = ref([])
const tpl = ref({ colors: { primary: 'C00000', accent: 'E8B54D', light: 'FDF2F2', dark: '7A0000' },
                  layouts: {}, font: '微软雅黑' })
const cur = ref(0)
const saving = ref(false), exporting = ref(false), aiBusy = ref(false)
const saveState = ref('')
const aiInstruction = ref('')
const aiLog = ref([])
const materials = ref([])
const templates = ref([])

const pageTypes = [
  { value: 'cover', label: '封面' }, { value: 'toc', label: '目录' },
  { value: 'section', label: '章节页' }, { value: 'content', label: '正文' },
  { value: 'data', label: '数据页' }, { value: 'chart', label: '图表页' },
  { value: 'case', label: '案例页' }, { value: 'timeline', label: '时间轴' },
  { value: 'process', label: '流程图' }, { value: 'summary', label: '总结页' },
  { value: 'closing', label: '结束页' },
]
const variantMap = {
  cover: [{ value: 'band_bottom', label: '居中标题+色带' }, { value: 'left_block', label: '左侧色块' }],
  toc: [{ value: 'numbered_list', label: '编号列表' }, { value: 'cards', label: '卡片网格' }],
  section: [{ value: 'left_block', label: '左侧色块' }, { value: 'center', label: '居中大标题' }],
  content: [{ value: 'bar_title', label: '标题侧条' }, { value: 'top_band', label: '顶部色带' },
            { value: 'image_right', label: '右图左文' }],
  closing: [{ value: 'center', label: '居中' }, { value: 'brand_band', label: '品牌色带' }],
}
const layoutVariants = (t) => variantMap[t] || []
const typeLabel = (t) => (pageTypes.find(p => p.value === t) || {}).label || t
const current = computed(() => slides.value[cur.value] || null)
const officialTemplates = computed(() => templates.value.filter(t => t.is_official))
const myTemplates = computed(() => templates.value.filter(t => !t.is_official && t.is_mine))

const hasChart = computed(() => {
  const c = current.value && current.value.blocks && current.value.blocks.chart
  return !!(c && c.categories && c.categories.length && c.series && c.series.length)
})
const chartMax = computed(() => {
  if (!hasChart.value) return 1
  const vals = current.value.blocks.chart.series.flatMap(s => (s.values || []).map(Number))
  return Math.max(...vals, 1)
})
const barHeight = (v) => (Number(v) / chartMax.value * 120) + 'px'
const thumbStyle = (s) => {
  if (['cover', 'closing', 'section'].includes(s.type))
    return { background: 'linear-gradient(135deg, #' + tpl.value.colors.primary + ', #' + tpl.value.colors.dark + ')', color: '#fff' }
  return { background: '#fff', color: '#' + tpl.value.colors.dark }
}
const headStyle = computed(() => {
  if ((tpl.value.layouts.content || 'bar_title') === 'top_band')
    return { background: '#' + tpl.value.colors.primary }
  return {}
})
const headTextStyle = computed(() => {
  if ((tpl.value.layouts.content || 'bar_title') === 'top_band')
    return { color: '#fff' }
  return {}
})

/* ---------- 加载 ---------- */
const load = async () => {
  const [d, m, t] = await Promise.all([
    request.get(`/ppt/documents/${docId}`),
    request.get('/ppt/materials'),
    request.get('/ppt/templates', { params: { scope: 'all' } }),
  ])
  doc.value = { title: d.data.title, subtitle: d.data.subtitle, template_id: d.data.template_id }
  slides.value = (d.data.outline && d.data.outline.slides) || []
  if (d.data.template) tpl.value = d.data.template
  materials.value = m.data.items
  templates.value = t.data.items
}

/* ---------- 自动保存 ---------- */
let dirty = false, timer = null
const markDirty = () => { dirty = true; saveState.value = '有未保存修改' }
const saveNow = async () => {
  saving.value = true
  try {
    await request.put(`/ppt/documents/${docId}/draft`, {
      title: doc.value.title,
      outline: { title: doc.value.title, subtitle: doc.value.subtitle || '', slides: slides.value },
      template_id: doc.value.template_id,
    })
    dirty = false
    saveState.value = '已自动保存 ' + new Date().toLocaleTimeString('zh-CN', { hour12: false })
  } finally { saving.value = false }
}
const switchTemplate = async (tid) => {
  const t = templates.value.find(x => x.id === tid)
  if (t) tpl.value = { colors: t.colors, layouts: t.layouts || {}, font: t.font || '微软雅黑' }
  markDirty()
  await saveNow()
  ElMessage.success('已切换模板，内容保持不变')
}

/* ---------- 页面操作 ---------- */
const addSlide = () => {
  slides.value.splice(slides.value.length - 1, 0, {
    id: Math.random().toString(36).slice(2, 10), type: 'content', layout: null,
    title: '', subtitle: '', points: [''], blocks: {}, image_name: null, image_hint: '', note: '' })
  cur.value = slides.value.length - 2
  markDirty()
}
const dupSlide = () => {
  const c = JSON.parse(JSON.stringify(current.value))
  c.id = Math.random().toString(36).slice(2, 10)
  slides.value.splice(cur.value + 1, 0, c)
  cur.value += 1
  markDirty()
}
const delSlide = async () => {
  await ElMessageBox.confirm('确定删除本页？', '提示', { type: 'warning' })
  slides.value.splice(cur.value, 1)
  cur.value = Math.max(0, Math.min(cur.value, slides.value.length - 1))
  markDirty()
}
const moveSlide = (d) => {
  const i = cur.value, j = i + d
  const [s] = slides.value.splice(i, 1)
  slides.value.splice(j, 0, s)
  cur.value = j
  markDirty()
}
const onTypeChange = () => {
  const s = current.value
  if (!s.blocks) s.blocks = {}
  if (s.type === 'data' && !s.blocks.cards) s.blocks.cards = [{ label: '指标', value: '0' }]
  markDirty()
}

/* ---------- AI 操作 ---------- */
const log = (text, ok = true) => aiLog.value.unshift({ text, ok })
const errMsg = (e) => (e.response && e.response.data && e.response.data.detail) || e.message || '未知错误'
const aiSlide = async (action) => {
  if (!current.value) return
  aiBusy.value = true
  try {
    const { data } = await request.post('/ppt/ai/slide-action', {
      action, slide: current.value, instruction: aiInstruction.value })
    slides.value[cur.value] = data.slide
    markDirty()
    log('✔ ' + { rewrite: '已重写', expand: '已扩写', condense: '已精简', custom: '已处理' }[action] + `第 ${cur.value + 1} 页`)
  } catch (e) { log('✘ AI 处理失败：' + errMsg(e), false) }
  finally { aiBusy.value = false }
}
const aiVisual = async (kind) => {
  aiBusy.value = true
  try {
    const { data } = await request.post('/ppt/ai/visual', {
      kind, slide: current.value, instruction: aiInstruction.value })
    slides.value[cur.value] = Object.assign({}, current.value, data.slide)
    markDirty()
    log('✔ 已生成' + { chart: '图表', timeline: '时间轴', process: '流程图', data: '数据卡片' }[kind])
  } catch (e) { log('✘ 生成失败：' + errMsg(e), false) }
  finally { aiBusy.value = false }
}
const aiStructure = async (action) => {
  aiBusy.value = true
  try {
    const { data } = await request.post('/ppt/ai/structure', {
      action, slides: slides.value, index: cur.value, instruction: aiInstruction.value })
    slides.value = data.slides
    markDirty()
    log('✔ ' + { add: '已新增一页', split: '已拆分本页', merge: '已合并页面' }[action])
  } catch (e) { log('✘ 操作失败：' + errMsg(e), false) }
  finally { aiBusy.value = false }
}

/* ---------- 导出 / 返回 ---------- */
const exportPptx = async () => {
  await saveNow()
  exporting.value = true
  try {
    const res = await request.post(`/ppt/documents/${docId}/export`, null, { responseType: 'blob' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(res.data)
    a.download = `${doc.value.title || 'PPT'}.pptx`
    a.click()
    URL.revokeObjectURL(a.href)
    ElMessage.success('已导出可编辑 PPTX')
  } catch (e) { ElMessage.error('导出失败：' + errMsg(e)) }
  finally { exporting.value = false }
}
const goBack = async () => { await saveNow(); router.push('/ppt') }

onMounted(async () => {
  await load()
  timer = setInterval(() => { if (dirty) saveNow() }, 10000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<style scoped>
.editor { height: 100vh; display: flex; flex-direction: column; background: #f0f2f7; }
.topbar { display: flex; align-items: center; gap: 12px; padding: 10px 18px;
  background: #fff; border-bottom: 1px solid #e8ecf3; flex-shrink: 0;
  box-shadow: 0 1px 4px rgba(30,50,100,.05); z-index: 2; }
.title-input { width: 280px; }
.save-state { font-size: 12px; color: #909399; margin-left: auto; }
.editor-body { flex: 1; display: flex; overflow: hidden; }

/* 左栏 */
.thumb-pane { width: 200px; background: #fff; border-right: 1px solid #e8ecf3;
  overflow-y: auto; padding: 10px; flex-shrink: 0; }
.thumb-head { display: flex; justify-content: space-between; align-items: center;
  font-size: 13px; color: #606266; margin-bottom: 10px; font-weight: 600; }
.thumb { display: flex; align-items: center; gap: 7px; padding: 6px; border-radius: 8px;
  cursor: pointer; border: 1.5px solid transparent; margin-bottom: 5px; transition: all .15s; }
.thumb:hover { background: #f5f7fc; }
.thumb.active { border-color: #4a7ff7; background: #f0f5ff; }
.thumb-no { font-size: 11px; color: #909399; width: 14px; text-align: center; flex-shrink: 0; }
.thumb-mini { flex: 1; height: 52px; border: 1px solid #e8ecf3; border-radius: 5px;
  display: flex; align-items: center; justify-content: center; overflow: hidden; }
.thumb-title { font-size: 10px; padding: 2px 5px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; max-width: 90px; }
.thumb-type { font-size: 10px; color: #909399; width: 28px; flex-shrink: 0;
  white-space: nowrap; }
.thumb-ops { padding: 10px 0; display: flex; gap: 5px; flex-wrap: wrap; }

/* 中栏 */
.canvas-pane { flex: 1; display: flex; flex-direction: column; padding: 20px; overflow: auto; }
.canvas { flex: 1; max-width: 900px; width: 100%; margin: 0 auto; background: #fff;
  border-radius: 12px; box-shadow: 0 4px 18px rgba(30,50,100,.09); position: relative;
  display: flex; flex-direction: column; overflow: hidden; min-height: 500px; }
.cv-full { flex: 1; display: flex; flex-direction: column; justify-content: center; padding: 50px 70px; }
.cv-band { height: 5px; width: 64px; margin-bottom: 24px; border-radius: 3px; }
.cv-title { background: transparent; border: none; outline: none; color: #fff;
  font-size: 32px; font-weight: 700; width: 100%; }
.cv-title::placeholder { color: rgba(255,255,255,.5); }
.cv-sub { background: transparent; border: none; outline: none; color: rgba(255,255,255,.8);
  font-size: 16px; margin-top: 16px; width: 100%; }
.cv-sub::placeholder { color: rgba(255,255,255,.5); }
.pg-head { display: flex; align-items: center; gap: 10px; padding: 20px 30px 12px;
  border-bottom: 1px solid #eef1f6; }
.pg-bar { width: 6px; height: 28px; border-radius: 3px; flex-shrink: 0; }
.pg-title { flex: 1; border: none; outline: none; font-size: 22px; font-weight: 700;
  color: #303133; background: transparent; }
.pg-body { flex: 1; padding: 22px 34px; overflow: auto; }
.pg-note { padding: 10px 30px; border-top: 1px dashed #e8ecf3; }

/* 要点列表（直接写在模板里，样式生效） */
.pt-list { display: flex; flex-direction: column; gap: 10px; }
.pt-row { display: flex; align-items: center; gap: 10px; }
.pt-dot { width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; }
.row-del { cursor: pointer; color: #c0c4cc; padding: 0 6px; font-size: 16px; flex-shrink: 0;
  line-height: 1; }
.row-del:hover { color: #e05555; }
.pt-add { font-size: 13px; color: #4a7ff7; cursor: pointer; margin-top: 2px; }
.pt-add:hover { text-decoration: underline; }

/* 目录 */
.toc-row { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.toc-no { width: 30px; height: 30px; border-radius: 7px; color: #fff; display: flex;
  align-items: center; justify-content: center; font-weight: 700; flex-shrink: 0; }

/* 数据卡片 */
.data-cards { display: flex; gap: 14px; margin-bottom: 18px; }
.data-card { flex: 1; border-radius: 10px; padding: 16px 8px; text-align: center;
  border-top: 3px solid; }
.dc-value { border: none; outline: none; background: transparent; font-size: 24px;
  font-weight: 700; text-align: center; width: 100%; }
.dc-label { border: none; outline: none; background: transparent; text-align: center;
  color: #909399; width: 100%; margin-top: 6px; font-size: 13px; }

/* 图表 */
.chart-box { display: flex; align-items: flex-end; gap: 18px; height: 170px;
  padding: 10px 20px; border: 1px solid #eef1f6; border-radius: 10px; margin-bottom: 8px; }
.chart-empty { padding: 30px; text-align: center; color: #909399; border: 1px dashed #ddd;
  border-radius: 10px; margin-bottom: 8px; }
.chart-tip { font-size: 12px; color: #909399; margin-bottom: 10px; }
.bar-col { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 6px; }
.bar-group { display: flex; align-items: flex-end; gap: 4px; height: 120px; }
.bar { width: 22px; border-radius: 3px 3px 0 0; }
.bar-cat { font-size: 12px; color: #606266; }

/* 时间轴 / 流程 */
.tl-line { height: 3px; border-radius: 2px; margin: 26px 20px 0; }
.tl-row { display: flex; gap: 10px; margin-top: -6px; }
.tl-item { flex: 1; text-align: center; }
.tl-dot { display: block; width: 12px; height: 12px; border-radius: 50%; margin: 0 auto 8px; }
.tl-time { border: none; outline: none; background: transparent; font-weight: 700;
  text-align: center; width: 100%; font-size: 14px; margin-bottom: 4px; }
.pc-row { display: flex; gap: 6px; margin-top: 10px; }
.pc-step { flex: 1; padding: 14px 4px;
  clip-path: polygon(0 0, 90% 0, 100% 50%, 90% 100%, 0 100%, 10% 50%); }
.pc-step:first-child { clip-path: polygon(0 0, 90% 0, 100% 50%, 90% 100%, 0 100%); }
.pc-input { border: none; outline: none; background: transparent; color: #fff;
  font-size: 12px; text-align: center; width: 100%; }
.img-hint { margin-top: 12px; font-size: 12px; color: #67c23a; }

.page-toolbar { display: flex; align-items: center; gap: 8px; max-width: 900px;
  width: 100%; margin: 14px auto 0; }
.muted { font-size: 12px; color: #909399; }

/* 右栏 */
.ai-pane { width: 250px; background: #fff; border-left: 1px solid #e8ecf3;
  overflow-y: auto; padding: 16px; flex-shrink: 0; }
.ai-head { font-weight: 700; margin-bottom: 14px; }
.ai-section { margin-bottom: 18px; }
.ai-sec-title { font-size: 12px; color: #909399; margin-bottom: 8px; }
.ai-btns { display: flex; flex-wrap: wrap; gap: 6px; }
.ai-log { border-top: 1px solid #f0f2f6; padding-top: 10px; }
.ai-log-item { font-size: 12px; color: #67c23a; margin-bottom: 4px; }
.ai-log-item.err { color: #f56c6c; }
</style>