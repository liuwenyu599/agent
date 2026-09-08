package com.judicialai.desktop.features.writing

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.bool
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.features.chat.model.ChatAttachment
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import java.io.File

/** 工作台对话消息 */
data class TaskChatMessage(val role: String, val content: String)

/**
 * 写作任务状态（对应后端 task_context）。
 * 所有字段的权威来源是后端返回；前端字段可编辑，编辑后 PATCH 同步回后端。
 */
data class WritingTaskState(
    val taskId: String? = null,
    val documentType: String = "",
    val title: String = "",
    val topic: String = "",
    val purpose: String = "",
    val timeRange: String = "",
    val recipient: String = "",
    val authority: String = "",
    val keyFacts: List<String> = emptyList(),
    val requirements: String = "",
    val tone: String = "",
    val wordCountTarget: Int = 0,
    val documentNumberEnabled: Boolean = false,
    val documentNumber: String = "",
    val documentDate: String = "",
    val missingFields: List<String> = emptyList(),
)

class WritingViewModel(private val repo: WritingRepository) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var task by mutableStateOf(WritingTaskState())
        private set
    var content by mutableStateOf("")
    var versionNo by mutableStateOf(0)
        private set
    var status by mutableStateOf<String?>(null)
    var taskStatus by mutableStateOf("collecting")
        private set

    var messages by mutableStateOf(listOf<TaskChatMessage>())
        private set
    var chatInput by mutableStateOf("")
    var materials by mutableStateOf(listOf<ChatAttachment>())
        private set
    var references by mutableStateOf(listOf<String>())
        private set
    var versions by mutableStateOf(listOf<JsonObject>())
        private set
    var busy by mutableStateOf(false)
        private set

    /** 零门槛入口输入 */
    var entryInput by mutableStateOf("")

    val hasTask: Boolean get() = task.taskId != null
    val hasDraft: Boolean get() = content.isNotBlank()

    // ---------------- 状态装载 ----------------

    private fun applyResponse(d: JsonObject) {
        val ctx = d["task_context"].obj() ?: return
        task = WritingTaskState(
            taskId = d["task_id"].str().ifBlank { task.taskId },
            documentType = ctx["document_type"].str(),
            title = ctx["title"].str(),
            topic = ctx["topic"].str(),
            purpose = ctx["purpose"].str(),
            timeRange = ctx["time_range"].str(),
            recipient = ctx["recipient"].str(),
            authority = ctx["authority"].str(),
            keyFacts = ctx["key_facts"].arr().map { it.str() }.filter { it.isNotBlank() },
            requirements = ctx["requirements"].str(),
            tone = ctx["tone"].str(),
            wordCountTarget = ctx["word_count_target"].int(),
            documentNumberEnabled = ctx["document_number_enabled"].bool(),
            documentNumber = ctx["document_number"].str(),
            documentDate = ctx["document_date"].str(),
            missingFields = ctx["missing_fields"].arr().map { it.str() }.filter { it.isNotBlank() },
        )
        d["current_content"].str().takeIf { it.isNotBlank() }?.let { content = it }
        versionNo = d["version_no"].int()
        taskStatus = d["status"].str().ifBlank { taskStatus }
        d["references"].arr().map { it.str() }.filter { it.isNotBlank() }
            .takeIf { it.isNotEmpty() }?.let { references = it }
        if (d["content_changed"].bool()) refreshVersions()
    }

    private fun fail(msg: String) {
        status = msg
        busy = false
    }

    // ---------------- 入口 ----------------

    /** 一句话启动任务 */
    fun startFromIntent() {
        val text = entryInput.trim()
        if (text.isBlank() || busy) return
        busy = true
        status = null
        messages = messages + TaskChatMessage("user", text)
        scope.launch {
            when (val r = repo.createTask(text)) {
                is ApiResult.Ok -> {
                    r.data?.let { d ->
                        applyResponse(d)
                        d["reply"].str().takeIf { it.isNotBlank() }
                            ?.let { messages = messages + TaskChatMessage("assistant", it) }
                    }
                    entryInput = ""
                }
                is ApiResult.Err -> fail(r.message)
            }
            busy = false
        }
    }

    // ---------------- 任务内对话 ----------------

    /** 用户在工作台持续对话（补要素 / 起草 / 自然语言修改都由后端决策） */
    fun sendChat() {
        val text = chatInput.trim()
        val id = task.taskId
        if (text.isBlank() || busy || id == null) return
        busy = true
        messages = messages + TaskChatMessage("user", text)
        chatInput = ""
        scope.launch {
            when (val r = repo.chat(id, text)) {
                is ApiResult.Ok -> {
                    r.data?.let { d ->
                        applyResponse(d)
                        d["reply"].str().takeIf { it.isNotBlank() }
                            ?.let { messages = messages + TaskChatMessage("assistant", it) }
                    }
                }
                is ApiResult.Err -> fail(r.message)
            }
            busy = false
        }
    }

    // ---------------- 起草 / 修改 ----------------

    fun draft(outlineOnly: Boolean = false) {
        val id = task.taskId ?: return
        if (busy) return
        busy = true
        scope.launch {
            when (val r = repo.draft(id, outlineOnly)) {
                is ApiResult.Ok -> r.data?.let { d ->
                    applyResponse(d)
                    d["reply"].str().takeIf { it.isNotBlank() }
                        ?.let { messages = messages + TaskChatMessage("assistant", it) }
                }
                is ApiResult.Err -> fail(r.message)
            }
            busy = false
        }
    }

    /**
     * AI 修改当前文档（快捷按钮与自然语言共用同一后端 revision 逻辑）。
     * mode: expand/polish/condense/normalize/complete/rewrite/revise
     */
    fun revise(instruction: String, mode: String) {
        val id = task.taskId ?: return
        if (busy || !hasDraft) return
        busy = true
        scope.launch {
            when (val r = repo.revise(id, instruction, mode, content)) {
                is ApiResult.Ok -> r.data?.let { d ->
                    applyResponse(d)
                    d["reply"].str().takeIf { it.isNotBlank() }
                        ?.let { messages = messages + TaskChatMessage("assistant", it) }
                }
                is ApiResult.Err -> fail(r.message)
            }
            busy = false
        }
    }

    // ---------------- 字段编辑同步 ----------------

    /** 用户手改左侧字段后同步后端 */
    fun patchContext(patch: Map<String, Any?>) {
        val id = task.taskId ?: return
        scope.launch {
            when (val r = repo.patchContext(id, patch)) {
                is ApiResult.Ok -> r.data?.let { applyResponse(it) }
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun toggleDocNumber(enabled: Boolean) {
        task = task.copy(documentNumberEnabled = enabled,
            documentNumber = if (enabled) task.documentNumber else "")
        patchContext(mapOf(
            "document_number_enabled" to enabled,
            "document_number" to if (enabled) task.documentNumber else null,
        ))
    }

    fun setDocNumber(number: String) {
        task = task.copy(documentNumber = number)
        patchContext(mapOf("document_number" to number.ifBlank { null },
            "document_number_enabled" to number.isNotBlank()))
    }

    // ---------------- 材料 ----------------

    fun uploadMaterials(files: List<File>) {
        if (files.isEmpty() || busy) return
        busy = true
        status = "上传材料中…"
        scope.launch {
            when (val r = repo.uploadMaterials(files)) {
                is ApiResult.Ok -> {
                    materials = materials + r.data
                    status = "已上传 ${r.data.size} 份材料，将随下次起草/修改提供给 AI"
                }
                is ApiResult.Err -> fail(r.message)
            }
            busy = false
        }
    }

    // ---------------- 版本 / 导出 / 训练 ----------------

    fun saveVersion(note: String? = null) {
        val id = task.taskId ?: return
        if (busy || !hasDraft) return
        busy = true
        scope.launch {
            when (val r = repo.saveVersion(id, content, note)) {
                is ApiResult.Ok -> {
                    r.data?.let { applyResponse(it) }
                    status = "已保存版本 v$versionNo"
                    refreshVersions()
                }
                is ApiResult.Err -> fail(r.message)
            }
            busy = false
        }
    }

    fun refreshVersions() {
        val id = task.taskId ?: return
        scope.launch {
            when (val r = repo.listVersions(id)) {
                is ApiResult.Ok -> versions = r.data
                is ApiResult.Err -> {}
            }
        }
    }

    fun export(redHeader: Boolean, target: File) {
        val id = task.taskId ?: return
        if (busy || !hasDraft) return
        busy = true
        status = "导出 Word 中…"
        scope.launch {
            when (val r = repo.export(id, redHeader, target)) {
                is ApiResult.Ok -> status = "已导出：${target.name}"
                is ApiResult.Err -> fail(r.message)
            }
            busy = false
        }
    }

    fun addToTraining() {
        val id = task.taskId ?: return
        if (busy || !hasDraft) return
        busy = true
        scope.launch {
            when (val r = repo.addToTraining(id, content)) {
                is ApiResult.Ok -> status = "已加入训练候选样本（待审核）"
                is ApiResult.Err -> fail(r.message)
            }
            busy = false
        }
    }

    fun newTask() {
        task = WritingTaskState()
        content = ""
        versionNo = 0
        taskStatus = "collecting"
        messages = emptyList()
        materials = emptyList()
        references = emptyList()
        versions = emptyList()
        entryInput = ""
        chatInput = ""
        status = null
    }
}
