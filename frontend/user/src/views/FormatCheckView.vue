<template>
  <div class="fc-page">
    <!-- 顶部 -->
    <div class="fc-header">
      <div>
        <div class="fc-title"><el-icon color="#409eff"><DocumentChecked /></el-icon>格式校验</div>
        <div class="fc-sub">依据司法局公文格式规范，检测文档格式问题并提供修改建议</div>
      </div>
      <div class="fc-header-actions">
        <el-button @click="historyVisible = true"><el-icon><Clock /></el-icon>校验历史</el-button>
        <el-upload :show-file-list="false" :auto-upload="false" accept=".docx,.txt,.md,.pdf" :on-change="onFileChange">
          <el-button type="primary" :loading="checking"><el-icon><Upload /></el-icon>上传文档</el-button>
        </el-upload>
      </div>
    </div>

    <!-- 文件信息卡 -->
    <div v-if="currentRecordId" class="file-card">
      <div class="file-icon">W</div>
      <div class="file-info">
        <div class="file-name">{{ fileInfo.name }}</div>
        <div class="file-meta">大小：{{ fileInfo.size }}　上传时间：{{ fileInfo.time }}</div>
      </div>
      <div class="file-status">
        <el-icon color="#67c23a" :size="18"><CircleCheckFilled /></el-icon>
        <span class="ok-text">校验完成</span>
        <span class="issue-count">共发现 <b>{{ issues.length }}</b> 个问题</span>
      </div>
    </div>
    <el-empty v-if="!currentRecordId && !checking" description="点击右上角「上传文档」开始格式校验（建议 .docx）" />

    <template v-if="currentRecordId">
      <el-tabs v-model="tab" class="fc-tabs">
        <!-- ============ 校验结果 ============ -->
        <el-tab-pane label="校验结果" name="result">
          <div class="result-layout">
            <div class="result-main">
              <!-- 统计卡 -->
              <div class="stat-row">
                <div class="stat-card"><div class="stat-label">问题总数</div><div class="stat-num">{{ issues.length }}</div></div>
                <div class="stat-card"><div class="stat-label">严重问题</div><div class="stat-num red">{{ statError }}</div></div>
                <div class="stat-card"><div class="stat-label">一般问题</div><div class="stat-num orange">{{ statWarn }}</div></div>
                <div class="stat-card"><div class="stat-label">提示信息</div><div class="stat-num blue">{{ statInfo }}</div></div>
                <div class="stat-card donut-card">
                  <div class="stat-label">问题类型分布</div>
                  <div class="donut-row">
                    <div class="donut" :style="donutStyle"></div>
                    <div class="donut-legend">
                      <div v-for="(g, k) in typeGroups" :key="k">
                        <span class="dot" :style="{ background: TYPE_COLORS[k] }"></span>
                        {{ k }}　{{ g.length }} ({{ pct(g.length) }})
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 筛选 -->
              <div class="filter-row">
                <span>问题类型：</span>
                <el-select v-model="filterType" style="width: 120px"><el-option v-for="t in ['全部', ...Object.keys(TYPE_COLORS)]" :key="t" :label="t" :value="t" /></el-select>
                <span>严重程度：</span>
                <el-select v-model="filterSeverity" style="width: 120px"><el-option v-for="t in ['全部', '严重', '一般', '提示']" :key="t" :label="t" :value="t" /></el-select>
                <span>来源：</span>
                <el-select v-model="filterSource" style="width: 120px"><el-option v-for="t in ['全部', '规则校验', 'AI辅助']" :key="t" :label="t" :value="t" /></el-select>
                <el-input v-model="filterKeyword" placeholder="搜索问题内容" clearable style="width: 220px" />
                <el-button>筛选</el-button>
              </div>

              <!-- 问题表格 -->
              <el-table :data="pagedIssues" style="width: 100%" @row-click="row => selectIssue(row._idx)">
                <el-table-column type="index" label="序号" width="60" :index="i => (page - 1) * pageSize + i + 1" />
                <el-table-column prop="element" label="问题内容" min-width="180" show-overflow-tooltip />
                <el-table-column prop="location" label="位置" width="110" show-overflow-tooltip />
                <el-table-column prop="current" label="当前值" width="130" show-overflow-tooltip />
                <el-table-column prop="expected" label="标准要求" width="150" show-overflow-tooltip />
                <el-table-column label="严重程度" width="90">
                  <template #default="{ row }">
                    <el-tag size="small" :type="severityTag(row)" effect="plain">{{ severityText(row) }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="来源" width="90">
                  <template #default="{ row }">{{ row.source === 'ai' ? 'AI辅助' : '规则校验' }}</template>
                </el-table-column>
                <el-table-column label="操作" width="110">
                  <template #default="{ row }">
                    <el-button size="small" text type="primary" @click.stop="selectIssue(row._idx)"><el-icon><View /></el-icon></el-button>
                    <el-button v-if="row.fix_hint" size="small" text
                      :type="acceptedSet.has(row._idx) ? 'success' : 'info'"
                      @click.stop="toggleAccept(row._idx)">
                      {{ acceptedSet.has(row._idx) ? '已选' : '选择' }}
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
              <div class="pager">
                <span>共 {{ filteredIssues.length }} 条</span>
                <el-pagination layout="prev, pager, next, sizes, jumper" :total="filteredIssues.length"
                  v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[10, 20, 50]" />
              </div>
              <div class="tip-row">提示：点击 <el-icon><View /></el-icon> 查看问题详情，勾选问题后可进行自动修正预览</div>

              <!-- 底部操作条 -->
              <div class="bottom-bar">
                <span>已选 <b class="red">{{ acceptedSet.size }}</b> 项</span>
                <el-button text type="primary" @click="rejectAll">清空选择</el-button>
                <el-button @click="acceptAll">全选可修正项</el-button>
                <el-button type="primary" plain @click="goPreview">预览修正</el-button>
                <el-button type="primary" :loading="downloading" @click="onDownload">生成修正稿</el-button>
              </div>
            </div>

            <!-- 右栏：问题详情 + 文档预览 -->
            <div class="result-side">
              <div class="side-box" v-if="activeIssueObj">
                <div class="side-head">
                  <span>问题详情</span>
                  <span class="side-nav">
                    {{ activeIssue + 1 }} / {{ issues.length }}
                    <el-button size="small" text @click="stepIssue(-1)"><el-icon><ArrowLeft /></el-icon></el-button>
                    <el-button size="small" text @click="stepIssue(1)"><el-icon><ArrowRight /></el-icon></el-button>
                  </span>
                </div>
                <div class="detail-body">
                  <div class="detail-title">
                    {{ activeIssueObj.element || '格式问题' }}
                    <el-tag size="small" :type="severityTag(activeIssueObj)" effect="dark">{{ severityText(activeIssueObj) }}</el-tag>
                  </div>
                  <div class="detail-row"><span class="lbl">位置：</span>{{ activeIssueObj.location }}</div>
                  <div class="detail-row"><span class="lbl">当前值：</span>{{ activeIssueObj.current }}</div>
                  <div class="detail-row"><span class="lbl">标准要求：</span>{{ activeIssueObj.expected }}</div>
                  <div class="detail-row"><span class="lbl">建议：</span>{{ activeIssueObj.suggestion }}</div>
                  <div class="detail-row"><span class="lbl">来源：</span>{{ activeIssueObj.source === 'ai' ? 'AI 辅助' : '规则校验' }}</div>
                </div>
              </div>

              <div class="side-box">
                <div class="side-head">
                  <span>文档预览</span>
                  <span class="side-nav">
                    高亮问题 <el-switch v-model="highlightOn" size="small" />
                  </span>
                </div>
                <div class="doc-preview">
                  <div class="doc-page">
                    <div v-for="p in sourceParagraphs" :key="p.index" class="doc-para"
                      :class="{ 'doc-hl': highlightOn && activeIssueObj && activeIssueObj.paragraph_index === p.index }">
                      {{ p.text || '　' }}
                      <span v-if="highlightOn && paraIssueMap[p.index]" class="hl-badge">{{ paraIssueMap[p.index].length }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <!-- ============ 逐段审阅（一一对应拉线） ============ -->
        <el-tab-pane label="逐段审阅" name="review">
          <el-alert v-if="!canReview" type="info" :closable="false" title="仅 .docx 文件支持逐段审阅" />
          <div v-else class="review-wrap" ref="reviewWrap">
            <div class="pane">
              <div class="pane-title">源文档</div>
              <div class="pane-body" @scroll="drawLines">
                <div v-for="p in sourceParagraphs" :key="'l' + p.index" :id="'lp-' + p.index"
                  class="para" :class="paraClass(p.index, 'left')" @click="onParaClick(p.index)">
                  {{ p.text || '　' }}
                </div>
              </div>
            </div>
            <svg class="lines-layer" ref="linesSvg"></svg>
            <div class="pane">
              <div class="pane-title">修正稿（按已接受的修正实时预览）</div>
              <div class="pane-body" v-loading="previewing" @scroll="drawLines">
                <div v-for="p in fixedParagraphs" :key="'r' + p.index" :id="'rp-' + p.index"
                  class="para" :class="paraClass(p.index, 'right')" @click="onParaClick(p.index)">
                  {{ p.text || '　' }}
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <!-- ============ 修正预览 ============ -->
        <el-tab-pane label="修正预览" name="preview">
          <el-alert v-if="!canReview" type="info" :closable="false" title="仅 .docx 文件支持修正预览" />
          <div v-else class="preview-page" v-loading="previewing">
            <div class="preview-head">
              已应用 <b>{{ acceptedSet.size }}</b> 项修正
              <el-button size="small" text type="primary" @click="refreshPreviewNow">刷新预览</el-button>
            </div>
            <div class="doc-page">
              <div v-for="p in fixedParagraphs" :key="'pv' + p.index" class="doc-para"
                :class="{ 'doc-fixed': fixedSet.has(p.index) }">
                {{ p.text || '　' }}
              </div>
            </div>
          </div>
        </el-tab-pane>

        <!-- ============ 修正结果 ============ -->
        <el-tab-pane label="修正结果" name="fixed">
          <div class="fixed-result">
            <el-result icon="success" title="修正稿已就绪"
              :sub-title="`已接受 ${acceptedSet.size} 项修正，点击下方按钮下载 Word 修正稿`">
              <template #extra>
                <el-button type="primary" size="large" :loading="downloading" @click="onDownload">
                  <el-icon><Download /></el-icon>下载修正稿
                </el-button>
                <el-button size="large" @click="tab = 'review'">返回逐段审阅调整</el-button>
              </template>
            </el-result>
          </div>
        </el-tab-pane>
      </el-tabs>
    </template>

    <!-- 校验历史抽屉 -->
    <el-drawer v-model="historyVisible" title="校验历史" size="420px">
      <div v-for="r in records" :key="r.id" class="history-item" @click="onRecordChange(r.id); historyVisible = false">
        <div class="history-name">{{ r.filename }}</div>
        <div class="history-meta">
          {{ (r.created_at || '').slice(0, 16).replace('T', ' ') }}　{{ r.issue_count }} 个问题
          <el-tag size="small" effect="plain">{{ r.file_type }}</el-tag>
        </div>
      </div>
      <el-empty v-if="!records.length" description="暂无历史记录" />
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  DocumentChecked, Clock, Upload, Download, View,
  CircleCheckFilled, ArrowLeft, ArrowRight,
} from '@element-plus/icons-vue'
import {
  checkFormat, listCheckRecords, getCheckRecord,
  getRecordParagraphs, previewFix, downloadFixed,
} from '@/api/format_check.js'

// ---------- 状态 ----------
const checking = ref(false)
const downloading = ref(false)
const previewing = ref(false)
const historyVisible = ref(false)
const records = ref([])
const currentRecordId = ref(null)
const currentFileType = ref('')
const fileInfo = ref({ name: '', size: '', time: '' })
const issues = ref([])
const sourceParagraphs = ref([])
const fixedParagraphs = ref([])
const acceptedSet = reactive(new Set())
const fixedSet = reactive(new Set())       // 修正预览里被改过的段落下标
const activeIssue = ref(0)
const paraIssueMap = reactive({})
const tab = ref('result')
const highlightOn = ref(true)

const page = ref(1)
const pageSize = ref(10)
const filterType = ref('全部')
const filterSeverity = ref('全部')
const filterSource = ref('全部')
const filterKeyword = ref('')

const TYPE_COLORS = { '字体字号': '#409eff', '段落格式': '#67c23a', '页面设置': '#e6a23c', '其他规范': '#f56c6c' }
const TYPE_KEYS = {
  '字体字号': ['字体', '字号', '加粗'],
  '段落格式': ['对齐方式', '行距', '首行缩进', '段前间距', '段后间距', '多余空行', '行尾空格'],
  '页面设置': ['上边距', '下边距', '左边距', '右边距', '页面宽度', '页面高度'],
}

const reviewWrap = ref(null)
const linesSvg = ref(null)

// ---------- 计算 ----------
const canReview = computed(() => currentFileType.value === 'docx' && sourceParagraphs.value.length > 0)
const activeIssueObj = computed(() => issues.value[activeIssue.value] || null)

function issueType(iss) {
  for (const [k, names] of Object.entries(TYPE_KEYS)) {
    if (names.includes(iss.element)) return k
  }
  return '其他规范'
}
const typeGroups = computed(() => {
  const g = { '字体字号': [], '段落格式': [], '页面设置': [], '其他规范': [] }
  issues.value.forEach(i => g[issueType(i)].push(i))
  return g
})
const donutStyle = computed(() => {
  const total = issues.value.length || 1
  let acc = 0
  const stops = []
  for (const [k, color] of Object.entries(TYPE_COLORS)) {
    const n = typeGroups.value[k]?.length || 0
    const from = acc / total * 100
    acc += n
    const to = acc / total * 100
    if (n) stops.push(`${color} ${from}% ${to}%`)
  }
  return { background: `conic-gradient(${stops.join(',') || '#e4e7ed 0 100%'})` }
})
function pct(n) { return issues.value.length ? Math.round(n / issues.value.length * 100) + '%' : '0%' }

function severityText(iss) {
  if (iss.source === 'ai') return '提示'
  return iss.severity === 'error' ? '严重' : '一般'
}
function severityTag(iss) {
  return { '严重': 'danger', '一般': 'warning', '提示': 'primary' }[severityText(iss)]
}
const statError = computed(() => issues.value.filter(i => severityText(i) === '严重').length)
const statWarn = computed(() => issues.value.filter(i => severityText(i) === '一般').length)
const statInfo = computed(() => issues.value.filter(i => severityText(i) === '提示').length)

const filteredIssues = computed(() =>
  issues.value
    .map((iss, i) => ({ ...iss, _idx: i }))
    .filter(iss =>
      (filterType.value === '全部' || issueType(iss) === filterType.value) &&
      (filterSeverity.value === '全部' || severityText(iss) === filterSeverity.value) &&
      (filterSource.value === '全部' || (filterSource.value === 'AI辅助' ? iss.source === 'ai' : iss.source !== 'ai')) &&
      (!filterKeyword.value || `${iss.element}${iss.current}${iss.expected}${iss.suggestion}`.includes(filterKeyword.value))
    ))
const pagedIssues = computed(() =>
  filteredIssues.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))

