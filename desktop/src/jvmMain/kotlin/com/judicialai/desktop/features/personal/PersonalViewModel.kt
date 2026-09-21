package com.judicialai.desktop.features.personal

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.serialization.json.JsonObject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/** 个人中心分区：全部来自后端真实接口，无本地假数据 */
enum class PersonalSection(val title: String) {
    TODO("我的待办"),
    RECENT("最近使用"),
    DOCS("我的文档"),
    MY_APPROVALS("我的审批"),
    FAVORITES("我的收藏"),
    SETTINGS("个人设置"),
}

/**
 * 个人中心数据源：
 * - 我的待办：GET /approvals?view=todo
 * - 我的审批：GET /approvals?view=mine
 * - 最近使用：GET /dashboard/summary → recent
 * - 我的文档：GET /documents
 * - 我的收藏：后端当前无通用收藏接口，展示说明而不是伪造列表
 */
class PersonalViewModel {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    data class TodoItem(
        val id: String, val title: String, val stepName: String,
        val submitter: String, val submittedAt: String, val statusName: String,
    )

    data class DocItem(val id: String, val title: String, val status: String, val updatedAt: String)

    var section by mutableStateOf(PersonalSection.TODO)
        private set

    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    var todos by mutableStateOf(listOf<TodoItem>())
        private set
    var mine by mutableStateOf(listOf<TodoItem>())
        private set
    var recent by mutableStateOf(listOf<DocItem>())
        private set
    var docs by mutableStateOf(listOf<DocItem>())
        private set

    /** 待办数量：与顶部 Header 计数同源，取后端真实值 */
    var todoCount by mutableStateOf(0)
        private set

    fun select(section: PersonalSection) {
        this.section = section
        if (section != PersonalSection.FAVORITES && section != PersonalSection.SETTINGS) load()
    }

    fun load() {
        loading = true
        error = null
        scope.launch { loadApprovals() }
        scope.launch { loadRecent() }
        scope.launch { loadDocs() }
        loading = false
    }

    private suspend fun loadApprovals() {
        when (val r = AppState.api.get(Endpoints.Approvals.LIST,
                mapOf("view" to "todo", "page" to "1", "page_size" to "50"))) {
            is ApiResult.Ok -> {
                todos = r.data.obj()?.get("items").arr().mapNotNull { it.obj() }.map(::toTodo)
            }
            is ApiResult.Err -> error = r.message
        }
        when (val r = AppState.api.get(Endpoints.Approvals.LIST,
                mapOf("view" to "mine", "page" to "1", "page_size" to "50"))) {
            is ApiResult.Ok -> {
                mine = r.data.obj()?.get("items").arr().mapNotNull { it.obj() }.map(::toTodo)
            }
            is ApiResult.Err -> Unit
        }
        todoCount = todos.size
        if (todoCount > 0) AppState.todoCount = todoCount
    }

    private fun toTodo(o: JsonObject): TodoItem = TodoItem(
        id = o["id"].str(),
        title = o["title"].str().ifBlank { "未命名公文" },
        stepName = o["current_step_name"].str(),
        submitter = o["submitter_name"].str(),
        submittedAt = o["submitted_at"].str().take(16).replace("T", " "),
        statusName = o["current_status_name"].str(),
    )

    private suspend fun loadRecent() {
        when (val r = AppState.api.get(Endpoints.Dashboard.SUMMARY)) {
            is ApiResult.Ok -> {
                val o = r.data.obj() ?: return
                recent = o["recent"].arr().mapNotNull { it.obj() }.map { d ->
                    DocItem(
                        id = d["id"].str(),
                        title = d["title"].str().ifBlank { "未命名文档" },
                        status = d["status"].str(),
                        updatedAt = d["updated_at"].str().take(16).replace("T", " "),
                    )
                }
                val c = o["todo_count"].int()
                if (c > 0) AppState.todoCount = c
            }
            is ApiResult.Err -> Unit
        }
    }

    private suspend fun loadDocs() {
        when (val r = AppState.api.get(Endpoints.Documents.LIST,
                mapOf("page" to "1", "page_size" to "50"))) {
            is ApiResult.Ok -> {
                val root = r.data.obj()
                val list = (root?.get("items") ?: root?.get("data")).arr()
                docs = list.mapNotNull { it.obj() }.map { d ->
                    DocItem(
                        id = d["id"].str(),
                        title = d["title"].str().ifBlank { "未命名文档" },
                        status = d["status"].str(),
                        updatedAt = d["updated_at"].str().take(16).replace("T", " "),
                    )
                }
            }
            is ApiResult.Err -> Unit
        }
    }
}
