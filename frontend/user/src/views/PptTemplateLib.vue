<template>
  <div class="tpl-lib">
    <!-- 面包屑 -->
    <div class="crumb">
      <span class="crumb-link" @click="$router.push('/ppt')">PPT助手</span>
      <span class="crumb-sep">/</span>
      <span>模板库</span>
    </div>

    <div class="lib-head">
      <el-radio-group v-model="libTab" size="default" @change="onTabChange">
        <el-radio-button value="official">模板库</el-radio-button>
        <el-radio-button value="mine">我的模板</el-radio-button>
      </el-radio-group>
      <div class="head-actions">
        <el-dropdown trigger="click" @command="onUploadCmd">
          <el-button><el-icon><Upload /></el-icon>上传模板</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="pptx">
                <div class="up-item"><el-icon color="#4a7ff7"><Document /></el-icon>
                  <div><b>上传PPT文件</b><p>支持 .pptx 格式，智能解析版式</p></div>
                </div>
              </el-dropdown-item>
              <el-dropdown-item command="local">
                <div class="up-item"><el-icon color="#4a7ff7"><FolderOpened /></el-icon>
                  <div><b>从本地导入</b><p>从电脑选择已有PPT文件导入</p></div>
                </div>
              </el-dropdown-item>
              <el-dropdown-item command="url">
                <div class="up-item"><el-icon color="#4a7ff7"><Link /></el-icon>
                  <div><b>从在线链接导入</b><p>输入PPT在线链接导入</p></div>
                </div>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button type="primary" @click="openEditor()"><el-icon><Plus /></el-icon>新建模板</el-button>
      </div>
    </div>
    <p class="up-note">导入的模板仅保存版式，不包含原始内容</p>

    <div class="lib-body">
      <!-- 左：筛选 + 网格 -->
      <div class="lib-main">
        <el-input v-model="keyword" placeholder="搜索模板名称或关键词" clearable class="lib-search">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>

        <div class="filter-row">
          <span class="filter-label">场景分类：</span>
          <span v-for="c in sceneCats" :key="c" class="chip" :class="{ on: scene === c }"
                @click="scene = c">{{ c }}</span>
        </div>
        <div class="filter-row">
          <span class="filter-label">风格类型：</span>
          <span v-for="s in styleTypes" :key="s" class="chip" :class="{ on: styleType === s }"
                @click="styleType = s">{{ s }}</span>
        </div>
        <div class="filter-row">
          <span class="filter-label">配色风格：</span>
          <span v-for="c in colorFilters" :key="c.key" class="color-dot"
                :class="{ on: colorKey === c.key }" :style="{ background: c.color }"
                :title="c.label" @click="colorKey = colorKey === c.key ? '' : c.key" />
        </div>
        <div class="filter-row">
          <span class="filter-label">排序方式：</span>
          <el-select v-model="sort" size="small" style="width:130px">
            <el-option label="推荐排序" value="rec" />
            <el-option label="最新" value="new" />
            <el-option label="使用最多" value="hot" />
          </el-select>
        </div>

        <div class="grid-title">全部模板<span class="muted">（共{{ filtered.length }}个）</span></div>
        <div v-loading="loading" class="tpl-grid">
          <div v-for="t in paged" :key="t.id" class="tpl-card"
               :class="{ active: current && current.id === t.id }" @click="current = t">
            <div class="tpl-cover" :style="{ background: 'linear-gradient(135deg, #' + t.colors.primary + ' 0%, #' + t.colors.dark + ' 100%)' }">
              <el-tag v-if="t.is_official" size="small" effect="dark" class="tg-official">官方</el-tag>
              <el-icon v-if="current && current.id === t.id" class="tc-check"><CircleCheckFilled /></el-icon>
              <span class="tc-band" :style="{ background: '#' + t.colors.accent }" />
              <span class="tc-title">{{ t.name }}</span>
              <span class="tc-sub">{{ t.category }} · {{ styleOf(t) }}</span>
            </div>
            <div class="tpl-info">
              <div class="ti-name">{{ t.name }}
                <el-icon class="ti-star" :class="{ fav: t.is_favorite }" @click.stop="toggleFav(t)">
                  <StarFilled v-if="t.is_favorite" /><Star v-else />
                </el-icon>
              </div>
              <div class="ti-tags">
                <span class="ti-tag">{{ t.category }}</span>
                <span class="ti-tag">{{ styleOf(t) }}</span>
                <span v-if="t.layout_count" class="ti-tag layout-tag">{{ t.layout_count }} 种版式</span>
              </div>
              <div class="ti-use">{{ t.use_count }} 人使用</div>
            </div>
          </div>
          <el-empty v-if="!loading && !filtered.length" description="暂无模板" :image-size="70" style="grid-column:1/-1" />
        </div>
        <el-pagination v-model:current-page="page" :page-size="pageSize" :total="filtered.length"
                       layout="prev, pager, next, total" class="lib-pager" />
      </div>

      <!-- 右：模板详情 -->
      <div v-if="current" class="lib-detail">
        <div class="d-title">{{ current.name }}
          <el-tag v-if="current.is_official" size="small" type="danger" effect="plain">官方模板</el-tag>
        </div>
        <div class="d-tags">
          <span class="ti-tag">{{ current.category }}</span>
          <span class="ti-tag">{{ styleOf(current) }}</span>
        </div>
        <p class="d-desc">{{ current.description || '适用于' + current.category + '等正式场景。' }}</p>
        <div class="d-meta">
          <span><el-icon><Monitor /></el-icon>16:9</span>
          <span><el-icon><Files /></el-icon>{{ current.layout_count ? current.layout_count + ' 种版式' : '标准版式' }}</span>
          <span><el-icon><Collection /></el-icon>{{ current.is_official ? '官方模板' : '我的模板' }}</span>
          <span><el-icon><User /></el-icon>{{ current.use_count }} 人使用</span>
          <el-button class="d-fav" :type="current.is_favorite ? 'warning' : 'default'" plain
                     size="small" @click="toggleFav(current)">
            <el-icon><StarFilled v-if="current.is_favorite" /><Star v-else /></el-icon>
            {{ current.is_favorite ? '已收藏' : '收藏' }}
          </el-button>
        </div>

        <div class="d-sub">{{ detailLayouts.length ? `模板版式（自动识别 ${detailLayouts.length} 种）` : '模板预览（部分版式）' }}</div>
        <!-- 学习到的版式库：动态展示，不再写死页型 -->
        <div v-if="detailLayouts.length" class="d-preview">
          <div v-for="l in detailLayouts" :key="l.id" class="d-pv-item">
            <img v-if="l.preview_url" :src="l.preview_url" class="pv-img" alt="" />
            <div v-else class="mini" :style="miniBg(miniType(l.detected_type))">
              <span class="m-band" v-if="['cover','section','closing'].includes(miniType(l.detected_type))"
                    :style="{ background: '#' + current.colors.accent }" />
              <span class="m-head" v-else :style="{ background: '#' + current.colors.primary }" />
            </div>
            <span class="d-pv-label">{{ l.name }}</span>
          </div>
        </div>
        <div v-else class="d-preview">
          <div v-for="p in previewPages" :key="p.label" class="d-pv-item">
            <div class="mini" :style="miniBg(p.type)">
              <template v-if="['cover','section','closing'].includes(p.type)">
                <span class="m-band" :style="{ background: '#' + current.colors.accent }" />
                <span class="m-line white" style="width:65%" />
                <span class="m-line white thin" style="width:45%" />
              </template>
              <template v-else-if="p.type === 'toc'">
                <span class="m-head" :style="{ background: '#' + current.colors.primary }" />
                <span v-for="i in 3" :key="i" class="m-row">
                  <i :style="{ background: '#' + current.colors.primary }" /><em />
                </span>
              </template>
              <template v-else-if="p.type === 'content_image'">
                <span class="m-head" :style="{ background: '#' + current.colors.primary }" />
                <div class="m-cols">
                  <div class="m-col"><span v-for="i in 3" :key="i" class="m-line thin" /></div>
                  <div class="m-img" :style="{ background: '#' + current.colors.light, borderColor: '#' + current.colors.accent }" />
                </div>
              </template>
              <template v-else-if="p.type === 'chart'">
                <span class="m-head" :style="{ background: '#' + current.colors.primary }" />
                <div class="m-chart">
                  <i v-for="(h, i) in [40, 70, 55, 85]" :key="i"
                     :style="{ height: h + '%', background: i % 2 ? '#' + current.colors.accent : '#' + current.colors.primary }" />
                </div>
              </template>
              <template v-else-if="p.type === 'two_col'">
                <span class="m-head" :style="{ background: '#' + current.colors.primary }" />
                <div class="m-cols">
                  <div class="m-col"><span v-for="i in 2" :key="i" class="m-line thin" /></div>
                  <div class="m-col"><span v-for="i in 2" :key="i" class="m-line thin" /></div>
                </div>
              </template>
              <template v-else-if="p.type === 'data'">
                <span class="m-head" :style="{ background: '#' + current.colors.primary }" />
                <div class="m-cards">
                  <b v-for="i in 3" :key="i" :style="{ background: '#' + current.colors.light }">
                    <i :style="{ background: '#' + current.colors.primary }" />
                  </b>
                </div>
              </template>
              <template v-else-if="p.type === 'case'">
                <span class="m-head" :style="{ background: '#' + current.colors.primary }" />
                <div class="m-cols">
                  <div class="m-img" :style="{ background: '#' + current.colors.light, borderColor: '#' + current.colors.accent }" />
                  <div class="m-col"><span v-for="i in 3" :key="i" class="m-line thin" /></div>
                </div>
              </template>
            </div>
            <span class="d-pv-label">{{ p.label }}</span>
          </div>
        </div>

        <div class="d-actions">
          <el-button @click="previewVisible = true"><el-icon><View /></el-icon>预览完整模板</el-button>
          <el-button type="primary" @click="useTemplate"><el-icon><MagicStick /></el-icon>使用此模板</el-button>
          <el-dropdown trigger="click" @command="onMoreCmd">
            <el-button>更多<el-icon><ArrowDown /></el-icon></el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="copy">复制模板</el-dropdown-item>
                <el-dropdown-item command="edit" :disabled="current.is_official">编辑模板（仅个人）</el-dropdown-item>
                <el-dropdown-item command="delete" :disabled="current.is_official" divided>删除模板（仅个人）</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </div>

    <!-- 完整预览 -->
    <el-dialog v-model="previewVisible" :title="current ? current.name : ''" width="860px">
      <div v-if="current && detailLayouts.length" class="full-preview">
        <div v-for="l in detailLayouts" :key="l.id" class="fp-item">
          <img v-if="l.preview_url" :src="l.preview_url" class="fp-img" alt="" />
          <div v-else class="mini big" :style="miniBg(miniType(l.detected_type))">
            <span class="m-band" v-if="['cover','section','closing'].includes(miniType(l.detected_type))"
                  :style="{ background: '#' + current.colors.accent }" />
            <span class="m-head" v-else :style="{ background: '#' + current.colors.primary }" />
          </div>
          <span class="d-pv-label">{{ l.name }}</span>
        </div>
      </div>
      <div v-else-if="current" class="full-preview">
        <div v-for="p in previewPages" :key="p.label" class="fp-item">
          <div class="mini big" :style="miniBg(p.type)">
            <span class="m-band" v-if="['cover','section','closing'].includes(p.type)"
                  :style="{ background: '#' + current.colors.accent }" />
            <span class="m-head" v-else :style="{ background: '#' + current.colors.primary }" />
          </div>
          <span class="d-pv-label">{{ p.label }}</span>
        </div>
      </div>
    </el-dialog>

    <!-- 上传 pptx -->
    <el-dialog v-model="uploadVisible" title="上传 PPT 模板" width="480px" destroy-on-close>
      <el-form label-width="90px">
        <el-form-item label="模板文件">
          <el-upload :auto-upload="false" :limit="1" accept=".pptx" :on-change="onTplPicked" :file-list="tplFiles">
            <el-button><el-icon><Upload /></el-icon>选择 .pptx</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item label="模板名称"><el-input v-model="uploadForm.name" /></el-form-item>
        <el-form-item label="分类">
          <el-select v-model="uploadForm.category" style="width:100%">
            <el-option v-for="c in sceneCats.slice(1)" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="dlg-footer">
        <el-button type="primary" :loading="busy" @click="submitUpload">上传</el-button>
      </div>
    </el-dialog>

    <!-- 在线链接导入 -->
    <el-dialog v-model="urlVisible" title="从在线链接导入" width="480px" destroy-on-close>
      <el-form label-width="90px">
        <el-form-item label="文件链接">
          <el-input v-model="urlForm.url" placeholder="https://...（指向 .pptx 文件的直链）" />
        </el-form-item>
        <el-form-item label="模板名称"><el-input v-model="urlForm.name" placeholder="留空则取文件名" /></el-form-item>
        <el-form-item label="分类">
          <el-select v-model="urlForm.category" style="width:100%">
            <el-option v-for="c in sceneCats.slice(1)" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="dlg-footer">
        <el-button type="primary" :loading="busy" @click="submitUrl">导入</el-button>
      </div>
    </el-dialog>

    <!-- 新建/编辑模板 -->
    <el-dialog v-model="editorVisible" :title="editing ? '编辑模板' : '新建模板'" width="700px" destroy-on-close>
      <el-form label-width="90px">
        <el-form-item label="模板名称"><el-input v-model="tplForm.name" /></el-form-item>
        <el-form-item label="分类">
          <el-select v-model="tplForm.category" style="width:200px">
            <el-option v-for="c in sceneCats.slice(1)" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="说明"><el-input v-model="tplForm.description" /></el-form-item>
        <el-form-item label="主题色">
          <div class="color-row">
            <span v-for="c in colorFields" :key="c.key" class="color-item">
              <el-color-picker v-model="tplForm.colors[c.key]" />
              <label>{{ c.label }}</label>
            </span>
          </div>
        </el-form-item>
        <el-form-item label="字体">
          <el-select v-model="tplForm.font" style="width:200px">
            <el-option v-for="f in fonts" :key="f" :label="f" :value="f" />
          </el-select>
        </el-form-item>
        <el-form-item label="版式体系">
          <div class="layout-grid">
            <div v-for="lt in layoutTypes" :key="lt.key" class="layout-item">
              <label>{{ lt.label }}</label>
              <el-select v-model="tplForm.layouts[lt.key]" size="small">
                <el-option v-for="v in lt.variants" :key="v.value" :label="v.label" :value="v.value" />
              </el-select>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <div class="dlg-footer">
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="busy" @click="saveTemplate">保存模板</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, Plus, Search, Star, StarFilled, CircleCheckFilled, Document,
         FolderOpened, Link, Monitor, Files, Brush, User, View, MagicStick,
         ArrowDown } from '@element-plus/icons-vue'