// ---------- 数据加载 ----------
async function loadRecords() {
  try {
    const { data } = await listCheckRecords({ page: 1, page_size: 50 })
    records.value = data.data || []
  } catch (e) { /* 静默 */ }
}

async function onFileChange(file) {
  checking.value = true
  try {
    const { data } = await checkFormat(file.raw, true)
    fileInfo.value = {
      name: data.filename,
      size: (file.raw.size / 1024).toFixed(0) + ' KB',
      time: new Date().toLocaleString('zh-CN', { hour12: false }),
    }
    ElMessage.success(`校验完成，发现 ${data.issue_count} 个问题`)
    await loadAfterCheck(data.record_id, data.issues || [], data.file_type)
    loadRecords()
  } catch (e) {
    ElMessage.error('校验失败：' + (e.response?.data?.detail || e.message))
  } finally {
    checking.value = false
  }
}

async function onRecordChange(id) {
  try {
    const { data } = await getCheckRecord(id)
    const rec = records.value.find(r => r.id === id)
    fileInfo.value = {
      name: data.filename, size: '—',
      time: (data.created_at || '').slice(0, 16).replace('T', ' '),
    }
    await loadAfterCheck(id, data.issues || [], data.file_type)
  } catch (e) {
    ElMessage.error('加载记录失败')
  }
}

