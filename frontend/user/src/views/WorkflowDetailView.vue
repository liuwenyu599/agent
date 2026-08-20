<template>
  <div class="wf-cockpit" v-loading="loading">
    <!-- 头部 -->
    <div class="head-card">
      <div class="head-left">
        <div class="head-icon"><el-icon :size="26" color="#fff"><Calendar /></el-icon></div>
        <div>
          <div class="title-row">
            <span class="title">{{ inst.title }}</span>
            <el-button text size="small" @click="renameVisible = true"><el-icon><Edit /></el-icon></el-button>
            <el-tag :type="statusTag.type" effect="light">{{ statusTag.text }}</el-tag>
          </div>
          <div class="meta">
            创建时间：{{ inst.created_at || '—' }}　创建人：{{ inst.creator || '—' }}　主办部门：{{ inst.workflow_context?.organizer || '—' }}
          </div>
        </div>
      </div>
      <div class="head-mid">
        <span class="progress-label">整体进度</span>
        <el-progress :percentage="overallProgress" :stroke-width="8" style="width: 200px" />
        <b>{{ doneCount }} / {{ nodes.length }}</b>
        <span class="progress-pct">{{ overallProgress }}%</span>
      </div>
      <div class="head-right">
        <el-button v-if="inst.status === 'running'" @click="setStatus('draft')">暂停工作流</el-button>
        <el-button v-else-if="inst.status === 'draft'" type="primary" plain @click="setStatus('running')">继续工作流</el-button>
        <el-dropdown @command="onExport">
          <el-button type="primary" plain>导出全部材料<el-icon><ArrowDown /></el-icon></el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="all">导出全部（Word）</el-dropdown-item>
              <el-dropdown-item command="done">仅导出已完成成果</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-dropdown @command="onMore">
          <el-button>··· 更多</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="archive">归档</el-dropdown-item>
              <el-dropdown-item command="complete">标记整个工作流完成</el-dropdown-item>
              <el-dropdown-item command="delete" divided>删除工作流</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <div class="cockpit-row">
      <div class="cockpit-main">
        <!-- 工作流节点与成果（在基本信息上方） -->
        <div class="card">
          <div class="card-head">
            <span class="card-title">工作流节点与成果</span>
            <el-button size="small" text type="primary" @click="nodesCollapsed = !nodesCollapsed">
              {{ nodesCollapsed ? '展开' : '收起' }}
              <el-icon><ArrowUp v-if="!nodesCollapsed" /><ArrowDown v-else /></el-icon>
            </el-button>
          </div>
          <div v-show="!nodesCollapsed" class="node-grid">
            <div v-for="(n, i) in nodes" :key="n.id" class="node-card clickable" :class="[n.status, { post: isPostNode(n) }]" @click="openNode(n)">
              <div class="node-head">
                <span class="node-no" :class="n.status">{{ i + 1 }}</span>
                <span class="node-name">{{ n.name }}</span>
                <el-tag size="small" :type="nodeTag(n).type" effect="light">{{ nodeTag(n).text }}</el-tag>
              </div>
              <div class="node-desc">{{ n.write_guide || '—' }}</div>
              <div class="node-time" v-if="n.status === 'done' && n.updated_at">完成时间：{{ n.updated_at }}</div>
              <div class="node-time" v-else-if="!n.content">未开始</div>
              <div class="node-actions" @click.stop>
                <template v-if="n.content">
                  <el-button size="small" text type="primary" @click="exportNode(n)">下载</el-button>
                  <el-dropdown @command="cmd => onNodeMore(cmd, n)">
                    <el-button size="small">更多<el-icon><ArrowDown /></el-icon></el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="regen">重新生成</el-dropdown-item>
                        <el-dropdown-item v-if="n.status !== 'done'" command="done">确认完成</el-dropdown-item>
                        <el-dropdown-item command="clear" divided>清空内容</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </template>
                <span v-else class="node-open-hint">{{ isBasicNode(n) ? '点击卡片，AI协助确定' : '点击卡片进入填写' }}</span>
              </div>
              <div class="node-file" v-if="n.content">
                <el-icon color="#2b579a"><Document /></el-icon>
                {{ inst.title.slice(0, 8) }}-{{ n.name }}.docx
              </div>
            </div>
          </div>
          <div v-show="!nodesCollapsed" class="legend">
            <span><i class="dot done"></i>已完成</span>
            <span><i class="dot editing"></i>进行中</span>
            <span><i class="dot pending"></i>待生成</span>
            <span><i class="dot post"></i>会后节点</span>
          </div>
        </div>

        <!-- 基本信息 -->
        <div class="card">
          <div class="card-head">
            <span class="card-title">会议基本信息</span>
            <el-button size="small" text type="primary" @click="openBasicNode">
              <el-icon style="margin-right:2px"><MagicStick /></el-icon>AI协助完善
            </el-button>
          </div>
          <div class="basic-grid" v-if="basicEntries.length">
            <div v-for="[k, v] in basicEntries.slice(0, basicExpanded ? undefined : 8)" :key="k" class="basic-item">
              <el-icon color="#909399"><component :is="basicIcon(k)" /></el-icon>
              <span class="basic-key">{{ k }}</span>
              <span class="basic-val">{{ v }}</span>
            </div>
          </div>
          <el-empty v-else description="还没有会议信息，描述一下你的想法，AI 帮你整理" :image-size="56">
            <el-button size="small" type="primary" @click="openBasicNode">AI协助确定</el-button>
          </el-empty>
          <div v-if="basicEntries.length > 8" class="basic-more" @click="basicExpanded = !basicExpanded">
            {{ basicExpanded ? '收起' : '更多信息' }}
            <el-icon><ArrowDown v-if="!basicExpanded" /><ArrowUp v-else /></el-icon>
          </div>
        </div>
      </div>

      <!-- 右栏 -->
      <div class="cockpit-side">
        <div class="card">
          <div class="card-head">
            <span class="card-title"><el-icon color="#409eff"><MagicStick /></el-icon> AI工作助手</span>
          </div>
          <div class="ast-banner">
            我已分析当前会议情况<br>
            <small>当前还有 {{ pendingCount }} 项待完成任务</small>
          </div>
          <div class="ast-status">
            <div class="ast-status-title">当前状态</div>
            <div v-for="f in stdFieldStatus" :key="f.key" class="ast-status-item">
              <span :class="f.ok ? 'ast-ok' : 'ast-miss'">{{ f.ok ? '✓' : '△' }} {{ f.label }}{{ f.ok ? '已确定' : '尚未确定' }}</span>
            </div>
          </div>
          <div v-if="missingStdFields.length" class="ast-next-label" style="margin-top:10px">建议下一步</div>
          <el-button v-if="missingStdFields.length" size="small" type="warning" plain style="width: 100%; margin-bottom: 8px" @click="openBasicNode">
            补充{{ missingStdFields.slice(0, 3).join('、') }}{{ missingStdFields.length > 3 ? '等' : '' }}
          </el-button>
          <template v-if="nextNode && !isBasicNode(nextNode)">
            <div v-if="!missingStdFields.length" class="ast-next-label">建议下一步</div>
            <div class="ast-next-card">
              <div class="ast-next-info">
                <b>生成{{ nextNode.name }}</b>
                <small>{{ nextNode.write_guide }}</small>
              </div>
            </div>
            <el-button type="primary" plain style="width: 100%" :loading="genId === nextNode.id" @click="regen(nextNode)">开始生成</el-button>
          </template>
          <el-button v-else-if="nextNode && isBasicNode(nextNode)" type="primary" plain style="width: 100%" @click="openBasicNode">
            去确认会议基本信息
          </el-button>
          <div class="ast-quick">
            <el-button size="small" plain @click="quickAction('补充参会人员信息')">补充参会人员</el-button>
            <el-button size="small" plain @click="openBasicNode">完善会议信息</el-button>
            <el-button size="small" plain @click="quickAction('请参考知识库中去年同类会议的材料格式')">参考历史会议</el-button>
            <el-button size="small" plain :loading="batchRunning" @click="generateAll">一键生成后续材料</el-button>
          </div>
          <div class="ast-chat" ref="chatRef">
            <div v-for="(m, i) in aiMsgs" :key="i" class="ast-msg" :class="m.role">
              <div class="ast-bubble">{{ m.content }}</div>
            </div>
            <div v-if="aiThinking" class="ast-msg assistant"><div class="ast-bubble">思考中…</div></div>
          </div>
          <el-input v-model="aiInput" placeholder="告诉我你需要做什么…" @keyup.enter="sendAi">
            <template #append>
              <el-button text @click="sendAi"><el-icon><Promotion /></el-icon></el-button>
            </template>
          </el-input>
        </div>

        <div class="card">
          <div class="card-head">
            <span class="card-title">工作流动态</span>
            <el-button size="small" text type="primary" @click="feedExpanded = !feedExpanded">查看全部</el-button>
          </div>
          <el-timeline class="feed">
            <el-timeline-item v-for="(f, i) in feedShown" :key="i"
              :type="f.done ? 'success' : 'info'" :hollow="!f.done" :timestamp="f.time" placement="top">
              {{ f.name }}
              <el-tag v-if="f.done" size="small" type="success" effect="plain">已完成</el-tag>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-if="!feed.length" description="暂无动态" :image-size="56" />
        </div>
      </div>
    </div>

    <!-- 节点填写抽屉（页签式：节点内容 / 历史记录 / 关联材料 / 操作日志） -->
    <el-drawer v-model="nodeVisible" size="72%" destroy-on-close :with-header="false">
      <template v-if="editingNode">
        <!-- ============ 基础信息节点：AI 协助确定会议基本信息（不是表单） ============ -->
        <div v-if="isBasicNode(editingNode)" class="basic-ai-panel">
          <div class="nd-title-row">
            <span class="nd-title">会议基本信息</span>
            <el-tag size="small" :type="nodeTag(editingNode).type" effect="light">{{ nodeTag(editingNode).text }}</el-tag>
            <span class="nd-ai-badge"><el-icon><MagicStick /></el-icon> AI协助完善</span>
          </div>
          <div class="nd-guide">先告诉我你准备开什么会，不需要一次说完整。可以直接描述想法，也可以上传已有的通知、方案等材料，AI 会自动提取并补全。</div>

          <div class="bap-input-box">
            <el-input v-model="nlInput" type="textarea" :rows="4"
              placeholder='例如："下周想组织一次全局上半年工作总结会，主要是各科室汇报工作情况，局领导参加。"' />
            <div class="bap-input-bar">
              <el-upload :show-file-list="false" :auto-upload="false" :on-change="onMaterialPick">
                <el-button size="small" plain><el-icon><Upload /></el-icon> 上传材料</el-button>
              </el-upload>
              <span class="bap-tip">支持上传已有通知、方案等，作为 AI 提取依据</span>
            </div>
          </div>
          <el-button type="primary" size="large" class="bap-analyze-btn" :loading="nlParsing" @click="parseNaturalLanguageInput">
            <el-icon style="margin-right:6px"><MagicStick /></el-icon>AI 分析并完善
          </el-button>

          <div class="bap-result">
            <div class="bap-result-title">当前会议信息</div>
            <div class="bap-field" v-for="f in stdFieldStatus" :key="f.key">
              <span class="bap-label">{{ f.label }}</span>
              <span v-if="f.ok" class="bap-val">{{ ctxOf()[f.key] }}</span>
              <span v-else class="bap-miss">尚未确定</span>
            </div>
            <div class="bap-field" v-for="[k, val] in Object.entries(ctxOf()).filter(([k]) => !STD_FIELDS.some(([sk]) => sk === k))" :key="k">
              <span class="bap-label">{{ FIELD_LABEL_MAP[k] || k }}</span>
              <span class="bap-val">{{ val }}</span>
            </div>
          </div>

          <div v-if="missingStdFields.length && Object.keys(ctxOf()).length" class="bap-missing-tip">
            还缺少：{{ missingStdFields.join('、') }}。可以直接补充描述让 AI 继续完善，也可以先确认现有信息，后续再补。
          </div>

          <div class="nd-actions">
            <el-button size="large" @click="openBasicEdit">手动修改</el-button>
            <el-button size="large" type="primary" class="nd-gen-btn" @click="confirmBasicInfo">确认基本信息</el-button>
          </div>
        </div>

        <!-- ============ 普通节点：页签式编辑器 ============ -->
        <el-tabs v-else v-model="nodeTab">
          <el-tab-pane label="节点内容" name="content">
            <div class="nd-title-row">
              <span class="nd-title">{{ editingNode.name }}</span>
              <el-tag size="small" :type="nodeTag(editingNode).type" effect="light">{{ nodeTag(editingNode).text }}</el-tag>
            </div>
            <div class="nd-guide">{{ editingNode.write_guide }}</div>

            <!-- AI生成依据 -->
            <div class="ref-box">
              <div class="ref-col">
                <div class="ref-title">AI生成依据 · 会议基本信息</div>
                <div class="ref-item" v-for="f in stdFieldStatus" :key="f.key">
                  <el-icon v-if="f.ok" color="#67c23a"><CircleCheckFilled /></el-icon>
                  <el-icon v-else color="#e6a23c"><Warning /></el-icon>
                  {{ f.label }}：<span :class="{ 'ref-empty': !f.ok }">{{ f.ok ? ctxOf()[f.key] : '尚未确定' }}</span>
                </div>
              </div>
              <div class="ref-col">
                <div class="ref-title">前序成果（自动带入）</div>
                <div class="ref-item" v-for="u in upstreamOf(editingNode)" :key="u.id">
                  <el-icon color="#67c23a"><CircleCheckFilled /></el-icon>{{ u.name }}
                </div>
                <div v-if="!upstreamOf(editingNode).length" class="ref-item ref-empty">暂无前序已完成节点</div>
                <template v-if="nodeMaterials.length">
                  <div class="ref-title" style="margin-top:8px">关联材料</div>
                  <div class="ref-item" v-for="(m, i) in nodeMaterials" :key="'rm' + i">
                    <el-icon><Document /></el-icon>{{ m.name }}
                  </div>
                </template>
              </div>
            </div>
            <div v-if="missingStdFields.length" class="nd-warn">
              <el-icon color="#e6a23c"><Warning /></el-icon>
              {{ missingStdFields.join('、') }}尚未确定。可先生成草稿（对应位置以"××"占位），待信息确认后重新生成。
            </div>

            <!-- 编辑器 -->
            <div class="nd-toolbar">
              <el-button size="small" text @click="fmt('bold')"><b>B</b></el-button>
              <el-button size="small" text @click="fmt('italic')"><i>I</i></el-button>
              <el-button size="small" text @click="fmt('underline')"><u>U</u></el-button>
              <el-divider direction="vertical" />
              <el-button size="small" text @click="fmt('insertOrderedList')">有序列表</el-button>
              <el-button size="small" text @click="fmt('insertUnorderedList')">无序列表</el-button>
              <el-divider direction="vertical" />
              <el-button size="small" text type="primary" :loading="optimizing" @click="aiOptimize">AI优化</el-button>
            </div>
            <div ref="editorRef" class="nd-editor" contenteditable="true" @input="dirty = true"></div>

            <div class="nd-actions">
              <el-button type="primary" size="large" class="nd-gen-btn"
                :loading="genId === editingNode.id" @click="regen(editingNode, true)">
                <el-icon style="margin-right:6px"><MagicStick /></el-icon>AI 一键生成本节点正文
              </el-button>
              <el-button size="large" @click="saveNode" :loading="saving">保存草稿</el-button>
              <el-button size="large" type="success" plain @click="markDone(editingNode, true)">标记为完成</el-button>
            </div>
          </el-tab-pane>

          <el-tab-pane label="历史记录" name="history">
            <el-empty description="历史版本功能将在后续版本提供" />
          </el-tab-pane>

          <el-tab-pane label="关联材料" name="materials">
            <el-upload :show-file-list="false" :auto-upload="false" :on-change="onMaterialPick">
              <el-button type="primary" plain><el-icon><Upload /></el-icon>上传材料</el-button>
            </el-upload>
            <div class="mat-tip">上传后内容会作为本节点 AI 生成/优化的参考（走对话附件通道解析）</div>

            <div class="mat-group" v-if="nodeMaterials.length">
              <div class="mat-group-title">本节点上传</div>
              <div v-for="(m, i) in nodeMaterials" :key="'u' + i" class="mat-item">
                <el-icon><Document /></el-icon>
                <div class="mat-info">
                  <div>{{ m.name }}</div>
                  <small>{{ m.time }}<template v-if="m.status">　{{ m.status }}</template></small>
                </div>
              </div>
            </div>

            <div class="mat-group" v-if="editingNode.content">
              <div class="mat-group-title">本节点生成</div>
              <div class="mat-item">
                <el-icon color="#2b579a"><Document /></el-icon>
                <div class="mat-info">
                  <div>{{ inst.title.slice(0, 10) }}-{{ editingNode.name }}.{{ isTableNode(editingNode) ? 'xls' : 'docx' }}</div>
                  <small>{{ editingNode.updated_at || '' }}</small>
                </div>
                <el-button size="small" text type="primary" @click="exportNode(editingNode)">下载</el-button>
              </div>
            </div>

            <div class="mat-group" v-if="upstreamOf(editingNode).length">
              <div class="mat-group-title">前序成果（自动带入）</div>
              <div v-for="u in upstreamOf(editingNode)" :key="u.id" class="mat-item">
                <el-icon color="#67c23a"><Connection /></el-icon>
                <div class="mat-info">
                  <div>{{ u.name }}</div>
                  <small>{{ (u.content || '').slice(0, 40) }}…</small>
                </div>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="操作日志" name="logs">
            <el-empty description="操作日志功能将在后续版本提供" />
          </el-tab-pane>
        </el-tabs>
      </template>
    </el-drawer>

    <!-- 手动修改会议信息（AI 面板中的兜底入口） -->
    <el-dialog v-model="basicEditVisible" title="手动修改会议信息" width="520px">
      <el-input v-model="basicText" type="textarea" :rows="7"
        placeholder="每行一条，格式：键：值&#10;会议时间：2026-08-20（周三）09:00&#10;会议地点：局三楼会议室&#10;主持人：李明 副局长" />
      <template #footer>
        <el-button @click="basicEditVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveBasic">保存</el-button>
      </template>
    </el-dialog>

    <!-- 重命名 -->
    <el-dialog v-model="renameVisible" title="修改标题" width="420px">
      <el-input v-model="renameText" />
      <template #footer>
        <el-button @click="renameVisible = false">取消</el-button>
        <el-button type="primary" @click="saveRename">保存</el-button>
      </template>
    </el-dialog>
        <!-- 自然语言解析确认 -->
    <el-dialog v-model="nlConfirmVisible" title="AI识别到以下信息，请确认是否同步" width="480px">
      <div v-if="Object.keys(nlParsed).length">
        <div v-for="(v, k) in nlParsed" :key="k" class="nl-item">
          <span class="nl-label">{{ FIELD_LABEL_MAP[k] || k }}：</span>
          <span class="nl-val">{{ v }}</span>
        </div>
      </div>
      <el-empty v-else description="未识别到有效信息" />
      <template #footer>
        <el-button @click="nlConfirmVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmNaturalLanguage">确认同步</el-button>
      </template>
    </el-dialog>

    <!-- 键值对冲突确认 -->
    <el-dialog v-model="kvConflictVisible" title="检测到信息变更，请确认" width="480px">
      <div v-for="c in kvConflicts" :key="c.field" class="conflict-item">
        <div class="conflict-field">{{ c.label }}</div>
        <div class="conflict-row">
          <span class="conflict-old">原：{{ c.old_value }}</span>
          <el-icon><Right /></el-icon>
          <span class="conflict-new">新：{{ c.new_value }}</span>
        </div>
      </div>
      <template #footer>
        <el-button @click="kvConflictVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmOverrides">确认更新</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Calendar, Edit, ArrowDown, ArrowUp, MagicStick, Promotion,
  Document, Upload, Connection, Clock, Location, User, Flag, Aim,
  OfficeBuilding, CircleCheckFilled, Right, Warning,
} from '@element-plus/icons-vue'
import {
  getWorkflowInstance, updateWorkflowInstance, deleteWorkflowInstance,
  updateWorkflowNode, generateWorkflowNode,parseNaturalLanguage, parseKeyValue, confirmWorkflowContext,
} from '@/api/workflow.js'
import { sendChat } from '@/api/knowledge.js'
import { uploadChatAttachments } from '@/api/format_check.js'