import axios from 'axios'
// 项目统一请求：直接基于 axios，自动带 token
const request = axios.create({ baseURL: '/api/v1' })
request.interceptors.request.use(cfg => {
  const t = localStorage.getItem('token')
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})
// 401 统一处理：登录过期时提示并跳转登录页，不再静默失败
request.interceptors.response.use(r => r, err => {
  if (err.response?.status === 401) {
    ElMessage.error('登录已过期或未登录，请重新登录后再试')
    localStorage.removeItem('token')
    setTimeout(() => { window.location.href = '/login' }, 800)
  }
  return Promise.reject(err)
})

const router = useRouter()
const libTab = ref('official')
const keyword = ref(''), scene = ref('全部'), styleType = ref('全部'), colorKey = ref(''), sort = ref('rec')
const loading = ref(false), busy = ref(false)
const templates = ref([])
const current = ref(null)
const page = ref(1), pageSize = 9
const previewVisible = ref(false)

const sceneCats = ['全部', '工作汇报', '领导汇报', '政策解读', '培训课件', '会议汇报', '经验交流', '宣传展示']
const styleTypes = ['全部', '政务正式', '简洁商务', '国风古典', '科技互联网', '清新淡雅']
const colorFilters = [
  { key: 'red', label: '政务红', color: '#c0392b' },
  { key: 'blue', label: '商务蓝', color: '#1f6fd6' },
  { key: 'green', label: '清新绿', color: '#2aa25f' },
  { key: 'gold', label: '典雅金', color: '#d9a441' },
  { key: 'cyan', label: '宣传青', color: '#3fa7b8' },
  { key: 'purple', label: '科技紫', color: '#7b53c1' },
  { key: 'pink', label: '活泼粉', color: '#e58bb0' },
  { key: 'gray', label: '简约灰', color: '#8a93a3' },
]
const fonts = ['微软雅黑', '思源黑体', '黑体', '楷体', '仿宋']
const colorFields = [
  { key: 'primary', label: '主色' }, { key: 'accent', label: '强调色' },
  { key: 'light', label: '浅色底' }, { key: 'dark', label: '深色' }]
