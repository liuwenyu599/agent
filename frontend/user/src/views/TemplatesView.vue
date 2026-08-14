 <template>
  <div class="templates-page">
    <div class="page-header">
      <div class="header-left">
        <h2>写作模板</h2>
        <p class="subtitle">选择模板，快速生成规范公文</p>
      </div>
      <div class="header-right">
        <el-button type="primary" @click="openCreateDialog" v-if="isAdmin">
          <el-icon><Plus /></el-icon> 新建模板
        </el-button>
        <el-button type="primary" @click="initTemplates" :loading="initing" v-if="isAdmin" plain>
          <el-icon><Refresh /></el-icon> 初始化内置模板
        </el-button>
      </div>
    </div>

    <!-- 圆角 pill 分类导航 -->
    <div class="category-bar">
      <div class="category-nav">
        <div class="category-item" :class="{ active: activeCategory === '' }" @click="activeCategory = ''">全部</div>
        <div v-for="cat in categories" :key="cat.code" class="category-item" :class="{ active: activeCategory === cat.name }" @click="activeCategory = cat.name">{{ cat.name }}</div>
      </div>
    </div>

    <!-- 官方模板 -->
    <div class="section-title" v-if="filteredBuiltin.length > 0">
      <span class="section-icon">📌</span>
      <span>官方模板</span>
      <span class="section-badge">{{ filteredBuiltin.length }} 个</span>
    </div>
    <el-row :gutter="20" v-if="filteredBuiltin.length > 0">
      <el-col :xs="24" :sm="12" :md="8" v-for="tmpl in filteredBuiltin" :key="tmpl.id">
        <div class="template-card" :class="'cat-' + iconColor(tmpl.category)" @click="useTemplate(tmpl)">
          <div class="card-accent"></div>
          <div class="card-main">
            <div class="card-header">
              <h3 class="card-name">{{ tmpl.name }}</h3>
              <el-tag size="small" type="success" effect="light" class="card-badge">官方</el-tag>
            </div>
            <div class="card-meta">
              <span>{{ tmpl.base_type || tmpl.category }}</span>
              <span class="dot">·</span>
              <span>{{ tmpl.writing_style || '正式公文' }}</span>
            </div>
            <p class="card-desc">{{ tmpl.description || '点击添加描述' }}</p>
            <div class="card-footer">
              <div class="card-stats">
                <span class="stat-item">
                  <el-icon><View /></el-icon> 使用 {{ tmpl.use_count || 0 }} 次
                </span>
                <span class="hot-badge" v-if="(tmpl.use_count || 0) > 10">⭐ 常用</span>
              </div>
              <div class="card-actions" v-if="isAdmin">
                <el-button link size="small" type="primary" @click.stop="editTemplate(tmpl)" title="编辑">
                  <el-icon><Edit /></el-icon>
                </el-button>
                <el-button link size="small" type="danger" @click.stop="deleteTemplate(tmpl)" title="删除">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 自定义模板 -->
    <div class="section-title" v-if="filteredCustom.length > 0">
      <span class="section-icon">✏️</span>
      <span>自定义模板</span>
      <span class="section-badge">{{ filteredCustom.length }} 个</span>
    </div>
    <el-row :gutter="20" v-if="filteredCustom.length > 0">
      <el-col :xs="24" :sm="12" :md="8" v-for="tmpl in filteredCustom" :key="tmpl.id">
        <div class="template-card" :class="'cat-' + iconColor(tmpl.category)" @click="useTemplate(tmpl)">
          <div class="card-accent"></div>
          <div class="card-main">
            <div class="card-header">
              <h3 class="card-name">{{ tmpl.name }}</h3>
              <el-tag size="small" type="info" effect="light" class="card-badge">自定义</el-tag>
            </div>
            <div class="card-meta">
              <span>{{ tmpl.base_type || tmpl.category }}</span>
              <span class="dot">·</span>
              <span>{{ tmpl.writing_style || '正式公文' }}</span>
            </div>
            <p class="card-desc">{{ tmpl.description || '点击添加描述' }}</p>
            <div class="card-footer">
              <div class="card-stats">
                <span class="stat-item">
                  <el-icon><View /></el-icon> 使用 {{ tmpl.use_count || 0 }} 次
                </span>
                <span class="hot-badge" v-if="(tmpl.use_count || 0) > 10">⭐ 常用</span>
              </div>
              <div class="card-actions" v-if="isAdmin">
                <el-button link size="small" type="primary" @click.stop="editTemplate(tmpl)" title="编辑">
                  <el-icon><Edit /></el-icon>
                </el-button>
                <el-button link size="small" type="danger" @click.stop="deleteTemplate(tmpl)" title="删除">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>

    <el-empty v-if="!loading && filteredBuiltin.length === 0 && filteredCustom.length === 0" description="暂无模板" :image-size="120" />

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="createDialogVisible" :title="editingTemplateId ? '修改写作模板' : '新建写作模板'" width="700px" destroy-on-close>
      <el-form :model="createForm" :rules="createRules" ref="createFormRef" label-width="100px">
        <el-form-item label="模板名称" prop="name">
          <el-input v-model="createForm.name" placeholder="如：年度工作总结" />
        </el-form-item>
        <el-form-item label="基础类型">
          <el-select v-model="createForm.base_type" @change="onBaseTypeChange" style="width:100%">
            <el-option v-for="t in baseTypeOptions" :key="t" :label="t" :value="t" />
          </el-select>
          <div class="form-hint">选择基础类型后，系统会自动加载常用字段</div>
        </el-form-item>
        <el-form-item label="分类" prop="category">
          <el-select v-model="createForm.category" placeholder="选择分类" style="width:100%">
            <el-option v-for="cat in categories" :key="cat.code" :label="cat.name" :value="cat.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="2" placeholder="模板用途说明" />
        </el-form-item>
        <el-form-item label="图标">
          <el-input v-model="createForm.icon" placeholder="如：DocumentChecked" />
        </el-form-item>
        <el-divider content-position="left">写作偏好</el-divider>
        <el-form-item label="写作风格">
          <el-radio-group v-model="createForm.writing_style">
            <el-radio-button label="正式公文">正式公文</el-radio-button>
            <el-radio-button label="简洁明了">简洁明了</el-radio-button>
            <el-radio-button label="领导讲话">领导讲话</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="字数要求">
          <el-slider v-model="createForm.word_count" :min="500" :max="5000" :step="500" show-stops />
          <span>{{ createForm.word_count }} 字</span>
        </el-form-item>
        <el-form-item label="格式要求">
          <el-checkbox v-model="createForm.need_red_header">需要红头</el-checkbox>
          <el-checkbox v-model="createForm.need_signature">需要落款</el-checkbox>
          <el-checkbox v-model="createForm.need_date">需要日期</el-checkbox>
          <el-checkbox v-model="createForm.need_doc_number">需要文号</el-checkbox>
        </el-form-item>
        <el-divider content-position="left">关键词 / 补充说明</el-divider>
        <el-form-item label="补充说明">
          <el-input v-model="createForm.keywords" type="textarea" :rows="3" placeholder="给AI的额外指令，如：通知时间统一用2026年8月1日；通知对象是各区县司法局。非必填。" />
          <div class="form-hint">这些关键词会在生成时直接告诉AI，帮助控制输出细节</div>
        </el-form-item>
        <el-divider content-position="left">字段配置（可增删改）</el-divider>
        <div v-for="(field, idx) in createForm.params_schema" :key="idx" class="param-field-row">
          <el-input v-model="field.name" placeholder="字段名（英文）" style="width:120px" />
          <el-input v-model="field.label" placeholder="显示名称" style="width:140px" />
          <el-select v-model="field.type" style="width:100px">
            <el-option label="输入框" value="input" />
            <el-option label="多行文本" value="textarea" />
            <el-option label="下拉选择" value="select" />
          </el-select>
          <el-checkbox v-model="field.required">必填</el-checkbox>
          <el-button link type="danger" @click="removeParam(idx)">删除</el-button>
        </div>
        <el-button link type="primary" @click="addParam"><el-icon><Plus /></el-icon> 添加字段</el-button>
        <el-divider content-position="left">生成配置（高级）</el-divider>
        <el-form-item label="内容模板（可选）">
          <el-input v-model="createForm.content_template" type="textarea" :rows="4" placeholder="AI生成时的结构参考，不填则由AI自由发挥" />
        </el-form-item>
        <el-form-item label="系统提示词">
          <el-input v-model="createForm.system_prompt" type="textarea" :rows="4" placeholder="AI角色设定，通常由基础类型自动生成" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCreateTemplate" :loading="createLoading">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { View, Refresh, Plus, Edit, Delete } from '@element-plus/icons-vue'
