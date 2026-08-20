<template>
  <div class="tpl-center">
    <div class="page-header">
      <div class="header-left">
        <h2>模板中心</h2>
        <p class="subtitle">选择合适的模板，作为智能写作和公文起草的格式参考。</p>
      </div>
      <div class="header-right">
        <el-button v-if="isAdmin" text type="primary" @click="initTemplates" :loading="initing">
          <el-icon><Refresh /></el-icon> 初始化内置模板
        </el-button>
        <el-button :type="onlyMine ? 'primary' : 'default'" :plain="!onlyMine" @click="onlyMine = !onlyMine">我的模板</el-button>
        <el-button v-if="isAdmin" type="primary" @click="openCreateDialog">
          <el-icon><Plus /></el-icon> 新建模板
        </el-button>
      </div>
    </div>

    <!-- 搜索 -->
    <div class="search-bar">
      <el-input v-model="searchQuery" size="large" clearable
        placeholder="搜索模板名称或关键词，例如：请示、工作总结、会议通知…">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
    </div>

    <!-- 一级分类 -->
    <div class="category-bar">
      <div class="category-item" :class="{ active: activeCategory === '' }" @click="activeCategory = ''">全部</div>
      <div v-for="cat in categories" :key="cat.code" class="category-item"
        :class="{ active: activeCategory === cat.name }" @click="activeCategory = cat.name">{{ cat.name }}</div>
    </div>

    <div class="main-row" v-loading="loading">
      <!-- 左：模板列表 -->
      <div class="list-panel">
        <div class="list-head">
          <span>模板列表（共 {{ filteredList.length }} 个）</span>
          <el-select v-model="sortBy" size="small" style="width: 130px">
            <el-option label="按使用频率" value="freq" />
            <el-option label="按名称" value="name" />
          </el-select>
        </div>
        <div class="list-body">
          <div v-for="t in filteredList" :key="t.id" class="tpl-row" :class="{ active: selectedId === t.id }"
            @click="selectedId = t.id">
            <div class="tpl-icon" :class="'ic-' + iconColor(t.category)">
              <el-icon :size="22"><component :is="t.icon || 'Document'" /></el-icon>
            </div>
            <div class="tpl-info">
              <div class="tpl-name-row">
                <span class="tpl-name">{{ t.name }}</span>
                <span class="tpl-cat-tag" :class="'tag-' + iconColor(t.category)">{{ t.category }}</span>
                <el-tag v-if="!t.is_builtin" size="small" type="info" effect="plain">我的</el-tag>
              </div>
              <div class="tpl-desc">{{ t.description || (t.base_type + '类材料') }}</div>
            </div>
            <div class="tpl-row-right">
              <el-button size="small" type="primary" plain @click.stop="useTemplate(t)">使用模板</el-button>
              <div v-if="isAdmin" class="tpl-admin">
                <el-icon title="编辑" @click.stop="editTemplate(t)"><Edit /></el-icon>
                <el-icon title="删除" class="del" @click.stop="deleteTemplate(t)"><Delete /></el-icon>
              </div>
            </div>
          </div>
          <el-empty v-if="!loading && !filteredList.length" description="没有符合条件的模板" :image-size="100" />
        </div>
      </div>

      <!-- 右：模板预览 -->
      <div class="preview-panel" v-if="selectedTemplate">
        <div class="pv-head">
          <span class="pv-title">模板预览</span>
          <span class="pv-fav" @click="toggleFav(selectedTemplate.id)">
            <el-icon :color="isFav(selectedTemplate.id) ? '#e6a23c' : '#c0c4cc'">
              <StarFilled v-if="isFav(selectedTemplate.id)" /><Star v-else />
            </el-icon> 收藏模板
          </span>
        </div>
        <div class="pv-name-row">
          <div class="tpl-icon big" :class="'ic-' + iconColor(selectedTemplate.category)">
            <el-icon :size="26"><component :is="selectedTemplate.icon || 'Document'" /></el-icon>
          </div>
          <div>
            <div class="pv-name">{{ selectedTemplate.name }}</div>
            <div class="pv-tags">
              <el-tag size="small" effect="plain" type="primary">{{ selectedTemplate.base_type || '公文' }}</el-tag>
              <el-tag size="small" effect="plain">{{ selectedTemplate.category }}</el-tag>
              <el-tag v-if="selectedTemplate.is_builtin" size="small" type="success" effect="light">官方</el-tag>
            </div>
          </div>
        </div>

        <div class="pv-sec-title">适用场景</div>
        <p class="pv-desc">{{ selectedTemplate.description || '暂无描述' }}</p>

        <div class="pv-sec-title">模板结构</div>
        <div class="pv-struct" v-for="(item, i) in structureItems" :key="i">
          <div class="pv-struct-name">{{ cnNums[i] }}、{{ item }}</div>
        </div>

        <div class="pv-sec-title">格式预览</div>
        <div class="pv-skeleton">
          <div class="sk-title">关于××××的{{ selectedTemplate.base_type || '公文' }}</div>
          <div class="sk-body">
            <div v-for="(item, i) in structureItems.slice(0, 5)" :key="i" class="sk-line">
              <b>{{ cnNums[i] }}、{{ item }}</b>
              <span class="sk-dots">……</span>
            </div>
          </div>
          <div class="sk-foot">
            <div v-if="selectedTemplate.need_signature">（单位落款）</div>
            <div v-if="selectedTemplate.need_date">××××年××月××日</div>
          </div>
        </div>

        <el-button type="primary" size="large" class="pv-use-btn" @click="useTemplate(selectedTemplate)">
          使用此模板
        </el-button>
      </div>
      <div class="preview-panel pv-empty" v-else>
        <el-empty description="选择左侧模板查看预览" />
      </div>
    </div>

    <!-- 新建/编辑对话框（新版设计：基础信息/写作指引/结构/参考材料/知识库/权限/图标） -->
    <TemplateCreateDialog ref="tplDialogRef" @saved="loadData" />
  </div>