async function loadAfterCheck(recordId, issueList, fileType) {
  currentRecordId.value = recordId
  currentFileType.value = fileType
  issues.value = issueList
  activeIssue.value = 0
  sourceParagraphs.value = []
  fixedParagraphs.value = []
  acceptedSet.clear()
  fixedSet.clear()
  issueList.forEach((iss, i) => { if (iss.fix_hint) acceptedSet.add(i) })
  rebuildMap()
  tab.value = 'result'
  if (fileType === 'docx') {
    try {
      const { data } = await getRecordParagraphs(recordId)
      sourceParagraphs.value = data.paragraphs || []
      await refreshPreviewNow()
    } catch (e) { /* 源文件过期则退化为纯问题列表 */ }
  }
}

function rebuildMap() {
  Object.keys(paraIssueMap).forEach(k => delete paraIssueMap[k])
  issues.value.forEach((iss, i) => {
    const p = iss.paragraph_index
    if (p === undefined || p === null) return
    if (!paraIssueMap[p]) paraIssueMap[p] = []
    paraIssueMap[p].push(i)
  })
}

// ---------- 选择 / 接受 ----------
function selectIssue(i) {
  activeIssue.value = i
  nextTick(drawLines)
}
function stepIssue(d) {
  activeIssue.value = Math.min(Math.max(activeIssue.value + d, 0), issues.value.length - 1)
  nextTick(drawLines)
}
function toggleAccept(i) {
  if (acceptedSet.has(i)) acceptedSet.delete(i); else acceptedSet.add(i)
  refreshPreview()
}
function acceptAll() {
  issues.value.forEach((iss, i) => { if (iss.fix_hint) acceptedSet.add(i) })
  refreshPreview()
}
function rejectAll() { acceptedSet.clear(); refreshPreview() }