import axios from 'axios'

const router = useRouter()
const token = ref(localStorage.getItem('token') || '')

const categories = ref([])
const templates = ref([])
const loading = ref(false)
const initing = ref(false)
const activeCategory = ref('')

const isAdmin = computed(() => {
  try {
    const user = JSON.parse(localStorage.getItem('user') || '{}')
    return ['developer', 'knowledge_admin', 'admin'].includes(user.role)
  } catch { return false }
})

// 官方模板
const filteredBuiltin = computed(() => {
  const list = templates.value.filter(t => t.is_builtin)
  if (!activeCategory.value) return list
  return list.filter(t => t.category === activeCategory.value)
})

// 自定义模板
const filteredCustom = computed(() => {
  const list = templates.value.filter(t => !t.is_builtin)
  if (!activeCategory.value) return list
  return list.filter(t => t.category === activeCategory.value)
})

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
    {name:'title',label:'请示事项',type:'input',required:true,placeholder:'如：关于申请经费的请示'},
    {name:'reason',label:'请示理由',type:'textarea',required:true,placeholder:'请简述背景和原因',rows:4},
    {name:'content',label:'申请内容',type:'textarea',required:true,placeholder:'请详细说明申请内容',rows:4},
    {name:'basis',label:'政策依据',type:'textarea',required:true,placeholder:'请列出政策依据',rows:3},
    {name:'suggestion',label:'拟办意见',type:'textarea',required:true,placeholder:'请简述拟办意见',rows:3}
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
  editingTemplateId.value = null
  createForm.value = {
    name: '', category: categories.value[0]?.name || '', base_type: '通知',
    description: '', icon: 'Document', content_template: '', system_prompt: '',
    writing_style: '正式公文', word_count: 1000,
    need_red_header: false, need_signature: true, need_date: true, need_doc_number: false,
    keywords: '', params_schema: []
  }
  onBaseTypeChange('通知')
  createDialogVisible.value = true
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