const route = useRoute()
const router = useRouter()
const instId = route.params.id

const loading = ref(false)
const saving = ref(false)
const optimizing = ref(false)
const batchRunning = ref(false)
const inst = ref({ title: '', basic_info: {}, nodes: [] })
const genId = ref(null)
const basicExpanded = ref(false)
const nodesCollapsed = ref(false)
const feedExpanded = ref(false)
const basicEditVisible = ref(false)
const basicText = ref('')
const workflowContext = computed(() => inst.value.workflow_context || {})
const nlConfirmVisible = ref(false)
const nlParsed = ref({})
const nlInput = ref('')
const kvConflictVisible = ref(false)
const kvConflicts = ref([])
const kvParsed = ref({})
const renameVisible = ref(false)
const renameText = ref('')

const nodeVisible = ref(false)
const editingNode = ref(null)
const editorRef = ref(null)
const dirty = ref(false)
const nodeTab = ref('content')
const nodeMaterials = ref([])

const nodes = computed(() => (inst.value.nodes || []).slice().sort((a, b) => a.sort_order - b.sort_order))
const doneCount = computed(() => nodes.value.filter(n => n.status === 'done').length)
const pendingCount = computed(() => nodes.value.length - doneCount.value)
const overallProgress = computed(() => nodes.value.length ? Math.round(doneCount.value / nodes.value.length * 100) : 0)
const nextNode = computed(() => nodes.value.find(n => n.status !== 'done'))
const FIELD_LABEL_MAP = {
  meeting_name: '会议名称', meeting_time: '会议时间', meeting_location: '会议地点',
  organizer: '主办单位', host: '主持人', participants: '参会人员',
  purpose: '会议目的', topic: '会议主题',
}

