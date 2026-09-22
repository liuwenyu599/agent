package com.judicialai.desktop.features.admin

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject

class AdminViewModel(private val repo: AdminRepository) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var userCount by mutableStateOf(0); private set
    var docCount by mutableStateOf(0); private set
    var sessionCount by mutableStateOf(0); private set
    var kbCount by mutableStateOf(0); private set

    var users by mutableStateOf(listOf<JsonObject>()); private set
    var kbs by mutableStateOf(listOf<JsonObject>()); private set
    var pendingDocs by mutableStateOf(listOf<JsonObject>()); private set
    var publishedDocs by mutableStateOf(listOf<JsonObject>()); private set
    var rejectedDocs by mutableStateOf(listOf<JsonObject>()); private set

    /** 科室字典：来自 /organization/departments，只允许下拉选择 */
    var departments by mutableStateOf(listOf<JsonObject>()); private set

    var status by mutableStateOf<String?>(null)
    var busy by mutableStateOf(false); private set

    fun loadStats() {
        scope.launch {
            when (val r = repo.stats()) {
                is ApiResult.Ok -> {
                    userCount = r.data["user_count"].int()
                    docCount = r.data["doc_count"].int()
                    sessionCount = r.data["session_count"].int()
                    kbCount = r.data["kb_count"].int()
                }
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun loadUsers() = scope.launch {
        when (val r = repo.users()) {
            is ApiResult.Ok -> users = r.data
            is ApiResult.Err -> status = r.message
        }
    }

    fun loadKbs() = scope.launch {
        when (val r = repo.kbs()) {
            is ApiResult.Ok -> kbs = r.data
            is ApiResult.Err -> status = r.message
        }
    }

    fun loadDocs() = scope.launch {
        when (val r = repo.pendingDocs()) {
            is ApiResult.Ok -> pendingDocs = r.data
            is ApiResult.Err -> status = r.message
        }
        when (val r = repo.docsByStatus("published")) {
            is ApiResult.Ok -> publishedDocs = r.data
            is ApiResult.Err -> Unit
        }
        when (val r = repo.docsByStatus("rejected")) {
            is ApiResult.Ok -> rejectedDocs = r.data
            is ApiResult.Err -> Unit
        }
    }

    fun loadDepartments() = scope.launch {
        when (val r = repo.departments()) {
            is ApiResult.Ok -> departments = r.data
            is ApiResult.Err -> status = r.message
        }
    }

    fun loadAll() {
        loadStats(); loadUsers(); loadKbs(); loadDocs()
        loadDepartments()
    }

    /** 可选角色：与后端 assignable 角色一致（user / knowledge_admin / developer） */
    fun roleOptions(actorRole: String): List<Pair<String, String>> = when (actorRole) {
        "developer" -> listOf("user" to "普通用户", "knowledge_admin" to "科室管理员",
            "developer" to "系统管理员")
        "knowledge_admin" -> listOf("user" to "普通用户", "knowledge_admin" to "科室管理员")
        else -> emptyList()
    }

    fun roleLabel(role: String) = when (role) {
        "developer" -> "系统管理员"
        "knowledge_admin" -> "科室管理员"
        "user" -> "普通用户"
        else -> "普通用户"
    }

    fun deptLabel(code: String): String {
        val d = departments.firstOrNull { it["code"].str() == code }
        return d?.get("name").str().ifBlank { d?.get("short_name").str() }
    }

    private fun act(message: String = "操作成功", block: suspend () -> ApiResult<*>) {
        busy = true
        scope.launch {
            when (val r = block()) {
                is ApiResult.Ok -> { status = message; loadAll() }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    fun createUser(username: String, email: String, password: String, realName: String,
                   departmentCode: String, role: String) =
        act("创建成功") {
            repo.createUser(mapOf("username" to username, "email" to email, "password" to password,
                "real_name" to realName, "department_code" to departmentCode, "role" to role))
        }

    fun updateUser(id: String, realName: String, departmentCode: String, role: String) =
        act("修改成功") {
            repo.updateUser(id, mapOf("real_name" to realName,
                "department_code" to departmentCode, "role" to role))
        }

    fun toggleUser(id: String, active: Boolean) =
        act("操作成功") { repo.updateUser(id, mapOf("is_active" to active)) }

    fun resetPassword(id: String, password: String) =
        act("密码重置成功") { repo.resetPassword(id, password) }

    fun deleteKb(id: String) = act("已删除") { repo.deleteKb(id) }

    fun review(docId: String, action: String) =
        act("审核完成") {
            repo.review(docId, action, if (action == "approved") "审核通过" else "不符合要求")
        }

    fun archive(docId: String) = act("已归档") { repo.archive(docId) }
}