const layoutTypes = [
  { key: 'cover', label: '封面', variants: [
    { value: 'band_bottom', label: '居中标题+色带' }, { value: 'left_block', label: '左侧色块' }] },
  { key: 'toc', label: '目录', variants: [
    { value: 'numbered_list', label: '编号列表' }, { value: 'cards', label: '卡片网格' }] },
  { key: 'section', label: '章节页', variants: [
    { value: 'left_block', label: '左侧色块' }, { value: 'center', label: '居中大标题' }] },
  { key: 'content', label: '正文页', variants: [
    { value: 'bar_title', label: '标题侧条' }, { value: 'top_band', label: '顶部色带' }] },
  { key: 'closing', label: '结束页', variants: [
    { value: 'center', label: '居中' }, { value: 'brand_band', label: '品牌色带' }] },
]
/* ---------- 模板详情（版式库动态预览） ---------- */
const currentDetail = ref(null)
watch(() => current.value && current.value.id, async (id) => {
  currentDetail.value = null
  if (!id) return
  try {
    const { data } = await request.get(`/ppt/templates/${id}`)
    currentDetail.value = data
  } catch (e) { /* 详情加载失败则显示示意图 */ }
})
const detailLayouts = computed(() => (currentDetail.value && currentDetail.value.layout_library) || [])
const miniType = (t) => ({ cover: 'cover', toc: 'toc', section: 'section', closing: 'closing',
  content_image: 'content_image', chart: 'chart', data: 'data', two_col: 'two_col',
  case: 'case', process: 'chart', timeline: 'chart', summary: 'content', content: 'content' }[t] || 'content')