function paraClass(pIdx, side) {
  const list = paraIssueMap[pIdx]
  if (!list) return {}
  return {
    'para-issue': true,
    'para-accepted': side === 'right' && list.some(i => acceptedSet.has(i)),
    'para-active': list.includes(activeIssue.value),
  }
}
function onParaClick(pIdx) {
  const list = paraIssueMap[pIdx]
  if (list && list.length) selectIssue(list[0])
}

// ---------- 修正预览 ----------
let previewTimer = null
function refreshPreview() {
  clearTimeout(previewTimer)
  previewTimer = setTimeout(refreshPreviewNow, 300)
}
async function refreshPreviewNow() {
  if (!currentRecordId.value || currentFileType.value !== 'docx') return
  previewing.value = true
  try {
    const { data } = await previewFix(currentRecordId.value, [...acceptedSet])
    const paras = data.paragraphs || []
    fixedParagraphs.value = paras
    fixedSet.clear()
    paras.forEach(p => {
      const src = sourceParagraphs.value[p.index]
      if (!src || src.text !== p.text) fixedSet.add(p.index)
    })
  } catch (e) {
    ElMessage.error('修正预览失败：' + (e.response?.data?.detail || e.message))
  } finally {
    previewing.value = false
    await nextTick()
    drawLines()
  }
}
function goPreview() { tab.value = 'preview'; refreshPreviewNow() }