const basicEntries = computed(() => {
  const ctx = inst.value.workflow_context || {}
  const entries = []
  const order = ['meeting_name', 'meeting_time', 'meeting_location', 'organizer', 'host', 'participants', 'purpose', 'topic']
  for (const key of order) {
    if (ctx[key]) entries.push([FIELD_LABEL_MAP[key] || key, ctx[key]])
  }
  for (const [k, v] of Object.entries(ctx)) {
    if (!order.includes(k) && v) entries.push([k, v])
  }
  return entries
})
const statusTag = computed(() => ({
  running: { text: '进行中', type: 'primary' },
  draft: { text: '已暂停', type: 'info' },
  completed: { text: '已完成', type: 'success' },
  archived: { text: '已归档', type: 'warning' },
}[inst.value.status] || { text: inst.value.status, type: 'info' }))

function isPostNode(n) { return (n.stage || '').includes('会后') }
// 基础信息节点 = 整个工作流的 AI 启动节点，状态语义是"确认"而非"生成"
function isBasicNode(n) { return /基础信息|基本信息/.test(n?.name || '') }
function nodeTag(n) {
  if (isBasicNode(n)) {
    if (n.status === 'done') return { text: '已确认', type: 'success' }
    if (nlParsing.value) return { text: 'AI整理中', type: 'warning' }
    return { text: '待确认', type: 'info' }
  }
  if (n.status === 'done') return { text: '已完成', type: 'success' }
  if (n.content || n.status === 'draft' || n.status === 'editing') return { text: '进行中', type: 'warning' }
  return isPostNode(n) ? { text: '待生成（会后）', type: 'info' } : { text: '待生成', type: 'info' }
}