const previewPages = [
  { type: 'cover', label: '封面页' }, { type: 'toc', label: '目录页' },
  { type: 'section', label: '章节页' }, { type: 'content_image', label: '内容页-图文' },
  { type: 'chart', label: '内容页-数据图表' }, { type: 'two_col', label: '内容页-两栏图文' },
  { type: 'data', label: '数据页' }, { type: 'case', label: '案例展示页' },
  { type: 'closing', label: '总结页' },
]

/* 风格归类（按模板 id / 分类推断） */
const styleOf = (t) => {
  const m = { gov_report_red: '政务正式', policy_blue: '简洁商务', training_blue: '简洁商务',
              exp_share_red: '政务正式', summary_brown: '国风古典', publicity_cyan: '清新淡雅' }
  return m[t.builtin_id] || m[t.id] || '政务正式'
}
const colorFamily = (hex) => {
  const r = parseInt(hex.slice(0, 2), 16), g = parseInt(hex.slice(2, 4), 16), b = parseInt(hex.slice(4, 6), 16)
  if (r > 150 && g < 110) return 'red'
  if (b > r && b > 120 && g > r) return 'cyan'
  if (b >= r && b > 110) return 'blue'
  if (g >= r && g > 120) return 'green'
  if (r > 170 && g > 130 && b < 110) return 'gold'
  if (r > 130 && b > 130) return 'purple'
  if (r > 180 && b > 130) return 'pink'
  return 'gray'
}