</template>
<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ElMessageBox } from 'element-plus'
import { View, Refresh, Plus, Edit, Delete, Search, Star, StarFilled } from '@element-plus/icons-vue'
import TemplateCreateDialog from '../components/TemplateCreateDialog.vue'
import axios from 'axios'

const router = useRouter()
const token = ref(localStorage.getItem('token') || '')

const categories = ref([])
const templates = ref([])
const loading = ref(false)
const initing = ref(false)
const activeCategory = ref('')
const searchQuery = ref('')
const sortBy = ref('freq')
const selectedId = ref('')
const onlyMine = ref(false)
const favs = ref(JSON.parse(localStorage.getItem('fav_templates') || '[]'))
const cnNums = ['一','二','三','四','五','六','七','八','九','十']
const tplDialogRef = ref(null)

const isAdmin = computed(() => {
  try {
    const user = JSON.parse(localStorage.getItem('user') || '{}')
    return ['developer', 'knowledge_admin', 'admin'].includes(user.role)
  } catch { return false }
})

// 统一过滤：分类 + 我的模板 + 搜索 + 排序
const filteredList = computed(() => {
  let list = templates.value
  if (onlyMine.value) list = list.filter(t => !t.is_builtin)
  if (activeCategory.value) list = list.filter(t => t.category === activeCategory.value)
  const q = searchQuery.value.trim()
  if (q) {
    list = list.filter(t =>
      (t.name || '').includes(q) || (t.description || '').includes(q) ||
      (t.base_type || '').includes(q) || (t.category || '').includes(q))
  }
  list = list.slice()
  if (sortBy.value === 'freq') list.sort((a, b) => (b.use_count || 0) - (a.use_count || 0))
  else list.sort((a, b) => (a.name || '').localeCompare(b.name || '', 'zh'))
  return list
})

const selectedTemplate = computed(() =>
  templates.value.find(t => t.id === selectedId.value) || filteredList.value[0] || null
)

// 模板结构：从 content_template 的"包含：××、××"解析
const structureItems = computed(() => {
  const t = selectedTemplate.value
  if (!t) return []
  const m = (t.content_template || '').match(/包含：(.+?)。/)
  if (m) return m[1].split(/[、，；,]/).map(s => s.trim()).filter(s => s && !/^(落款|成文日期|签名栏)/.test(s)).slice(0, 8)
  return (t.params_schema || []).map(p => p.label).slice(0, 8)
})

function isFav(id) { return favs.value.includes(id) }
function toggleFav(id) {
  favs.value = isFav(id) ? favs.value.filter(x => x !== id) : [...favs.value, id]
  localStorage.setItem('fav_templates', JSON.stringify(favs.value))
}

