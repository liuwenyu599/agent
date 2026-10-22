package com.judicialai.desktop.features.writing

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.bool
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.features.chat.model.ChatAttachment
import kotlinx.serialization.json.JsonObject
import java.io.File
import java.security.MessageDigest

private fun contentHash(content: String): String =
    MessageDigest.getInstance("SHA-256")
        .digest(content.toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it.toInt() and 0xff) }

data class WritingAgentProgress(
    val type: String,
    val runId: String = "",
    val route: String = "",
    val key: String = "",
    val label: String = "",
    val status: String = "",
    val qualityLevel: String = "",
    val issueCount: Int = 0,
    val repairRound: Int = 0,
)

/**
 * 智能写作工作台数据访问（/writing/tasks 系列接口）。
 * 任务 = 结构化上下文 + 当前文档 + 持续对话 + 版本链，全部行为落在后端。
 */
class WritingRepository(private val api: ApiClient) {

    /** POST /writing/tasks 从自然语言创建任务；携带 AI 规划结果时一并下发 */
    suspend fun createTask(message: String, spec: WorkspaceSpec? = null): ApiResult<JsonObject?> {
        val body = mutableMapOf<String, Any?>("message" to message)
        if (spec != null) {
            if (spec.templateId.isNotBlank()) body["template_id"] = spec.templateId
            if (spec.docType.isNotBlank()) body["document_type"] = spec.docType
            if (spec.kbIds.isNotEmpty()) body["kb_ids"] = spec.kbIds
            if (spec.title.isNotBlank()) body["title"] = spec.title
            spec.plannedContext?.let { body["planned_context"] = it }
        }
        return when (val r = api.post(Endpoints.WritingTasks.LIST, body, timeoutMs = 120_000)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }
    }