// 会议标准字段：用于"当前状态"分析、缺失提醒、AI生成依据展示
const STD_FIELDS = [
  ['meeting_name', '会议名称'], ['meeting_time', '会议时间'], ['meeting_location', '会议地点'],
  ['organizer', '主办部门'], ['host', '主持人'], ['participants', '参会人员'],
  ['purpose', '会议目的'], ['topic', '会议主题'],
]
const ctxOf = () => inst.value.workflow_context || inst.value.basic_info || {}
const stdFieldStatus = computed(() =>
  STD_FIELDS.map(([key, label]) => ({ key, label, ok: !!(ctxOf()[key] && String(ctxOf()[key]).trim()) })))
const missingStdFields = computed(() => stdFieldStatus.value.filter(f => !f.ok).map(f => f.label))
const nlParsing = ref(false)

const ICON_MAP = { 时间: Clock, 地点: Location, 主持: User, 对象: User, 人员: User, 部门: OfficeBuilding, 主题: Flag, 目的: Aim }
function basicIcon(k) {
  for (const key of Object.keys(ICON_MAP)) if (k.includes(key)) return ICON_MAP[key]
  return Flag
}

const feed = computed(() => {
  const list = nodes.value
    .filter(n => n.status === 'done' && n.updated_at)
    .map(n => ({ name: n.name, time: n.updated_at, done: true }))
  list.push({ name: '工作流创建', time: inst.value.created_at || '', done: false })
  return list
})
const feedShown = computed(() => feedExpanded.value ? feed.value : feed.value.slice(0, 6))