const baseTypes = [
  { label: '通知', value: '通知', fields: [
    {name:'title',label:'通知标题',type:'input',required:true,placeholder:'如：关于开展社区矫正专项排查的通知'},
    {name:'recipient',label:'通知对象',type:'input',required:true,placeholder:'如：各区县司法局'},
    {name:'purpose',label:'发文目的',type:'textarea',required:true,placeholder:'请简述发文目的和政策依据',rows:3},
    {name:'content',label:'具体事项',type:'textarea',required:true,placeholder:'请详细说明通知的具体内容',rows:5},
    {name:'requirements',label:'工作要求',type:'textarea',required:true,placeholder:'请简述工作要求和时间节点',rows:3},
    {name:'contact',label:'联系人',type:'input',required:false,placeholder:'如：张三'},
    {name:'phone',label:'联系电话',type:'input',required:false,placeholder:'如：0531-12345678'}
  ]},
  { label: '计划与总结', value: '计划与总结', fields: [
    {name:'title',label:'标题',type:'input',required:true,placeholder:'如：社区矫正科2026年上半年工作总结暨下半年工作计划'},
    {name:'department',label:'部门/单位',type:'input',required:true,placeholder:'如：社区矫正科'},
    {name:'period',label:'时间范围',type:'input',required:true,placeholder:'如：2026年全年 / 2026年上半年'},
    {name:'background',label:'工作背景',type:'textarea',required:false,placeholder:'请简述工作背景、上级要求和政策依据',rows:3},
    {name:'goals',label:'工作目标',type:'textarea',required:false,placeholder:'请简述年度/阶段工作目标和总体思路',rows:3},
    {name:'key_work',label:'重点工作',type:'textarea',required:false,placeholder:'请列出重点工作任务和主要举措',rows:4},
    {name:'measures',label:'具体措施',type:'textarea',required:false,placeholder:'请简述落实工作的具体措施、步骤和时间安排',rows:4},
    {name:'completion',label:'完成情况',type:'textarea',required:false,placeholder:'请简述各项工作完成情况（写总结时填写）',rows:4},
    {name:'achievements',label:'取得成效',type:'textarea',required:false,placeholder:'请简述工作成效、亮点和相关数据（写总结时填写）',rows:4},
    {name:'problems',label:'存在问题',type:'textarea',required:false,placeholder:'请简述工作中存在的问题和不足',rows:3},
    {name:'next_plan',label:'下一步工作',type:'textarea',required:false,placeholder:'请简述下一步工作计划、目标和安排',rows:3}
  ]},
  { label: '请示', value: '请示', fields: [
    {name:'title',label:'请示标题',type:'input',required:true,placeholder:'如：关于申请社区矫正专项工作经费的请示'},
    {name:'recipient',label:'主送机关',type:'input',required:true,placeholder:'如：市司法局'},
    {name:'reason',label:'请示理由',type:'textarea',required:true,placeholder:'请简述请示的背景、原因和必要性',rows:4},
    {name:'basis',label:'请示依据',type:'textarea',required:false,placeholder:'相关政策文件或法律依据（如有）',rows:3},
    {name:'matter',label:'请求批准事项',type:'textarea',required:true,placeholder:'请详细说明需要上级批准或解决的具体事项、金额、时间等',rows:4},
    {name:'suggestion',label:'拟办意见',type:'textarea',required:false,placeholder:'拟采取的方案或建议（如有）',rows:3}
  ]},
  { label: '报告', value: '报告', fields: [
    {name:'title',label:'报告标题',type:'input',required:true,placeholder:'如：关于XX工作的报告'},
    {name:'background',label:'工作背景',type:'textarea',required:true,placeholder:'请简述背景',rows:3},
    {name:'work_content',label:'工作内容',type:'textarea',required:true,placeholder:'请详细说明工作内容',rows:5},
    {name:'achievements',label:'工作成效',type:'textarea',required:true,placeholder:'请简述成效',rows:4},
    {name:'problems',label:'存在问题',type:'textarea',required:true,placeholder:'请简述问题',rows:3},
    {name:'suggestions',label:'建议措施',type:'textarea',required:true,placeholder:'请提出建议',rows:3}
  ]},
  { label: '调研报告', value: '调研报告', fields: [
    {name:'title',label:'调研主题',type:'input',required:true,placeholder:'如：社区矫正工作现状调研'},
    {name:'background',label:'调研背景',type:'textarea',required:true,placeholder:'请简述背景',rows:3},
    {name:'method',label:'调研方法',type:'textarea',required:true,placeholder:'请简述方法',rows:3},
    {name:'findings',label:'调研发现',type:'textarea',required:true,placeholder:'请简述发现',rows:5},
    {name:'problems',label:'存在问题',type:'textarea',required:true,placeholder:'请简述问题',rows:3},
    {name:'suggestions',label:'对策建议',type:'textarea',required:true,placeholder:'请提出建议',rows:4}
  ]},
  { label: '会议纪要', value: '会议纪要', fields: [
    {name:'meeting_name',label:'会议名称',type:'input',required:true,placeholder:'如：社区矫正工作推进会'},
    {name:'time',label:'会议时间',type:'input',required:true,placeholder:'如：2026年7月23日'},
    {name:'location',label:'会议地点',type:'input',required:true,placeholder:'如：局会议室'},
    {name:'host',label:'主持人',type:'input',required:true,placeholder:'如：张局长'},
    {name:'attendees',label:'参会人员',type:'textarea',required:true,placeholder:'请列出参会人员',rows:2},
    {name:'content',label:'会议内容',type:'textarea',required:true,placeholder:'请简述内容',rows:5},
    {name:'decisions',label:'会议决议',type:'textarea',required:true,placeholder:'请列出决议',rows:3}
  ]},
  { label: '计划', value: '计划', fields: [
    {name:'year',label:'年份',type:'input',required:true,placeholder:'如：2026'},
    {name:'department',label:'部门',type:'input',required:true,placeholder:'如：社区矫正科'},
    {name:'background',label:'工作背景',type:'textarea',required:true,placeholder:'请简述背景',rows:3},
    {name:'goals',label:'工作目标',type:'textarea',required:true,placeholder:'请简述目标',rows:3},
    {name:'measures',label:'具体措施',type:'textarea',required:true,placeholder:'请简述措施',rows:4},
    {name:'timeline',label:'时间安排',type:'textarea',required:false,placeholder:'请简述时间安排',rows:3}
  ]},
  { label: '执法文书', value: '执法文书', fields: [
    {name:'doc_type',label:'文书类型',type:'select',required:true,options:[{label:'调查笔录',value:'调查笔录'},{label:'告知书',value:'告知书'},{label:'决定书',value:'决定书'},{label:'通知书',value:'通知书'}]},
    {name:'party',label:'当事人',type:'input',required:true,placeholder:'如：王某某'},
    {name:'facts',label:'事实经过',type:'textarea',required:true,placeholder:'请简述事实',rows:4},
    {name:'basis',label:'法律依据',type:'textarea',required:true,placeholder:'请列出依据',rows:3},
    {name:'decision',label:'处理决定',type:'textarea',required:true,placeholder:'请说明决定',rows:3}
  ]},
  { label: '汇报', value: '汇报', fields: [
    {name:'title',label:'汇报标题',type:'input',required:true,placeholder:'如：关于XX情况的汇报'},
    {name:'recipient',label:'汇报对象',type:'input',required:true,placeholder:'如：局领导'},
    {name:'situation',label:'情况说明',type:'textarea',required:true,placeholder:'请详细说明',rows:5},
    {name:'measures',label:'已采取措施',type:'textarea',required:true,placeholder:'请简述措施',rows:3},
    {name:'suggestions',label:'建议',type:'textarea',required:false,placeholder:'请简述建议',rows:3}
  ]}
]

