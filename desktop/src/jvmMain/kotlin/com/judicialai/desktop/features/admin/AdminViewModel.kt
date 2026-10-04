package com.judicialai.desktop.features.admin

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import java.io.File

class AdminViewModel(private val repo: AdminRepository) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    /**
     * 是否系统管理员（developer / admin）。
     *
     * 决定两件事：
     * 1. 操作成功后的刷新范围 —— /knowledge/stats 与 /users/ 都是 require_developer，
     *    科室管理员无条件 loadAll() 会被 403 把「审核完成」覆盖成「System admin required」，
     *    用户看到的就是「点了报错」；
     * 2. 「＋ 新建知识库」里能否选择公共库（服务端限制公共库仅系统管理员可建）。
     */
    var systemAdmin by mutableStateOf(true)

    var userCount by mutableStateOf(0); private set
    var docCount by mutableStateOf(0); private set
    var sessionCount by mutableStateOf(0); private set
    var kbCount by mutableStateOf(0); private set

    var users by mutableStateOf(listOf<JsonObject>()); private set
    var kbs by mutableStateOf(listOf<JsonObject>()); private set
    var pendingDocs by mutableStateOf(listOf<JsonObject>()); private set
    var publishedDocs by mutableStateOf(listOf<JsonObject>()); private set
    var rejectedDocs by mutableStateOf(listOf<JsonObject>()); private set
    /** 已归档：归档不是删除，必须能列出来、能恢复，否则「归档」等于数据消失 */
    var archivedDocs by mutableStateOf(listOf<JsonObject>()); private set

    /** 科室字典：来自 /organization/departments，只允许下拉选择 */
    var departments by mutableStateOf(listOf<JsonObject>()); private set

    var status by mutableStateOf<String?>(null)
    var busy by mutableStateOf(false); private set

    // ---- 批量导入用户（Excel / CSV）----
    var importBusy by mutableStateOf(false); private set
    /** 最近一次导入结果（total/succeeded/failed/results[]），展示后由用户关闭 */
    var importResult by mutableStateOf<JsonObject?>(null); private set

    // ============ 加载（suspend 版供「操作后刷新」复用，错误以返回值上报）============

    private suspend fun reloadStats(): String? = when (val r = repo.stats()) {
        is ApiResult.Ok -> {
            userCount = r.data["user_count"].int()
            docCount = r.data["doc_count"].int()
            sessionCount = r.data["session_count"].int()
            kbCount = r.data["kb_count"].int()
            null
        }
        is ApiResult.Err -> r.message
    }

    private suspend fun reloadUsers(): String? = when (val r = repo.users()) {
        is ApiResult.Ok -> { users = r.data; null }
        is ApiResult.Err -> r.message
    }

    private suspend fun reloadKbs(): String? = when (val r = repo.kbs()) {
        is ApiResult.Ok -> { kbs = r.data; null }
        is ApiResult.Err -> r.message
    }

    private suspend fun reloadDocs(): String? {
        when (val r = repo.pendingDocs()) {
            is ApiResult.Ok -> pendingDocs = r.data
            is ApiResult.Err -> return r.message
        }
        when (val r = repo.docsByStatus("published")) {
            is ApiResult.Ok -> publishedDocs = r.data
            is ApiResult.Err -> Unit
        }
        when (val r = repo.docsByStatus("rejected")) {
            is ApiResult.Ok -> rejectedDocs = r.data
            is ApiResult.Err -> Unit
        }
        when (val r = repo.docsByStatus("archived")) {
            is ApiResult.Ok -> archivedDocs = r.data
            is ApiResult.Err -> Unit
        }
        return null
    }

    private suspend fun reloadDepartments(): String? = when (val r = repo.departments()) {
        is ApiResult.Ok -> { departments = r.data; null }
        is ApiResult.Err -> r.message
    }

    fun loadStats() = scope.launch { reloadStats()?.let { status = it } }
    fun loadUsers() = scope.launch { reloadUsers()?.let { status = it } }
    fun loadKbs() = scope.launch { reloadKbs()?.let { status = it } }
    fun loadDocs() = scope.launch { reloadDocs()?.let { status = it } }
    fun loadDepartments() = scope.launch { reloadDepartments()?.let { status = it } }

    fun loadAll() {
        loadStats(); loadUsers(); loadKbs(); loadDocs()
        loadDepartments()
    }

    /**
     * 操作成功后的刷新：只刷当前角色有权访问的数据，返回失败原因（无则 null）。
     *
     * 刷新失败不直接写 [status]，交由 [act] 决定如何与成功提示合并 —— 否则科室
     * 管理员点「通过」会先看到「审核完成」、再被越权 403 覆盖成「操作失败」。
     */
    private suspend fun refreshScoped(): String? {
        if (systemAdmin) {
            return reloadStats() ?: reloadUsers() ?: reloadKbs()
                ?: reloadDocs() ?: reloadDepartments()
        }
        return reloadKbs() ?: reloadDocs()
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

    /**
     * 统一的写操作壳：防重复提交 + 成功提示不被刷新错误覆盖。
     *
     * 旧实现有两个问题：
     * 1. 成功后无条件 [loadAll()]，越权的 403 会顶掉成功提示；
     * 2. [busy] 从不复位前不加锁，连点会重复提交同一动作。
     */
    private fun act(message: String = "操作成功", block: suspend () -> ApiResult<*>) {
        if (busy) return
        busy = true
        scope.launch {
            status = when (val r = block()) {
                is ApiResult.Ok -> {
                    val refreshErr = refreshScoped()
                    if (refreshErr.isNullOrBlank()) message
                    else "$message（列表刷新失败：$refreshErr）"
                }
                is ApiResult.Err -> r.message.ifBlank { "操作失败" }
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

    /**
     * 批量导入用户（.xlsx / .csv）。
     * 初始密码缺省 123456，所有批量创建用户首次登录强制改密（服务端处理）。
     */
    fun importUsers(file: File) {
        if (importBusy) return
        importBusy = true
        importResult = null
        scope.launch {
            when (val r = repo.batchImportUsers(file)) {
                is ApiResult.Ok -> {
                    importResult = r.data.obj()
                    status = "批量导入完成"
                    reloadUsers()?.let { status = "批量导入完成（列表刷新失败：$it）" }
                }
                is ApiResult.Err -> status = r.message
            }
            importBusy = false
        }
    }

    fun clearImportResult() { importResult = null }

    fun updateUser(id: String, realName: String, departmentCode: String, role: String) =
        act("修改成功") {
            repo.updateUser(id, mapOf("real_name" to realName,
                "department_code" to departmentCode, "role" to role))
        }

    fun toggleUser(id: String, active: Boolean) =
        act(if (active) "已启用" else "已禁用") { repo.updateUser(id, mapOf("is_active" to active)) }

    fun resetPassword(id: String, password: String) =
        act("密码重置成功") { repo.resetPassword(id, password) }

    fun deleteUser(id: String) = act("已删除用户") { repo.deleteUser(id) }

    /**
     * 新建知识库。
     *
     * [type] 必须显式传：服务端缺省是 personal（只有创建者自己可见），管理后台
     * 里建库若不指定类型，会建出一个别人都看不见的私人库。
     */
    fun createKb(name: String, description: String, type: String) =
        act("知识库已创建") { repo.createKb(name, description, type) }

    fun deleteKb(id: String) = act("已删除") { repo.deleteKb(id) }

    fun review(docId: String, action: String, comment: String) =
        act(if (action == "approved") "已通过" else "已驳回") {
            repo.review(docId, action, comment.trim())
        }

    fun archive(docId: String) = act("已归档") { repo.archive(docId) }

    /** 恢复归档：归档是退出检索范围，不是删除，必须留一条回来的路 */
    fun unarchive(docId: String) = act("已恢复发布") { repo.unarchive(docId) }
}
