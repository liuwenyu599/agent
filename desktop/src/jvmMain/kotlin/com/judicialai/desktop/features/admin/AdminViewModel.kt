package com.judicialai.desktop.features.admin

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.int
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
    var sessions by mutableStateOf(listOf<JsonObject>()); private set

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

    fun loadSessions() = scope.launch {
        when (val r = repo.adminSessions()) {
            is ApiResult.Ok -> sessions = r.data
            is ApiResult.Err -> status = r.message
        }
    }

    fun loadAll() {
        loadStats(); loadUsers(); loadKbs(); loadDocs(); loadSessions()
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

    fun createUser(username: String, email: String, password: String, realName: String, department: String, role: String) =
        act("创建成功") {
            repo.createUser(mapOf("username" to username, "email" to email, "password" to password,
                "real_name" to realName, "department" to department, "role" to role))
        }

    fun updateUser(id: String, realName: String, department: String, role: String) =
        act("修改成功") {
            repo.updateUser(id, mapOf("real_name" to realName, "department" to department, "role" to role))
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

    fun deleteSession(id: String) = act("已删除") { repo.deleteSession(id) }
}