async function editTemplate(tmpl) {
  createForm.value = {
    name: tmpl.name,
    category: tmpl.category,
    base_type: tmpl.base_type || '其他',
    description: tmpl.description || '',
    icon: tmpl.icon || 'Document',
    content_template: tmpl.content_template || '',
    system_prompt: tmpl.system_prompt || '',
    writing_style: tmpl.writing_style || '正式公文',
    word_count: tmpl.word_count || 1000,
    need_red_header: tmpl.need_red_header || false,
    need_signature: tmpl.need_signature !== false,
    need_date: tmpl.need_date !== false,
    need_doc_number: tmpl.need_doc_number || false,
    keywords: tmpl.keywords || '',
    params_schema: tmpl.params_schema ? JSON.parse(JSON.stringify(tmpl.params_schema)) : []
  }
  editingTemplateId.value = tmpl.id
  createDialogVisible.value = true
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
  const map = {
    '计划总结': 'blue', '请示报告': 'orange',
    '通知公告': 'red', '调研报告': 'purple', '会议纪要': 'cyan',
    '情况汇报': 'pink', '执法文书': 'gray'
  }
  return map[category] || 'blue'
}
</script>

<style scoped>
.templates-page { padding: 24px; background: #f0f2f5; min-height: 100vh; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-header h2 { margin: 0; font-size: 22px; color: #303133; }
.subtitle { margin: 8px 0 0; font-size: 13px; color: #909399; }

/* 圆角 pill 分类导航 */
.category-nav { display: flex; align-items: center; gap: 8px; flex-wrap: nowrap; overflow-x: auto; padding-bottom: 4px; }
.category-nav::-webkit-scrollbar { height: 4px; }
.category-nav::-webkit-scrollbar-thumb { background: #c0c4cc; border-radius: 2px; }
.category-item { padding: 6px 14px; font-size: 13px; color: #606266; cursor: pointer; border-radius: 16px; transition: all 0.2s ease; white-space: nowrap; user-select: none; background: #f5f7fa; border: 1px solid transparent; }
.category-item:hover { color: #409EFF; background: #ecf5ff; border-color: #b3d8ff; }
.category-item.active { font-size: 13px; font-weight: 600; color: #fff; background: #409EFF; border-color: #409EFF; box-shadow: 0 2px 6px rgba(64,158,255,0.3); }

/* 分组标题 */
.section-title { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: #303133; padding: 20px 0 12px; margin-top: 8px; }
.section-icon { font-size: 16px; }
.section-badge { font-size: 12px; color: #909399; background: #f0f2f5; padding: 2px 10px; border-radius: 12px; font-weight: 400; }

/* 卡片 */
.template-card {
  position: relative;
  background: white;
  border-radius: 12px;
  border: 1px solid #ebeef5;
  display: flex;
  margin-bottom: 16px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94);
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  overflow: hidden;
}
.template-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0,0,0,0.10);
  border-color: #c0c4cc;
}

/* 左边缘色条 */
.card-accent {
  width: 4px;
  flex-shrink: 0;
  border-radius: 12px 0 0 12px;
}
.cat-blue .card-accent { background: #409EFF; }
.cat-green .card-accent { background: #67C23A; }
.cat-orange .card-accent { background: #E6A23C; }
.cat-red .card-accent { background: #F56C6C; }
.cat-purple .card-accent { background: #9B59B6; }
.cat-cyan .card-accent { background: #1ABC9C; }
.cat-pink .card-accent { background: #FF6B6B; }
.cat-gray .card-accent { background: #34495E; }

.card-main { flex: 1; padding: 16px 16px 12px 12px; min-width: 0; display: flex; flex-direction: column; }

/* 卡片头部 */
.card-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
.card-name { margin: 0; font-size: 16px; font-weight: 600; color: #303133; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-badge { flex-shrink: 0; }

/* 元信息 */
.card-meta { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #909399; margin-bottom: 8px; }
.card-meta .dot { color: #d0d0d0; }

/* 描述 */
.card-desc { font-size: 13px; color: #606266; line-height: 1.5; margin: 0 0 10px; min-height: 20px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }

/* 底部 */
.card-footer { display: flex; justify-content: space-between; align-items: center; padding-top: 10px; border-top: 1px solid #f0f2f5; margin-top: auto; }
.card-stats { display: flex; align-items: center; gap: 10px; font-size: 12px; color: #b0b0b0; }
.stat-item { display: flex; align-items: center; gap: 4px; }
.hot-badge { background: #FEF0E6; color: #E6A23C; padding: 0 8px; border-radius: 10px; font-size: 11px; line-height: 18px; }

/* 操作按钮：悬停才显示 */
.card-actions { display: flex; align-items: center; gap: 2px; opacity: 0; transition: opacity 0.25s; }
.template-card:hover .card-actions { opacity: 1; }
.card-actions .el-button { padding: 4px 6px; height: 28px; min-width: 28px; font-size: 14px; }

.header-right { display: flex; gap: 10px; }
.form-hint { font-size: 12px; color: #909399; margin-top: 4px; }
.param-field-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
</style>