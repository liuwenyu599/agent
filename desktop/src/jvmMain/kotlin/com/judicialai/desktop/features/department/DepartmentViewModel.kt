package com.judicialai.desktop.features.department

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * 科室空间：组织架构 + 科室 Agent 配置。
 * 可见科室、Agent 简介、知识范围全部由后端下发（后端按 department_id 强隔离），
 * 前端不做任何本地推导或补白。
 */
class DepartmentViewModel {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    data class Dept(
        val code: String,
        val name: String,          // 正式名称
        val shortName: String,     // 简称（UI 日常显示）
        val memberCount: Int = 0,
        val kbCount: Int = 0,
        val templateCount: Int = 0,
        val isMine: Boolean = false,
    )

    data class Agent(
        val deptCode: String,
        val deptName: String,
        val name: String,            // 如「复议科 Agent」
        val intro: String,
        val model: String,           // 底层模型（统一 Qwen 服务）
        val scopes: List<String>,    // 允许的知识范围，如 GLOBAL / DEPT:fuli
        val recommendedTasks: List<String>,
        val templates: List<String>,
        val manager: String,
    )

    var loading by mutableStateOf(true)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    var departments by mutableStateOf(listOf<Dept>())
        private set
    var agents by mutableStateOf(mapOf<String, Agent>())
        private set
    var selectedCode by mutableStateOf<String?>(null)
        private set

    val selected: Dept? get() = departments.firstOrNull { it.code == selectedCode }
    val selectedAgent: Agent? get() = selectedCode?.let { agents[it] }

    init { load() }

    fun load() {
        loading = true
        error = null
        scope.launch {
            when (val r = AppState.api.get(Endpoints.Organization.LIST)) {
                is ApiResult.Ok -> {
                    departments = r.data.items().map { o ->
                        Dept(
                            code = o["code"].str(),
                            name = o["name"].str(),
                            shortName = o["short_name"].str().ifBlank { o["name"].str() },
                            memberCount = o["member_count"].int(),
                            kbCount = o["kb_count"].int(),
                            templateCount = o["template_count"].int(),
                            isMine = o["is_mine"].str() == "true" || o["is_mine"].int() == 1,
                        )
                    }.sortedWith(compareBy({ !it.isMine }, { it.code }))
                    val mine = departments.firstOrNull { it.isMine } ?: departments.firstOrNull()
                    selectedCode = mine?.code ?: selectedCode
                    if (selectedCode != null) loadAgent(selectedCode!!)
                }
                is ApiResult.Err -> error = r.message
            }
            loading = false
        }
    }

    fun select(code: String) {
        selectedCode = code
        if (!agents.containsKey(code)) loadAgent(code)
    }

    private fun loadAgent(code: String) {
        scope.launch {
            when (val r = AppState.api.get(Endpoints.Organization.agent(code))) {
                is ApiResult.Ok -> {
                    val o = r.data.obj() ?: return@launch
                    agents = agents + (code to Agent(
                        deptCode = code,
                        deptName = o["dept_name"].str(),
                        name = o["name"].str().ifBlank { "科室 Agent" },
                        intro = o["intro"].str(),
                        model = o["model"].str(),
                        scopes = o["scopes"].arr().map { it.str() },
                        recommendedTasks = o["recommended_tasks"].arr().map { it.str() },
                        templates = o["templates"].arr().map { it.str() },
                        manager = o["manager"].str(),
                    ))
                }
                is ApiResult.Err -> Unit // 未配置 Agent 时不阻塞展示科室列表
            }
        }
    }
}