const load = async () => {
  loading.value = true
  try {
    const scope = libTab.value === 'mine' ? 'mine' : 'all'
    const { data } = await request.get('/ppt/templates', { params: { scope } })
    templates.value = data.items
    if (!current.value && data.items.length) current.value = data.items[0]
    if (current.value && !data.items.find(t => t.id === current.value.id))
      current.value = data.items[0] || null
  } finally { loading.value = false }
}
const onTabChange = () => { current.value = null; page.value = 1; load() }

const filtered = computed(() => {
  let list = templates.value
  if (libTab.value === 'official') list = list.filter(t => t.is_official)
  if (scene.value !== '全部') list = list.filter(t => t.category === scene.value)
  if (styleType.value !== '全部') list = list.filter(t => styleOf(t) === styleType.value)
  if (colorKey.value) list = list.filter(t => colorFamily(t.colors.primary) === colorKey.value)
  if (keyword.value) list = list.filter(t => t.name.includes(keyword.value) || (t.description || '').includes(keyword.value))
  if (sort.value === 'hot') list = [...list].sort((a, b) => b.use_count - a.use_count)
  return list
})
const paged = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))

const miniBg = (type) => {
  const c = current.value.colors
  if (['cover', 'section', 'closing'].includes(type))
    return { background: 'linear-gradient(135deg, #' + c.primary + ', #' + c.dark + ')' }
  return { background: '#fff' }
}

