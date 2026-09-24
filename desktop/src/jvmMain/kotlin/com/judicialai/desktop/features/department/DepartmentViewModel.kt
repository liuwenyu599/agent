package com.judicialai.desktop.features.department

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.bool
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * 科室空间（v3.2）
 *
 * 定位：本科室的「资源空间」，不是 Agent 选择器。
 * 用户不给选择 Agent，进入即按 department_code 自动绑定智能助手，
 * 这里只聚合五块内容：智能助手 / 常用业务 / 知识资源 / 本科室模板 / 工作流程。
 *
 * 全部由服务端按登录用户解析（/organization/space），客户端不传 dept_code。
 * 界面不出现模型、检索范围、系统提示等技术概念。
 */
class DepartmentViewModel {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    data class AgentInfo(
        val name: String,
        val intro: String,
        val manager: String,
        val recommendedTasks: List<String>,
        val templates: List<String>,
        val version: Int,
        val canManage: Boolean,
        // 以下仅科室管理员 / 系统管理员可见，用于维护本科室业务层
        val businessPrompt: String = "",
        val workRequirements: String = "",
        val kbIds: List<String> = emptyList(),
        val editableFields: List<String> = emptyList(),
    )

    data class BusinessItem(val id: String, val title: String, val hint: String)

    data class KnowledgeItem(
        val id: String, val name: String, val description: String, val docCount: Int,
    )

    data class TemplateItem(
        val id: String, val name: String, val category: String, val description: String,
    )

    data class VersionItem(
        val version: Int, val operator: String, val note: String, val createdAt: String,
    )

    /** 本科室可用工作流程（/workflow/templates，服务端按登录用户范围返回） */
    data class WorkflowItem(
        val code: String, val name: String, val description: String,
        val category: String, val nodeCount: Int,
    )

    var loading by mutableStateOf(true)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var status by mutableStateOf<String?>(null)
        private set

    var deptCode by mutableStateOf("")
        private set
    var deptName by mutableStateOf("")
        private set

    var agent by mutableStateOf<AgentInfo?>(null)
        private set
    var business by mutableStateOf(listOf<BusinessItem>())
        private set
    var knowledge by mutableStateOf(listOf<KnowledgeItem>())
        private set
    var templates by mutableStateOf(listOf<TemplateItem>())
        private set
    var workflows by mutableStateOf(listOf<WorkflowItem>())
        private set

    /** 维护面板：只有后端下发 can_manage = true 才允许打开 */
    var maintaining by mutableStateOf(false)
    var versions by mutableStateOf(listOf<VersionItem>())
        private set
    var saving by mutableStateOf(false)
        private set

    // ---- 维护表单（仅业务层，系统层与安全层由后端保留，前端不可编辑）----
    var formIntro by mutableStateOf("")
    var formManager by mutableStateOf("")
    var formBusinessPrompt by mutableStateOf("")
    var formRequirements by mutableStateOf("")
    // 推荐任务 / 关联模板 / 关联资源：勾选选择（值为任务文案 / 模板名称 / 知识库 ID）
    var formTasksSel by mutableStateOf(setOf<String>())
    var formTemplatesSel by mutableStateOf(setOf<String>())
    var formKbIdsSel by mutableStateOf(setOf<String>())

    init { load() }

    fun load() {
        loading = true
        error = null
        scope.launch {
            when (val r = AppState.api.get(Endpoints.Organization.SPACE)) {
                is ApiResult.Ok -> apply(r.data.obj())
                is ApiResult.Err -> error = r.message
            }
            loading = false
        }
        // 本科室工作流程列表：加载失败只留空列表，不影响科室空间主体
        scope.launch {
            when (val r = AppState.api.get(Endpoints.Workflow.TEMPLATES)) {
                is ApiResult.Ok -> workflows = r.data.items().map { t ->
                    WorkflowItem(
                        code = t["code"].str().ifBlank { t["id"].str() },
                        name = t["name"].str(),
                        description = t["description"].str(),
                        category = t["category"].str(),
                        nodeCount = t["nodes"].arr().size,
                    )
                }.filter { it.name.isNotBlank() }
                is ApiResult.Err -> Unit
            }
        }
    }

