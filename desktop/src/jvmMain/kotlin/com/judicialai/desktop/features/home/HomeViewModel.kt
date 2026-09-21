package com.judicialai.desktop.features.home

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.bool
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * 工作台（HOME）数据源：
 * - /dashboard/summary：真实姓名、部门、角色、待办数、AI 在线状态、最近文档
 * - /approvals?view=todo：待我审批的公文（前 5 条）
 * 全部来自后端；无任何本地假数据。
 */
class HomeViewModel {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var loading by mutableStateOf(true)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    var realName by mutableStateOf("")
        private set
    var department by mutableStateOf("")
        private set
    var roleName by mutableStateOf("")
        private set
    var aiOnline by mutableStateOf(false)
        private set
    var todoCount by mutableStateOf(0)
        private set

    /** 问候语按本地时间段生成（纯展示，不涉及业务数据） */
    val greeting: String
        get() {
            val h = java.time.LocalTime.now().hour
            return when {
                h < 6 -> "夜深了"
                h < 11 -> "上午好"
                h < 14 -> "中午好"
                h < 18 -> "下午好"
                else -> "晚上好"
            }
        }

    init { load() }

    fun load() {
        loading = true
        error = null
        scope.launch { loadSummary() }
        scope.launch { loadOrgContext() }
        loading = false
    }

    /** 科室归属 / Agent / 知识范围：全部由后端下发，前端不做任何推导 */
    private suspend fun loadOrgContext() {
        when (val r = AppState.api.get(Endpoints.Organization.ME)) {
            is ApiResult.Ok -> {
                val o = r.data.obj() ?: return
                AppState.departmentCode = o["dept_code"].str()
                AppState.departmentName = o["dept_name"].str().ifBlank { o["short_name"].str() }
                val agent = o["agent"].obj()
                AppState.agentName = agent?.get("name").str()
                AppState.agentIntro = agent?.get("intro").str()
                AppState.deptTasks = agent?.get("recommended_tasks").arr()
                    .map { it.str() }.filter { it.isNotBlank() }
                AppState.canManageDeptAgent = agent?.get("can_manage").bool()
                if (AppState.departmentName.isNotBlank()) department = AppState.departmentName
            }
            is ApiResult.Err -> Unit // 组织服务不可用时首页仍可用，不打断办公
        }
    }

    private suspend fun loadSummary() {
        when (val r = AppState.api.get(Endpoints.Dashboard.SUMMARY)) {
            is ApiResult.Ok -> {
                val o = r.data.obj() ?: return
                realName = o["real_name"].str().ifBlank { AppState.displayName }
                department = o["department"].str()
                AppState.departmentName = department
                AppState.departmentCode = o["department_code"].str()
                roleName = o["role_name"].str()
                aiOnline = o["ai_online"].bool()
                todoCount = o["todo_count"].int()
                AppState.todoCount = todoCount
            }
            is ApiResult.Err -> error = r.message
        }
    }

}