    /** POST /writing/tasks/plan 一句话指令 → AI 规划出本次写作的工作台配置 */
    suspend fun plan(instruction: String): ApiResult<JsonObject?> =
        when (val r = api.post(Endpoints.WritingTasks.PLAN,
            mapOf("message" to instruction), timeoutMs = 60_000)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    /** GET /writing/tasks/{id} 获取任务全量状态 */
    suspend fun getTask(id: String): ApiResult<JsonObject?> =
        when (val r = api.get(Endpoints.WritingTasks.item(id))) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    suspend fun renderProfile(id: String): ApiResult<JsonObject?> =
        when (val r = api.get(Endpoints.WritingTasks.renderProfile(id))) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    suspend fun paragraphs(id: String): ApiResult<JsonObject?> =
        when (val r = api.get(Endpoints.WritingTasks.paragraphs(id))) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    suspend fun suggestParagraph(
        id: String, paragraphId: String, instruction: String, regenerate: Boolean,
    ): ApiResult<JsonObject?> =
        when (val r = api.post(Endpoints.WritingTasks.paragraphSuggest(id, paragraphId),
            mapOf("instruction" to instruction, "regenerate" to regenerate), timeoutMs = 180_000)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    suspend fun acceptSuggestion(
        id: String, suggestionId: String, finalContent: String,
    ): ApiResult<JsonObject?> =
        when (val r = api.post(Endpoints.WritingTasks.suggestionAccept(id, suggestionId),
            mapOf("final_content" to finalContent))) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    suspend fun rejectSuggestion(id: String, suggestionId: String): ApiResult<JsonObject?> =
        when (val r = api.post(Endpoints.WritingTasks.suggestionReject(id, suggestionId), emptyMap<String, Any>())) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    /** PATCH /writing/tasks/{id} 同步用户手改的结构化字段 */
    suspend fun patchContext(id: String, patch: Map<String, Any?>): ApiResult<JsonObject?> =
        when (val r = api.put(Endpoints.WritingTasks.item(id), mapOf("context" to patch))) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    /** POST /writing/tasks/{id}/chat 任务内持续对话（可能更新上下文/起草/修改） */
    suspend fun chat(id: String, message: String): ApiResult<JsonObject?> =
        when (val r = api.post(Endpoints.WritingTasks.chat(id),
            mapOf("message" to message), timeoutMs = 300_000)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    /** POST /writing/tasks/{id}/draft 生成初稿（非流式，流式接口不可用时的回退） */
    suspend fun draft(id: String, outlineOnly: Boolean = false): ApiResult<JsonObject?> =
        when (val r = api.post(Endpoints.WritingTasks.draft(id),
            mapOf("outline_only" to outlineOnly), timeoutMs = 300_000)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    /**
     * POST /writing/tasks/{id}/draft/stream 流式起草（SSE）。
     * delta 事件回调 onDelta 供渐进展示；done 事件携带权威结果作为返回值；
     * error 事件 / 传输失败转为 Err。
     */
    suspend fun draftStream(
        id: String, outlineOnly: Boolean = false,
        onDelta: (String) -> Unit,
        onReplace: (String) -> Unit = {},
        onProgress: (WritingAgentProgress) -> Unit = {},
    ): ApiResult<JsonObject?> {
        var done: JsonObject? = null
        var streamError: String? = null
        val r = api.postStream(
            Endpoints.WritingTasks.draftStream(id),
            mapOf("outline_only" to outlineOnly),
        ) { ev ->
            when (ev["type"].str()) {
                "delta" -> onDelta(ev["text"].str())
                "replace" -> onReplace(ev["text"].str())
                "done" -> done = ev["data"].obj()
                "error" -> streamError = ev["message"].str().ifBlank { "生成失败，请重试" }
                "run", "stage", "quality" -> onProgress(WritingAgentProgress(
                    type = ev["type"].str(),
                    runId = ev["run_id"].str(),
                    route = ev["route"].str(),
                    key = ev["key"].str(),
                    label = ev["label"].str(),
                    status = ev["status"].str(),
                    qualityLevel = ev["level"].str(),
                    issueCount = ev["issue_count"].int(),
                    repairRound = ev["repair_round"].int().takeIf { it > 0 }
                        ?: ev["attempt"].int(),
                ))
            }
        }
        done?.let { return ApiResult.Ok(it) }
        streamError?.let { return ApiResult.Err(null, it) }
        if (r is ApiResult.Err) return r
        return ApiResult.Err(null, "生成中断，请重试")
    }

    suspend fun cancelAgentRun(id: String, runId: String): ApiResult<JsonObject?> =
        when (val r = api.post(
            Endpoints.WritingTasks.agentRunCancel(id, runId), emptyMap<String, Any?>())) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    /** POST /writing/tasks/{id}/revise 修改当前文档（核心：作用于 currentContent） */
    suspend fun revise(
        id: String, instruction: String, mode: String,
        currentContent: String, baseVersion: Int, baseContent: String,
        selection: String? = null,
    ): ApiResult<JsonObject?> =
        when (val r = api.post(Endpoints.WritingTasks.revise(id), buildMap<String, Any?> {
            put("instruction", instruction)
            put("mode", mode)
            put("current_content", currentContent)
            put("base_version", baseVersion)
            put("base_content_hash", contentHash(baseContent))
            if (!selection.isNullOrBlank()) put("selection", selection)
        }, timeoutMs = 300_000)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    /**
     * POST /writing/tasks/{id}/images 上传图片并由视觉模型（Qwen2.5-VL）识别为文本。
     *
     * 识别文本在服务端写回附件并绑定到任务会话：之后的起草/修改会自动把识别内容
     * 作为「附件材料」注入模型上下文，无需前端再传。视觉识别可能较慢，放宽到 10 分钟。
     * 返回 (识别条目, 是否走了视觉模型)。
     */
    suspend fun recognizeImages(
        id: String, files: List<File>,
    ): ApiResult<Pair<List<JsonObject>, Boolean>> =
        when (val r = api.upload(Endpoints.WritingTasks.images(id), "files", files,
            timeoutMs = 600_000)) {
            is ApiResult.Ok -> {
                val o = r.data.obj()
                val items = o?.get("items")?.arr()?.mapNotNull { it.obj() } ?: emptyList()
                ApiResult.Ok(items to (o?.get("vision")?.bool() ?: false))
            }
            is ApiResult.Err -> r
        }

    /** POST /writing/tasks/{id}/versions 保存当前编辑为新版本 */
    suspend fun saveVersion(
        id: String, content: String, note: String?,
        baseVersion: Int, baseContent: String,
    ): ApiResult<JsonObject?> =
        when (val r = api.post(Endpoints.WritingTasks.versions(id), buildMap<String, Any?> {
            put("content", content)
            put("base_version", baseVersion)
            put("base_content_hash", contentHash(baseContent))
            if (!note.isNullOrBlank()) put("note", note)
        })) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    suspend fun listVersions(id: String): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.WritingTasks.versions(id))) {
            is ApiResult.Ok -> {
                val items = r.data.obj()?.get("items")?.arr()?.mapNotNull { it.obj() }
                    ?: r.data.items()
                ApiResult.Ok(items)
            }
            is ApiResult.Err -> r
        }

    /** GET /writing/tasks/{id}/versions/{no} 查看历史版本内容 */
    suspend fun getVersion(id: String, no: Int): ApiResult<JsonObject?> =
        when (val r = api.get(Endpoints.WritingTasks.version(id, no))) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    /** POST .../versions/{no}/restore 回退到指定历史版本（当前内容先自动保存为新版本） */
    suspend fun restoreVersion(id: String, no: Int): ApiResult<JsonObject?> =
        when (val r = api.post(Endpoints.WritingTasks.versionRestore(id, no),
            emptyMap<String, Any?>())) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    suspend fun export(id: String, redHeader: Boolean, target: File) =
        api.downloadGet(Endpoints.WritingTasks.export(id, redHeader), target)

    // ---- 材料（复用对话附件通道，绑定到任务关联会话） ----

    suspend fun uploadMaterials(files: List<File>): ApiResult<List<ChatAttachment>> =
        when (val r = api.upload(Endpoints.Chat.ATTACHMENTS_UPLOAD, "files", files)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items().map {
                ChatAttachment(it["id"].str(),
                    it["filename"].str().ifBlank { it["name"].str() },
                    it["kind"].str().ifBlank { "doc" },
                    it["parse_status"].str() == "failed")
            })
            is ApiResult.Err -> r
        }
}