/* ---------- 操作 ---------- */
const toggleFav = async (t) => {
  const { data } = await request.post(`/ppt/templates/${t.id}/favorite`)
  t.is_favorite = data.is_favorite
}
const useTemplate = () => router.push({ path: '/ppt', query: { template: current.value.id } })
const onMoreCmd = async (cmd) => {
  if (cmd === 'copy') {
    await request.post(`/ppt/templates/${current.value.id}/copy`)
    ElMessage.success('已复制到「我的模板」')
  } else if (cmd === 'edit') {
    openEditor(current.value)
  } else if (cmd === 'delete') {
    await ElMessageBox.confirm(`确定删除模板「${current.value.name}」？`, '提示', { type: 'warning' })
    await request.delete(`/ppt/templates/${current.value.id}`)
    ElMessage.success('已删除')
    current.value = null
    load()
  }
}

/* ---------- 上传 / 链接导入 ---------- */
const uploadVisible = ref(false), urlVisible = ref(false), tplFiles = ref([])
const uploadForm = ref({ name: '', category: '工作汇报' })
const urlForm = ref({ url: '', name: '', category: '工作汇报' })
let tplFileRaw = null
const onUploadCmd = (cmd) => {
  if (cmd === 'url') { urlForm.value = { url: '', name: '', category: '工作汇报' }; urlVisible.value = true }
  else { tplFiles.value = []; tplFileRaw = null; uploadForm.value = { name: '', category: '工作汇报' }; uploadVisible.value = true }
}
const onTplPicked = (f) => { tplFileRaw = f.raw; uploadForm.value.name = f.name.replace(/\.pptx$/i, '') }
const submitUpload = async () => {
  if (!tplFileRaw) return ElMessage.warning('请选择 .pptx 文件')
  busy.value = true
  try {
    const fd = new FormData()
    fd.append('file', tplFileRaw); fd.append('name', uploadForm.value.name); fd.append('category', uploadForm.value.category)
    await request.post('/ppt/templates/upload', fd, { timeout: 120000 })
    ElMessage.success('模板已创建，见「我的模板」')
    uploadVisible.value = false
    libTab.value = 'mine'; load()
  } catch (e) {
    console.error('模板上传失败', e)
    ElMessage.error(e.response?.data?.detail || (e.code === 'ECONNABORTED' ? '上传超时，请检查后端服务' : '上传失败，请检查后端服务是否已更新并重启'))
  } finally { busy.value = false }
}
const submitUrl = async () => {
  if (!urlForm.value.url) return ElMessage.warning('请输入链接')
  busy.value = true
  try {
    await request.post('/ppt/templates/import-url', urlForm.value, { timeout: 120000 })
    ElMessage.success('模板已导入，见「我的模板」')
    urlVisible.value = false
    libTab.value = 'mine'; load()
  } catch (e) {
    console.error('链接导入失败', e)
    ElMessage.error(e.response?.data?.detail || '导入失败，请检查链接是否可访问')
  } finally { busy.value = false }
}