const baseTypeOptions = baseTypes.map(b => b.value)

const createDialogVisible = ref(false)
const createLoading = ref(false)
const createFormRef = ref(null)
const editingTemplateId = ref(null)
const createForm = ref({
  name: '', category: '', base_type: '通知', description: '', icon: 'Document',
  content_template: '', system_prompt: '',
  writing_style: '正式公文', word_count: 1000,
  need_red_header: false, need_signature: true, need_date: true, need_doc_number: false,
  keywords: '', params_schema: []
})
const createRules = {
  name: [{ required: true, message: '请输入模板名称', trigger: 'blur' }],
  category: [{ required: true, message: '请选择分类', trigger: 'change' }]
}

function openCreateDialog() {
  tplDialogRef.value?.open(null)
}

function onBaseTypeChange(type) {
  const bt = baseTypes.find(b => b.value === type)
  if (bt) {
    createForm.value.params_schema = bt.fields.map(f => ({...f}))
    const fieldNames = bt.fields.map(f => `{${f.name}}`).join('、')
    createForm.value.content_template = `${bt.label}类公文，通常包含：${fieldNames}等要素。请根据用户提供的要素生成规范的${bt.label}。`
    createForm.value.system_prompt = `你是一位资深的司法行政公文写作专家，擅长撰写${bt.label}类公文。请根据用户提供的要素生成规范的${bt.label}。要求：1.语言正式、严谨，符合党政机关公文规范；2.内容充实、条理清晰；3.不要简单填空，要根据要素展开成完整的公文正文。`
  }
}