// ---------- 逐段审阅连线 ----------
function drawLines() {
  const svg = linesSvg.value, wrap = reviewWrap.value
  if (!svg || !wrap || tab.value !== 'review') return
  const wrapRect = wrap.getBoundingClientRect()
  svg.setAttribute('width', wrapRect.width)
  svg.setAttribute('height', wrapRect.height)
  svg.innerHTML = ''
  issues.value.forEach((iss, i) => {
    const p = iss.paragraph_index
    if (p === undefined || p === null) return
    const l = document.getElementById('lp-' + p)
    const r = document.getElementById('rp-' + p)
    if (!l || !r) return
    const lr = l.getBoundingClientRect(), rr = r.getBoundingClientRect()
    const x1 = lr.right - wrapRect.left, y1 = lr.top - wrapRect.top + lr.height / 2
    const x2 = rr.left - wrapRect.left, y2 = rr.top - wrapRect.top + rr.height / 2
    const mx = (x1 + x2) / 2
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
    path.setAttribute('d', `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`)
    const accepted = acceptedSet.has(i)
    path.setAttribute('fill', 'none')
    path.setAttribute('stroke', activeIssue.value === i ? '#409eff' : accepted ? '#67c23a' : '#e6a23c')
    path.setAttribute('stroke-width', activeIssue.value === i ? 2.5 : 1.5)
    if (!accepted) path.setAttribute('stroke-dasharray', '5,4')
    path.style.cursor = 'pointer'
    path.addEventListener('click', () => toggleAccept(i))
    svg.appendChild(path)
  })
}
watch(tab, v => { if (v === 'review') nextTick(drawLines) })