    private fun apply(o: kotlinx.serialization.json.JsonObject?) {
        if (o == null) return
        deptCode = o["dept_code"].str()
        deptName = o["dept_name"].str().ifBlank { o["short_name"].str() }
        AppState.departmentCode = deptCode
        if (deptName.isNotBlank()) AppState.departmentName = deptName

        business = o["business"].arr().mapNotNull { it.obj() }.map { b ->
            BusinessItem(
                id = b["id"].str(),
                title = b["title"].str(),
                hint = b["hint"].str(),
            )
        }
        knowledge = o["knowledge"].arr().mapNotNull { it.obj() }.map { k ->
            KnowledgeItem(
                id = k["id"].str(),
                name = k["name"].str(),
                description = k["description"].str(),
                docCount = k["doc_count"].int(),
            )
        }
        templates = o["templates"].arr().mapNotNull { it.obj() }.map { t ->
            TemplateItem(
                id = t["id"].str(),
                name = t["name"].str(),
                category = t["category"].str(),
                description = t["description"].str(),
            )
        }

        val a = o["agent"].obj()
        agent = if (a == null) null else AgentInfo(
            name = a["name"].str().ifBlank { "智能助手" },
            intro = a["intro"].str(),
            manager = a["manager"].str(),
            recommendedTasks = a["recommended_tasks"].arr().map { it.str() }
                .filter { it.isNotBlank() },
            templates = a["templates"].arr().map { it.str() }.filter { it.isNotBlank() },
            version = a["version"].int(),
            canManage = a["can_manage"].bool(),
            businessPrompt = a["business_prompt"].str(),
            workRequirements = a["work_requirements"].str(),
            kbIds = a["kb_ids"].arr().map { it.str() }.filter { it.isNotBlank() },
            editableFields = a["editable_fields"].arr().map { it.str() },
        )
        AppState.agentName = agent?.name.orEmpty()
        AppState.agentIntro = agent?.intro.orEmpty()
        AppState.deptTasks = agent?.recommendedTasks.orEmpty()
        AppState.canManageDeptAgent = agent?.canManage ?: false
        resetForm()
    }

    private fun resetForm() {
        val a = agent ?: return
        formIntro = a.intro
        formManager = a.manager
        formBusinessPrompt = a.businessPrompt
        formRequirements = a.workRequirements
        formTasksSel = a.recommendedTasks.toSet()
        formTemplatesSel = a.templates.toSet()
        formKbIdsSel = a.kbIds.toSet()
    }

    fun toggleTask(v: String) {
        formTasksSel = if (v in formTasksSel) formTasksSel - v else formTasksSel + v
    }

    fun toggleTemplate(v: String) {
        formTemplatesSel = if (v in formTemplatesSel) formTemplatesSel - v else formTemplatesSel + v
    }

    fun toggleKb(v: String) {
        formKbIdsSel = if (v in formKbIdsSel) formKbIdsSel - v else formKbIdsSel + v
    }

    fun openMaintain() {
        resetForm()
        maintaining = true
        loadVersions()
    }

    fun closeMaintain() {
        maintaining = false
        status = null
    }

    private fun loadVersions() {
        if (deptCode.isBlank()) return
        scope.launch {
            when (val r = AppState.api.get(Endpoints.Organization.agentVersions(deptCode))) {
                is ApiResult.Ok -> versions = r.data.items().map { v ->
                    VersionItem(
                        version = v["version"].int(),
                        operator = v["operator_name"].str(),
                        note = v["change_note"].str(),
                        createdAt = v["created_at"].str(),
                    )
                }
                is ApiResult.Err -> Unit
            }
        }
    }

    /** 保存本科室业务配置：只提交业务层字段，系统层与安全层由后端保留 */
    fun save() {
        val code = deptCode
        if (code.isBlank()) return
        saving = true
        status = null
        val body = mapOf(
            "intro" to formIntro,
            "manager" to formManager,
            "business_prompt" to formBusinessPrompt,
            "work_requirements" to formRequirements,
            "tasks" to formTasksSel.toList(),
            "templates" to formTemplatesSel.toList(),
            "kb_ids" to formKbIdsSel.toList(),
        )
        scope.launch {
            when (val r = AppState.api.put(Endpoints.Organization.agent(code), body)) {
                is ApiResult.Ok -> {
                    status = "已保存，智能助手配置已生效"
                    load()
                    loadVersions()
                }
                is ApiResult.Err -> status = r.message
            }
            saving = false
        }
    }
}