function addParam() {
  createForm.value.params_schema.push({ name: '', label: '', type: 'input', required: false, placeholder: '' })
}

function removeParam(idx) {
  createForm.value.params_schema.splice(idx, 1)
}

async function submitCreateTemplate() {
  const valid = await createFormRef.value?.validate().catch(() => false)
  if (!valid) return
  createLoading.value = true
  try {
    const payload = {
      name: createForm.value.name, category: createForm.value.category,
      base_type: createForm.value.base_type, description: createForm.value.description,
      icon: createForm.value.icon,
      params_schema: createForm.value.params_schema.map(p => ({
        name: p.name, label: p.label, type: p.type, required: p.required,
        placeholder: p.placeholder, options: p.options || undefined
      })),
      content_template: createForm.value.content_template,
      system_prompt: createForm.value.system_prompt,
      writing_style: createForm.value.writing_style,
      word_count: createForm.value.word_count,
      need_red_header: createForm.value.need_red_header,
      need_signature: createForm.value.need_signature,
      need_date: createForm.value.need_date,
      need_doc_number: createForm.value.need_doc_number,
      keywords: createForm.value.keywords
    }
    if (editingTemplateId.value) {
      await axios.put(`/api/v1/templates/${editingTemplateId.value}`, payload, {
        headers: { Authorization: `Bearer ${token.value}` }
      })
      ElMessage.success('模板修改成功')
      editingTemplateId.value = null
    } else {
      await axios.post('/api/v1/templates/', payload, {
        headers: { Authorization: `Bearer ${token.value}` }
      })
      ElMessage.success('模板创建成功')
    }
    createDialogVisible.value = false
    loadData()
  } catch (e) {
    ElMessage.error(editingTemplateId.value ? '修改失败：' : '创建失败：' + (e.response?.data?.detail || e.message))
  } finally {
    createLoading.value = false
  }
}

onMounted(() => { loadData() })

async function loadData() {
  loading.value = true
  try {
    const [catRes, tmplRes] = await Promise.all([
      axios.get('/api/v1/templates/categories', { headers: { Authorization: `Bearer ${token.value}` } }),
      axios.get('/api/v1/templates/', { headers: { Authorization: `Bearer ${token.value}` } })
    ])
    categories.value = catRes.data || []
    templates.value = tmplRes.data || []
    if (!selectedId.value && templates.value.length) selectedId.value = templates.value[0].id
  } catch (e) {
    ElMessage.error('加载模板失败')
  } finally {
    loading.value = false
  }
}

async function initTemplates() {
  initing.value = true
  try {
    await axios.post('/api/v1/templates/init', {}, {
      headers: { Authorization: `Bearer ${token.value}` }
    })
    ElMessage.success('内置模板初始化成功')
    loadData()
  } catch (e) {
    ElMessage.error('初始化失败：' + (e.response?.data?.detail || '无权限'))
  } finally {
    initing.value = false
  }
}

function useTemplate(tmpl) {
  router.push(`/template/${tmpl.id}`)
}

function editTemplate(tmpl) {
  tplDialogRef.value?.open(tmpl)
}

async function deleteTemplate(tmpl) {
  try {
    await ElMessageBox.confirm(`确定删除模板「${tmpl.name}」吗？`, '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await axios.delete(`/api/v1/templates/${tmpl.id}`, {
      headers: { Authorization: `Bearer ${token.value}` }
    })
    ElMessage.success('模板已删除')
    loadData()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败：' + (e.response?.data?.detail || e.message))
    }
  }
}

function iconColor(category) {
  const map = { '法定公文': 'blue', '工作材料': 'green', '宣传材料': 'orange', '其他材料': 'purple' }
  return map[category] || 'blue'
}

</script>