/* ---------- 新建 / 编辑模板 ---------- */
const editorVisible = ref(false), editing = ref(null)
const tplForm = ref({ name: '', category: '工作汇报', description: '', font: '微软雅黑', colors: {}, layouts: {} })
const openEditor = (t) => {
  editing.value = t || null
  tplForm.value = t
    ? JSON.parse(JSON.stringify({ name: t.name, category: t.category, description: t.description,
        colors: t.colors, font: t.font, layouts: t.layouts }))
    : { name: '', category: '工作汇报', description: '', font: '微软雅黑',
        colors: { primary: '#C00000', accent: '#E8B54D', light: '#FDF2F2', dark: '#7A0000' },
        layouts: { cover: 'band_bottom', toc: 'numbered_list', section: 'left_block',
                   content: 'bar_title', closing: 'center' } }
  editorVisible.value = true
}
const saveTemplate = async () => {
  if (!tplForm.value.name) return ElMessage.warning('请填写模板名称')
  busy.value = true
  const payload = JSON.parse(JSON.stringify(tplForm.value))
  for (const k of Object.keys(payload.colors)) payload.colors[k] = (payload.colors[k] || '').replace('#', '')
  try {
    if (editing.value) await request.put(`/ppt/templates/${editing.value.id}`, payload)
    else await request.post('/ppt/templates', payload)
    ElMessage.success('模板已保存')
    editorVisible.value = false
    load()
  } finally { busy.value = false }
}

onMounted(() => {
  load()
  request.post('/ppt/templates/seed').then(load).catch(() => {})
})
</script>