// ---------- 下载 ----------
async function onDownload() {
  if (!currentRecordId.value) return
  downloading.value = true
  try {
    const { data } = await downloadFixed(currentRecordId.value, [...acceptedSet])
    const url = URL.createObjectURL(data)
    const a = document.createElement('a')
    a.href = url
    a.download = '修正稿.docx'
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('修正稿已下载')
  } catch (e) {
    ElMessage.error('下载失败：' + (e.response?.data?.detail || e.message))
  } finally {
    downloading.value = false
  }
}

const onResize = () => drawLines()
onMounted(() => { loadRecords(); window.addEventListener('resize', onResize) })
onBeforeUnmount(() => window.removeEventListener('resize', onResize))
</script>

<style scoped>
.fc-page { padding: 20px 24px; }
.fc-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.fc-title { font-size: 22px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
.fc-sub { color: #909399; font-size: 13px; margin-top: 4px; }
.fc-header-actions { display: flex; gap: 10px; }

.file-card {
  display: flex; align-items: center; gap: 14px;
  background: #fff; border: 1px solid #ebeef5; border-radius: 10px;
  padding: 14px 18px; margin-bottom: 4px;
}
.file-icon {
  width: 44px; height: 44px; border-radius: 8px; background: #2b579a;
  color: #fff; font-weight: 700; font-size: 20px;
  display: flex; align-items: center; justify-content: center;
}
.file-info { flex: 1; }
.file-name { font-weight: 600; font-size: 15px; }
.file-meta { color: #909399; font-size: 12px; margin-top: 4px; }
.file-status { display: flex; align-items: center; gap: 6px; }
.ok-text { color: #67c23a; font-weight: 600; }
.issue-count { color: #606266; margin-left: 10px; }
.issue-count b { color: #f56c6c; }

.fc-tabs { margin-top: 8px; }

/* 校验结果 */
.result-layout { display: flex; gap: 16px; align-items: flex-start; }
.result-main { flex: 1; min-width: 0; }
.result-side { width: 380px; flex-shrink: 0; display: flex; flex-direction: column; gap: 14px; }

.stat-row { display: flex; gap: 12px; margin-bottom: 14px; }
.stat-card {
  background: #fff; border: 1px solid #ebeef5; border-radius: 10px;
  padding: 14px 18px; min-width: 110px;
}
.stat-label { color: #909399; font-size: 13px; }
.stat-num { font-size: 28px; font-weight: 700; margin-top: 6px; }
.stat-num.red { color: #f56c6c; } .stat-num.orange { color: #e6a23c; } .stat-num.blue { color: #409eff; }
.donut-card { flex: 1; }
.donut-row { display: flex; align-items: center; gap: 16px; margin-top: 8px; }
.donut { width: 76px; height: 76px; border-radius: 50%; position: relative; flex-shrink: 0; }
.donut::after { content: ''; position: absolute; inset: 20px; background: #fff; border-radius: 50%; }
.donut-legend { font-size: 12px; color: #606266; display: flex; flex-direction: column; gap: 3px; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }

.filter-row { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 13px; color: #606266; flex-wrap: wrap; }
.pager { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; color: #909399; font-size: 13px; }
.tip-row { color: #909399; font-size: 12px; margin-top: 8px; }
.bottom-bar {
  display: flex; align-items: center; gap: 14px; justify-content: flex-end;
  background: #fff; border: 1px solid #ebeef5; border-radius: 10px;
  padding: 12px 18px; margin-top: 14px;
}
.red { color: #f56c6c; }

.side-box { background: #fff; border: 1px solid #ebeef5; border-radius: 10px; }
.side-head {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; font-weight: 600; border-bottom: 1px solid #ebeef5;
}
.side-nav { display: flex; align-items: center; gap: 4px; font-weight: 400; color: #909399; font-size: 13px; }
.detail-body { padding: 14px 16px; }
.detail-title { font-size: 15px; font-weight: 600; display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.detail-row { font-size: 13px; color: #303133; line-height: 2; }
.detail-row .lbl { color: #909399; }

.doc-preview { padding: 12px; max-height: 46vh; overflow-y: auto; background: #f5f6f8; }
.doc-page {
  background: #fff; border: 1px solid #e4e7ed; border-radius: 4px;
  padding: 28px 32px; box-shadow: 0 1px 4px rgba(0,0,0,.06);
}
.doc-para { font-size: 14px; line-height: 2.1; min-height: 24px; position: relative; white-space: pre-wrap; word-break: break-all; }
.doc-hl { background: #fde2e2; border-radius: 3px; }
.doc-fixed { background: #e1f3d8; border-radius: 3px; }
.hl-badge {
  position: absolute; right: -6px; top: 2px; background: #f56c6c; color: #fff;
  font-size: 11px; min-width: 16px; height: 16px; line-height: 16px;
  border-radius: 50%; text-align: center;
}

/* 逐段审阅 */
.review-wrap {
  position: relative; display: flex; gap: 64px;
  border: 1px solid #e4e7ed; border-radius: 8px; background: #fafafa; padding: 0 12px;
}
.pane { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.pane-title { padding: 10px 4px; font-weight: 600; font-size: 14px; border-bottom: 1px solid #ebeef5; }
.pane-body { overflow-y: auto; padding: 12px 4px; max-height: 60vh; background: #fff; }
.para {
  padding: 4px 8px; margin: 2px 0; border-radius: 4px;
  font-size: 14px; line-height: 1.9; min-height: 28px;
  white-space: pre-wrap; word-break: break-all;
  border-left: 3px solid transparent;
}
.para-issue { border-left-color: #e6a23c; background: #fdf6ec; cursor: pointer; }
.para-accepted { border-left-color: #67c23a; background: #f0f9eb; }
.para-active { outline: 2px solid #409eff; }
.lines-layer { position: absolute; inset: 0; pointer-events: none; }
.lines-layer path { pointer-events: stroke; }

/* 修正预览 */
.preview-page { background: #f5f6f8; border-radius: 8px; padding: 16px; }
.preview-head { margin-bottom: 12px; color: #606266; }
.preview-head b { color: #67c23a; }
.preview-page .doc-page { max-height: 62vh; overflow-y: auto; }

/* 修正结果 */
.fixed-result { background: #fff; border: 1px solid #ebeef5; border-radius: 10px; padding: 30px 0; }

/* 历史 */
.history-item {
  padding: 12px 6px; border-bottom: 1px solid #f2f3f5; cursor: pointer;
}
.history-item:hover { background: #f5f7fa; }
.history-name { font-weight: 600; font-size: 14px; }
.history-meta { color: #909399; font-size: 12px; margin-top: 4px; display: flex; gap: 8px; align-items: center; }
</style>