<style scoped>
.tpl-center { padding: 20px 24px; background: #f5f6f8; min-height: 100%; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.page-header h2 { margin: 0; font-size: 22px; }
.subtitle { color: #909399; font-size: 13px; margin: 4px 0 0; }
.header-right { display: flex; gap: 10px; align-items: center; }

.search-bar { margin-bottom: 14px; }
.search-bar :deep(.el-input__wrapper) { border-radius: 8px; }

.category-bar { display: flex; gap: 8px; margin-bottom: 16px; }
.category-item {
  padding: 6px 18px; border-radius: 6px; font-size: 14px; cursor: pointer;
  color: #606266; background: #fff; border: 1px solid #e4e7ed; transition: all .15s;
}
.category-item.active { background: #2f5cff; border-color: #2f5cff; color: #fff; }

.main-row { display: flex; gap: 16px; align-items: flex-start; }
.list-panel { flex: 0 0 46%; background: #fff; border-radius: 10px; padding: 14px 16px; }
.list-head { display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 600; margin-bottom: 10px; }
.list-body { max-height: calc(100vh - 260px); overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.tpl-row {
  display: flex; align-items: center; gap: 12px; padding: 12px 14px;
  border: 1.5px solid #ebeef5; border-radius: 10px; cursor: pointer; transition: all .15s;
}
.tpl-row:hover { border-color: #c6d4ff; }
.tpl-row.active { border-color: #2f5cff; background: #f5f8ff; }
.tpl-icon {
  width: 44px; height: 44px; border-radius: 10px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center; color: #fff;
}
.tpl-icon.big { width: 52px; height: 52px; }
.ic-blue { background: #2f5cff; } .ic-green { background: #1bb580; }
.ic-orange { background: #f08c1a; } .ic-purple { background: #8b5cf6; }
.tpl-info { flex: 1; min-width: 0; }
.tpl-name-row { display: flex; align-items: center; gap: 8px; }
.tpl-name { font-weight: 700; font-size: 15px; }
.tpl-cat-tag { font-size: 12px; border-radius: 4px; padding: 1px 8px; }
.tag-blue { background: #e8efff; color: #2f5cff; }
.tag-green { background: #e3f7ef; color: #1bb580; }
.tag-orange { background: #fdf1e2; color: #f08c1a; }
.tag-purple { background: #f1ebfd; color: #8b5cf6; }
.tpl-desc { font-size: 12px; color: #909399; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tpl-row-right { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex-shrink: 0; }
.tpl-admin { display: flex; gap: 8px; color: #909399; font-size: 14px; }
.tpl-admin .del:hover { color: #f56c6c; }
.tpl-admin .el-icon:hover { color: #2f5cff; }

.preview-panel { flex: 1; background: #fff; border-radius: 10px; padding: 18px 22px; position: sticky; top: 16px; }
.pv-empty { display: flex; align-items: center; justify-content: center; min-height: 400px; }
.pv-head { display: flex; justify-content: space-between; align-items: center; font-weight: 600; font-size: 15px; margin-bottom: 16px; }
.pv-fav { font-size: 13px; color: #909399; font-weight: 400; cursor: pointer; display: flex; align-items: center; gap: 4px; }
.pv-name-row { display: flex; align-items: center; gap: 14px; margin-bottom: 14px; }
.pv-name { font-size: 19px; font-weight: 700; }
.pv-tags { display: flex; gap: 6px; margin-top: 6px; }
.pv-sec-title { font-weight: 700; font-size: 14px; margin: 14px 0 8px; }
.pv-desc { font-size: 13px; color: #606266; margin: 0; line-height: 1.8; }
.pv-struct { margin-bottom: 4px; }
.pv-struct-name { color: #2f5cff; font-size: 13px; font-weight: 600; }
.pv-skeleton { border: 1px solid #ebeef5; border-radius: 8px; padding: 20px 24px; background: #fafbfc; }
.sk-title { text-align: center; font-weight: 700; font-size: 15px; margin-bottom: 14px; }
.sk-line { font-size: 13px; color: #606266; line-height: 2; }
.sk-line b { color: #303133; }
.sk-dots { color: #c0c4cc; margin-left: 8px; }
.sk-foot { text-align: right; font-size: 13px; color: #606266; margin-top: 12px; line-height: 1.9; }
.pv-use-btn { width: 100%; margin-top: 16px; font-size: 15px; }

/* 保留对话框内样式 */
.form-hint { font-size: 12px; color: #909399; margin-top: 4px; }
.param-field-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
</style>