async function loadInstance() {
  loading.value = true
  try {
    const { data } = await getWorkflowInstance(instId)
    inst.value = data
  } catch (e) {
    ElMessage.error('加载工作流失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

function upstreamOf(node) {
  return nodes.value.filter(n => n.sort_order < node.sort_order && n.content && n.content.trim())
}

// ---------- 工作流级操作 ----------
async function setStatus(s) {
  await updateWorkflowInstance(instId, { status: s })
  inst.value.status = s
  ElMessage.success(s === 'draft' ? '已暂停' : '已继续')
}
async function onMore(cmd) {
  if (cmd === 'archive') { await setStatus('archived') }
  else if (cmd === 'complete') {
    await ElMessageBox.confirm('确认整个工作流已完成？', '提示', { type: 'warning' })
    await setStatus('completed')
  } else if (cmd === 'delete') {
    await ElMessageBox.confirm('删除后不可恢复，确认删除该工作流？', '警告', { type: 'error' })
    await deleteWorkflowInstance(instId)
    ElMessage.success('已删除')
    router.push('/workflows')
  }
}

// ---------- 节点 ----------
function openNode(n) {
  editingNode.value = n
  nodeTab.value = 'content'
  nodeVisible.value = true
  dirty.value = false
  nodeMaterials.value = loadNodeMaterials(n.id)
  nextTick(() => nextTick(() => { if (editorRef.value) editorRef.value.innerText = n.content || '' }))
}
function loadNodeMaterials(nodeId) {
  try { return JSON.parse(localStorage.getItem(`wf_mats_${instId}_${nodeId}`) || '[]') } catch { return [] }
}
function saveNodeMaterials() {
  if (!editingNode.value) return
  localStorage.setItem(`wf_mats_${instId}_${editingNode.value.id}`, JSON.stringify(nodeMaterials.value))
}

function fmt(cmd) { document.execCommand(cmd); dirty.value = true }
function editorText() { return editorRef.value?.innerText || '' }

async function saveNode(silent = false) {
  if (!editingNode.value) return
  saving.value = true
  try {
    await updateWorkflowNode(editingNode.value.id, { content: editorText() })
    editingNode.value.content = editorText()
    if (editingNode.value.status === 'pending') editingNode.value.status = 'draft'
    dirty.value = false
    if (!silent) ElMessage.success('已保存')
  } catch (e) {
    if (!silent) ElMessage.error('保存失败：' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

async function regen(n, fromDrawer = false) {
  const { value } = await ElMessageBox.prompt(
    '补充生成要求（可留空，如"按照去年同类会议的格式"）', `AI生成「${n.name}」`,
    { confirmButtonText: '开始生成', cancelButtonText: '取消' },
  ).catch(() => ({ value: null }))
  if (value === null) return
  genId.value = n.id
  try {
    const { data } = await generateWorkflowNode(n.id, value || '')
    n.content = data.content || ''
    n.status = data.status || 'draft'
    ElMessage.success(`「${n.name}」已生成`)
    if (fromDrawer && editorRef.value) { editorRef.value.innerText = n.content; dirty.value = false }
    else if (!fromDrawer && !nodeVisible.value) openNode(n)
  } catch (e) {
    ElMessage.error('生成失败：' + (e.response?.data?.detail || e.message))
  } finally {
    genId.value = null
  }
}

async function aiOptimize() {
  if (!editorText().trim()) return ElMessage.warning('请先填写内容')
  optimizing.value = true
  try {
    const { data } = await generateWorkflowNode(
      editingNode.value.id,
      '在不改变事实的前提下优化以下内容的格式与表达：\n' + editorText(),
      false,
    )
    if (editorRef.value) editorRef.value.innerText = data.content || editorText()
    dirty.value = true
    ElMessage.success('已优化，满意请点"保存草稿"')
  } catch (e) {
    ElMessage.error('优化失败')
  } finally {
    optimizing.value = false
  }
}

async function generateAll() {
  await ElMessageBox.confirm(
    `将对剩余 ${pendingCount.value} 项逐一调用 AI 生成（前序成果自动带入上下文），耗时较长，确认开始？`,
    '一键生成后续材料', { type: 'warning' },
  )
  batchRunning.value = true
  for (const n of nodes.value) {
    if (n.status === 'done' || n.content) continue
    genId.value = n.id
    try {
      const { data } = await generateWorkflowNode(n.id, '')
      n.content = data.content || ''
      n.status = data.status || 'draft'
    } catch (e) {
      ElMessage.error(`「${n.name}」生成失败，已跳过`)
    }
  }
  genId.value = null
  batchRunning.value = false
  ElMessage.success('批量生成完成，请逐项检查确认')
}

async function markDone(n, closeDrawer = false) {
  if (closeDrawer && dirty.value) await saveNode(true)
  try {
    await updateWorkflowNode(n.id, { status: 'done' })
    n.status = 'done'
    ElMessage.success(`「${n.name}」已完成`)
    if (closeDrawer) nodeVisible.value = false
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

function onNodeMore(cmd, n) {
  if (cmd === 'regen') regen(n)
  else if (cmd === 'download') exportNode(n)
  else if (cmd === 'done') markDone(n)
  else if (cmd === 'clear') {
    ElMessageBox.confirm('确定清空本节点内容？', '提示', { type: 'warning' }).then(async () => {
      await updateWorkflowNode(n.id, { content: '', status: 'pending' })
      n.content = ''
      n.status = 'pending'
    }).catch(() => {})
  }
}

// ---------- 材料上传 ----------
async function onMaterialPick(file) {
  const item = { name: file.name, time: new Date().toLocaleString('zh-CN', { hour12: false }), status: '上传中…' }
  nodeMaterials.value.push(item)
  try {
    await uploadChatAttachments([file.raw])
    item.status = '已上传，已纳入参考'
    saveNodeMaterials()
    ElMessage.success('材料已上传并解析')
  } catch (e) {
    item.status = '上传失败'
    ElMessage.error('上传失败：' + (e.response?.data?.detail || e.message))
  }
}

// ---------- 导出 ----------
function exportDoc(title, bodyHtml) {
  const html = `<html xmlns:w="urn:schemas-microsoft-com:office:word"><head><meta charset="utf-8"></head><body>${bodyHtml}</body></html>`
  const blob = new Blob(['﻿' + html], { type: 'application/msword' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `${title}.doc`
  a.click()
  URL.revokeObjectURL(a.href)
}

// 表格类节点（签到表/名单/清单/分工）：内容按行解析为表格，导出 Excel
function isTableNode(n) { return /签到|名单|清单|分工/.test(n.name || '') }
function parseRows(text) {
  return (text || '').split('\n')
    .map(l => l.trim()).filter(Boolean)
    .map(l => l.split(/\t|\||，|,|\s{2,}/).map(s => s.trim()).filter(s => s !== ''))
    .filter(r => r.length)
}
function tableData(n, text) {
  let rows = parseRows(text)
  if (!rows.length) return null
  // 首行像表头（含"姓名/序号/名称/项目"等）则用作表头
  let headers = null
  if (/姓名|序号|名称|项目|职务|单位/.test(rows[0].join(''))) headers = rows.shift()
  if (!headers) {
    headers = (n.name || '').includes('签到')
      ? ['序号', '姓名', '单位', '职务', '联系电话', '签到']
      : ['序号', '内容', '备注']
  }
  // 签到表首列不是数字序号时自动补序号
  if ((n.name || '').includes('签到')) {
    rows = rows.map((r, i) => /^\d+$/.test(r[0] || '') ? r : [String(i + 1), ...r])
  }
  return { headers, rows }
}
function tableHtml(n, text) {
  const t = tableData(n, text)
  if (!t) return `<p>${(text || '').replace(/\n/g, '<br>')}</p>`
  const th = t.headers.map(h => `<th style="border:1px solid #000;padding:6px 10px;background:#f2f2f2;">${h}</th>`).join('')
  const trs = t.rows.map(r =>
    '<tr>' + t.headers.map((_, i) => `<td style="border:1px solid #000;padding:6px 10px;">${r[i] || ''}</td>`).join('') + '</tr>'
  ).join('')
  return `<table style="border-collapse:collapse;width:100%;"><tr>${th}</tr>${trs}</table>`
}
function exportExcel(title, n, text) {
  const html = `<html xmlns:x="urn:schemas-microsoft-com:office:excel"><head><meta charset="utf-8"></head><body>${tableHtml(n, text)}</body></html>`
  const blob = new Blob(['﻿' + html], { type: 'application/vnd.ms-excel' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `${title}.xls`
  a.click()
  URL.revokeObjectURL(a.href)
}
function exportNode(n) {
  const text = (editingNode.value === n && editorRef.value) ? editorText() : n.content
  if (!text) return ElMessage.warning('该节点暂无内容')
  if (isTableNode(n)) return exportExcel(`${inst.value.title}-${n.name}`, n, text)
  exportDoc(`${inst.value.title}-${n.name}`, `<h2>${n.name}</h2><p>${text.replace(/\n/g, '<br>')}</p>`)
}
function onExport(cmd) {
  const parts = nodes.value.filter(n => n.content && (cmd === 'all' || n.status === 'done'))
  if (!parts.length) return ElMessage.warning('暂无可导出内容')
  const body = parts.map(n =>
    `<h2>${n.name}</h2>` + (isTableNode(n) ? tableHtml(n, n.content) : `<p>${n.content.replace(/\n/g, '<br>')}</p>`)
  ).join('<br style="page-break-before:always">')
  exportDoc(`${inst.value.title}-材料汇编`, body)
}
// ---------- 基本信息 / workflow_context ----------
function openBasicEdit() {
  const ctx = inst.value.workflow_context || {}
  basicText.value = Object.entries(ctx)
    .map(([k, v]) => `${FIELD_LABEL_MAP[k] || k}：${v}`)
    .join('\n')
  basicEditVisible.value = true
}

async function saveBasic() {
  const { data } = await parseKeyValue(instId, basicText.value)
  if (data.has_conflict) {
    kvConflicts.value = data.conflicts
    kvParsed.value = data.parsed
    kvConflictVisible.value = true
    return
  }
  await doSaveContext(data.parsed)
}

async function doSaveContext(ctxPart, confirmOverrides = {}) {
  saving.value = true
  try {
    const { data } = await confirmWorkflowContext(instId, ctxPart, confirmOverrides)
    inst.value.workflow_context = data.workflow_context
    inst.value.basic_info = data.workflow_context
    basicEditVisible.value = false
    kvConflictVisible.value = false
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error('保存失败：' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

async function confirmOverrides() {
  const overrides = {}
  for (const c of kvConflicts.value) {
    overrides[c.field] = true
  }
  await doSaveContext(kvParsed.value, overrides)
}
// 自然语言输入 → AI 提取会议信息
async function parseNaturalLanguageInput() {
  if (!nlInput.value.trim()) return ElMessage.warning('请先描述一下你准备开的会')
  nlParsing.value = true
  try {
    const { data } = await parseNaturalLanguage(instId, nlInput.value.trim())
    nlParsed.value = data.parsed || {}
    if (!Object.keys(nlParsed.value).length) {
      ElMessage.warning('未能识别出有效信息，请再补充一些描述（如时间、参会范围）')
      return
    }
    nlConfirmVisible.value = true
  } catch (e) {
    ElMessage.error('AI 分析失败：' + (e.response?.data?.detail || e.message))
  } finally {
    nlParsing.value = false
  }
}

async function confirmNaturalLanguage() {
  await doSaveContext(nlParsed.value)
  nlInput.value = ''
}

// 打开"基础信息"节点的 AI 入口（AI助手/快捷按钮共用）
function openBasicNode() {
  const n = nodes.value.find(x => isBasicNode(x))
  if (n) openNode(n)
}

// 确认会议基本信息：把当前上下文固化为节点成果，状态置为"已确认"
async function confirmBasicInfo() {
  const n = editingNode.value
  const ctx = ctxOf()
  if (!Object.keys(ctx).length) return ElMessage.warning('请先让 AI 分析或手动补充会议信息')
  const text = Object.entries(ctx).map(([k, val]) => `${FIELD_LABEL_MAP[k] || k}：${val}`).join('\n')
  try {
    await updateWorkflowNode(n.id, { content: text, status: 'done' })
    n.content = text
    n.status = 'done'
    ElMessage.success('会议基本信息已确认，后续节点将以此为依据生成')
    nodeVisible.value = false
  } catch (e) {
    ElMessage.error('确认失败：' + (e.response?.data?.detail || e.message))
  }
}

async function saveRename() {
  if (!renameText.value.trim()) return
  await updateWorkflowInstance(instId, { title: renameText.value.trim() })
  inst.value.title = renameText.value.trim()
  renameVisible.value = false
  ElMessage.success('已修改')
}

// ---------- AI 助手 ----------
const aiMsgs = ref([])
const aiInput = ref('')
const aiThinking = ref(false)
const chatRef = ref(null)
function quickAction(text) { aiInput.value = text; sendAi() }
async function sendAi() {
  const q = aiInput.value.trim()
  if (!q) return
  aiMsgs.value.push({ role: 'user', content: q })
  aiInput.value = ''
  aiThinking.value = true
  scrollChat()
  try {
    const statusText = nodes.value.map(n =>
      `${n.name}（${{ pending: '待生成', draft: '草稿', editing: '编辑中', done: '已完成' }[n.status] || n.status}）`).join('、')
    const ctx = `【工作流】${inst.value.title}
【工作流上下文】${JSON.stringify(inst.value.workflow_context || {})}
【节点状态】${statusText}
【我的要求】${q}

请站在整个工作流的角度回答；涉及具体材料时直接给出可用内容或明确操作建议。`
    const { data } = await sendChat({ message: ctx })
    aiMsgs.value.push({ role: 'assistant', content: data.reply || data.message || '（无回复）' })
  } catch (e) {
    aiMsgs.value.push({ role: 'assistant', content: '助手暂时不可用：' + (e.response?.data?.detail || e.message) })
  } finally {
    aiThinking.value = false
    scrollChat()
  }
}
function scrollChat() {
  nextTick(() => { const el = chatRef.value; if (el) el.scrollTop = el.scrollHeight })
}

// 离开页面前自动保存抽屉里的草稿
onBeforeRouteLeave(async () => {
  if (dirty.value && editingNode.value) await saveNode(true)
})

onMounted(loadInstance)
</script>

<style scoped>
.wf-cockpit { padding: 16px 20px; }

.head-card {
  background: #fff; border: 1px solid #ebeef5; border-radius: 12px;
  padding: 16px 20px; margin-bottom: 14px;
  display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
}
.head-left { display: flex; gap: 14px; align-items: center; flex: 1; min-width: 280px; }
.head-icon {
  width: 48px; height: 48px; border-radius: 10px; background: #2f5cff;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.title-row { display: flex; align-items: center; gap: 6px; }
.title { font-size: 20px; font-weight: 700; }
.meta { color: #909399; font-size: 12px; margin-top: 4px; }
.head-mid { display: flex; align-items: center; gap: 10px; }
.progress-label { font-size: 13px; color: #606266; }
.progress-pct { color: #909399; font-size: 13px; }
.head-right { display: flex; gap: 10px; }

.cockpit-row { display: flex; gap: 14px; align-items: flex-start; }
.cockpit-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 14px; }
.cockpit-side { width: 340px; flex-shrink: 0; display: flex; flex-direction: column; gap: 14px; }

.card { background: #fff; border: 1px solid #ebeef5; border-radius: 12px; padding: 16px 18px; }
.card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.card-title { font-weight: 700; font-size: 15px; display: flex; align-items: center; gap: 6px; }

.basic-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 30px; }
.basic-item { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.basic-key { color: #909399; white-space: nowrap; }
.basic-val { color: #303133; }
.basic-more { text-align: center; color: #2f5cff; font-size: 13px; margin-top: 12px; cursor: pointer; }

.node-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 12px; }
.node-card {
  border: 1.5px solid #ebeef5; border-radius: 10px; padding: 14px;
  display: flex; flex-direction: column; gap: 8px;
}
.node-card.clickable { cursor: pointer; transition: all .15s; }
.node-card.clickable:hover { border-color: #2f5cff; box-shadow: 0 2px 10px rgba(47,92,255,.1); }
.node-open-hint { font-size: 12px; color: #c0c4cc; }
.node-card.done { border-color: #b3e19d; }
.node-card.editing, .node-card.draft { border-color: #f5c26b; }
.node-card.post { border-style: dashed; }
.node-head { display: flex; align-items: center; gap: 8px; }
.node-no {
  width: 24px; height: 24px; line-height: 24px; text-align: center;
  border-radius: 50%; background: #c0c4cc; color: #fff; font-size: 13px; flex-shrink: 0;
}
.node-no.done { background: #67c23a; }
.node-no.draft, .node-no.editing { background: #e6a23c; }
.node-name { font-weight: 600; font-size: 14px; flex: 1; }
.node-desc { font-size: 12px; color: #909399; line-height: 1.6; }
.node-time { font-size: 12px; color: #a8abb2; }
.node-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.node-file {
  display: flex; align-items: center; gap: 6px;
  background: #f5f7fa; border-radius: 6px; padding: 6px 10px;
  font-size: 12px; color: #606266;
}
.legend { display: flex; gap: 20px; justify-content: center; margin-top: 16px; font-size: 12px; color: #909399; }
.legend .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; }
.dot.done { background: #67c23a; } .dot.editing { background: #e6a23c; }
.dot.pending { background: #c0c4cc; } .dot.post { background: #2f5cff; }

.ast-banner {
  background: linear-gradient(135deg, #eef3ff, #f6f9ff);
  border: 1px solid #d9e5ff; border-radius: 8px;
  padding: 12px 14px; font-size: 13px; line-height: 1.8; margin-bottom: 12px;
}
.ast-banner small { color: #909399; }
.ast-next-label { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
.ast-next-card { border: 1px solid #ebeef5; border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; }
.ast-next-info b { font-size: 13px; display: block; }
.ast-next-info small { color: #909399; font-size: 12px; }
.ast-quick { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 10px 0; }
.ast-quick .el-button { margin: 0; }
.ast-chat { height: 220px; overflow-y: auto; border-top: 1px solid #f2f3f5; padding: 8px 0; }
.ast-msg { display: flex; margin: 6px 0; }
.ast-msg.user { justify-content: flex-end; }
.ast-bubble {
  max-width: 88%; padding: 8px 12px; border-radius: 8px;
  font-size: 13px; line-height: 1.7; white-space: pre-wrap; background: #f4f4f5;
}
.ast-msg.user .ast-bubble { background: #ecf5ff; }

.feed :deep(.el-timeline-item__timestamp) { font-size: 12px; }

/* 节点填写抽屉 */
.nd-title-row { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.nd-title { font-size: 17px; font-weight: 700; }
.nd-guide { color: #909399; font-size: 13px; margin-bottom: 12px; }
.ref-box {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
  background: #fafafa; border: 1px solid #f0f0f0; border-radius: 8px;
  padding: 12px 14px; margin-bottom: 14px;
}
.ref-title { font-weight: 600; font-size: 13px; margin-bottom: 6px; }
.ref-item { font-size: 13px; color: #606266; line-height: 1.9; display: flex; align-items: center; gap: 4px; }
.ref-empty { color: #a8abb2; }
.nd-toolbar {
  display: flex; align-items: center; gap: 2px; padding: 4px 8px;
  border: 1px solid #dcdfe6; border-bottom: none; border-radius: 8px 8px 0 0; background: #fafafa;
}
.nd-editor {
  min-height: 44vh; max-height: 54vh; overflow-y: auto;
  border: 1px solid #dcdfe6; border-radius: 0 0 8px 8px;
  padding: 14px 16px; outline: none; font-size: 14px; line-height: 2; white-space: pre-wrap;
}
.nd-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px; }
.nd-gen-btn { flex: 1; font-size: 15px; font-weight: 600; }
.mat-tip { color: #909399; font-size: 12px; margin: 10px 0; }
.mat-group { margin-bottom: 14px; }
.mat-group-title { font-size: 12px; color: #909399; margin-bottom: 4px; }
.mat-item {
  display: flex; gap: 10px; align-items: center; padding: 10px 6px;
  border-bottom: 1px solid #f2f3f5;
}
.mat-info { font-size: 13px; flex: 1; }
.mat-info small { color: #909399; }

/* 缺失信息提醒 */
.nd-warn {
  display: flex; align-items: center; gap: 6px;
  background: #fdf6ec; border: 1px solid #faecd8; border-radius: 8px;
  padding: 8px 12px; font-size: 13px; color: #b88230; margin-bottom: 12px;
}

/* AI助手-当前状态 */
.ast-status { background: #fafafa; border: 1px solid #f0f0f0; border-radius: 8px; padding: 10px 12px; margin-bottom: 4px; }
.ast-status-title { font-size: 12px; color: #909399; margin-bottom: 4px; }
.ast-status-item { font-size: 13px; line-height: 1.9; }
.ast-ok { color: #67c23a; }
.ast-miss { color: #e6a23c; }

/* 基础信息节点的 AI 入口面板 */
.basic-ai-panel { display: flex; flex-direction: column; gap: 14px; }
.nd-ai-badge {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 12px; color: #2f5cff; background: #eef3ff;
  border-radius: 10px; padding: 2px 10px;
}
.bap-input-box { border: 1px solid #dcdfe6; border-radius: 10px; overflow: hidden; }
.bap-input-box :deep(.el-textarea__inner) { border: none; box-shadow: none; }
.bap-input-bar {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px; background: #fafafa; border-top: 1px solid #f0f0f0;
}
.bap-tip { font-size: 12px; color: #a8abb2; }
.bap-analyze-btn { align-self: center; min-width: 260px; font-size: 15px; font-weight: 600; }
.bap-result { border: 1px solid #ebeef5; border-radius: 10px; padding: 14px 18px; }
.bap-result-title { font-weight: 700; font-size: 14px; margin-bottom: 8px; }
.bap-field { display: flex; gap: 14px; font-size: 14px; line-height: 2.1; }
.bap-label { width: 80px; color: #909399; flex-shrink: 0; }
.bap-val { color: #303133; }
.bap-miss { color: #c0c4cc; }
.bap-missing-tip { font-size: 13px; color: #b88230; background: #fdf6ec; border-radius: 8px; padding: 10px 12px; line-height: 1.8; }
.nl-item { display: flex; padding: 8px 0; border-bottom: 1px solid #f2f3f5; }
.nl-label { color: #909399; width: 100px; flex-shrink: 0; }
.nl-val { color: #303133; font-weight: 500; }
.conflict-item { padding: 12px; background: #f5f7fa; border-radius: 8px; margin-bottom: 10px; }
.conflict-field { font-weight: 600; margin-bottom: 6px; }
.conflict-row { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.conflict-old { color: #f56c6c; text-decoration: line-through; }
.conflict-new { color: #67c23a; font-weight: 500; }
</style>