<style scoped>
.tpl-lib { padding: 16px 22px; background: #f5f6fa; min-height: 100%; }
.crumb { font-size: 14px; color: #606266; margin-bottom: 14px; }
.crumb-link { color: #4a7ff7; cursor: pointer; }
.crumb-sep { margin: 0 8px; color: #c0c4cc; }

.lib-head { display: flex; justify-content: space-between; align-items: center; }
.head-actions { display: flex; gap: 10px; }
.up-item { display: flex; gap: 10px; align-items: center; padding: 4px 0; }
.up-item b { font-size: 13px; }
.up-item p { margin: 2px 0 0; font-size: 11px; color: #909399; }
.up-note { font-size: 12px; color: #909399; text-align: right; margin: 6px 2px 10px; }

.lib-body { display: grid; grid-template-columns: 1fr 460px; gap: 16px; align-items: start; }
.lib-main { background: #fff; border-radius: 10px; padding: 18px 20px; border: 1px solid #ebeef5; }
.lib-search { width: 280px; margin-bottom: 14px; }

.filter-row { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.filter-label { font-size: 13px; color: #606266; flex-shrink: 0; }
.chip { font-size: 13px; color: #606266; padding: 3px 12px; border-radius: 20px; cursor: pointer; }
.chip:hover { color: #4a7ff7; }
.chip.on { background: #e8efff; color: #4a7ff7; font-weight: 600; }
.color-dot { width: 20px; height: 20px; border-radius: 50%; cursor: pointer;
  border: 2px solid transparent; transition: transform .15s; }
.color-dot:hover { transform: scale(1.15); }
.color-dot.on { border-color: #303133; box-shadow: 0 0 0 2px #fff inset; }

.grid-title { font-size: 14px; font-weight: 600; margin: 14px 0 12px; }
.muted { font-size: 12px; color: #909399; font-weight: 400; }

.tpl-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.tpl-card { border: 1.5px solid #e4e7ed; border-radius: 10px; overflow: hidden;
  cursor: pointer; transition: all .15s; background: #fff; }
.tpl-card:hover { border-color: #b3c8f5; box-shadow: 0 4px 14px rgba(74,127,247,.12); }
.tpl-card.active { border-color: #4a7ff7; box-shadow: 0 0 0 3px rgba(74,127,247,.15); }
.tpl-cover { height: 120px; position: relative; padding: 16px; display: flex;
  flex-direction: column; justify-content: center; }
.tg-official { position: absolute; left: 0; top: 10px; border-radius: 0 4px 4px 0;
  background: #4a7ff7; border-color: #4a7ff7; }
.tc-check { position: absolute; right: 8px; top: 8px; color: #fff; font-size: 20px; }
.tc-band { width: 42%; height: 5px; border-radius: 3px; margin-bottom: 10px; }
.tc-img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover;
          filter: brightness(.65); }
.tpl-cover .tc-band, .tpl-cover .tc-title, .tpl-cover .tc-sub { position: relative; z-index: 1; }
.pv-img { width: 100%; aspect-ratio: 16/9; object-fit: cover; border-radius: 6px;
          border: 1px solid #ebeef5; display: block; }
.fp-img { width: 100%; border-radius: 8px; border: 1px solid #ebeef5; display: block; }
.layout-tag { color: #4a7ff7; border-color: #b3c8f5; background: #eef3fe; }
.tc-title { color: #fff; font-size: 15px; font-weight: 700; }
.tc-sub { color: rgba(255,255,255,.75); font-size: 11px; margin-top: 5px; }
.tpl-info { padding: 10px 12px 12px; }
.ti-name { font-size: 14px; font-weight: 600; display: flex; justify-content: space-between; align-items: center; }
.ti-star { color: #c0c4cc; cursor: pointer; } .ti-star.fav { color: #e6a23c; }
.ti-tags { display: flex; gap: 6px; margin: 7px 0; }
.ti-tag { font-size: 11px; color: #606266; background: #f2f3f5; padding: 2px 8px; border-radius: 4px; }
.ti-use { font-size: 12px; color: #909399; }
.lib-pager { margin-top: 16px; justify-content: center; }

/* 右侧详情 */
.lib-detail { background: #fff; border-radius: 10px; padding: 20px; border: 1px solid #ebeef5;
  position: sticky; top: 16px; }
.d-title { font-size: 17px; font-weight: 700; display: flex; gap: 8px; align-items: center; }
.d-tags { display: flex; gap: 6px; margin: 10px 0; }
.d-desc { font-size: 13px; color: #606266; line-height: 1.6; }
.d-meta { display: flex; align-items: center; gap: 16px; font-size: 12px; color: #909399;
  margin: 12px 0 16px; }
.d-meta span { display: flex; align-items: center; gap: 4px; }
.d-fav { margin-left: auto; }
.d-sub { font-size: 14px; font-weight: 600; margin-bottom: 12px; }
.d-preview { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.d-pv-item { text-align: center; }
.d-pv-label { font-size: 11px; color: #909399; margin-top: 5px; display: block; }
.d-actions { display: flex; gap: 10px; margin-top: 18px; }
.d-actions .el-button { flex: 1; margin: 0; }

/* 版式小图 */
.mini { height: 74px; border: 1px solid #e4e7ed; border-radius: 6px; padding: 8px;
  display: flex; flex-direction: column; gap: 5px; overflow: hidden; }
.mini.big { height: 150px; }
.m-band { width: 45%; height: 5px; border-radius: 3px; }
.m-head { width: 45%; height: 7px; border-radius: 3px; }
.m-line { height: 6px; background: #e4e7ed; border-radius: 3px; }
.m-line.thin { height: 4px; }
.m-line.white { background: rgba(255,255,255,.9); }
.m-line.white.thin { background: rgba(255,255,255,.6); }
.m-row { display: flex; align-items: center; gap: 5px; }
.m-row i { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
.m-row em { flex: 1; height: 5px; background: #e4e7ed; border-radius: 3px; }
.m-cols { display: flex; gap: 6px; flex: 1; }
.m-col { flex: 1; display: flex; flex-direction: column; gap: 4px; }
.m-img { flex: 1; border: 1px solid; border-radius: 4px; }
.m-chart { display: flex; align-items: flex-end; gap: 5px; flex: 1; padding: 0 6px; }
.m-chart i { flex: 1; border-radius: 2px 2px 0 0; }
.m-cards { display: flex; gap: 5px; flex: 1; }
.m-cards b { flex: 1; border-radius: 4px; padding: 4px; display: flex; flex-direction: column; }
.m-cards b i { width: 60%; height: 6px; border-radius: 3px; }

.full-preview { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.fp-item { text-align: center; }
.dlg-footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px; }
.color-row { display: flex; gap: 18px; }
.color-item { display: flex; flex-direction: column; align-items: center; gap: 4px;
  font-size: 12px; color: #606266; }
.layout-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.layout-item label { font-size: 12px; color: #606266; display: block; margin-bottom: 4px; }
.layout-item .el-select { width: 100%; }
</style>