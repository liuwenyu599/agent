package com.judicialai.desktop.features.writing

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.features.chat.model.ChatAttachment
import kotlinx.serialization.json.JsonObject
import java.io.File

/**
 * 智能写作工作台数据访问（/writing/tasks 系列接口）。
 * 任务 = 结构化上下文 + 当前文档 + 持续对话 + 版本链，全部行为落在后端。
 */
class WritingRepository(private val api: ApiClient) {

    /** POST /writing/tasks 从自然语言创建任务 */
    suspend fun createTask(message: String): ApiResult<JsonObject?> =
        when (val r = api.post(Endpoints.WritingTasks.LIST,
            mapOf("message" to message), timeoutMs = 120_000)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    /** GET /writing/tasks/{id} 获取任务全量状态 */
    suspend fun getTask(id: String): ApiResult<JsonObject?> =
        when (val r = api.get(Endpoints.WritingTasks.item(id))) {
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

    /** POST /writing/tasks/{id}/draft 生成初稿 */
    suspend fun draft(id: String, outlineOnly: Boolean = false): ApiResult<JsonObject?> =
        when (val r = api.post(Endpoints.WritingTasks.draft(id),
            mapOf("outline_only" to outlineOnly), timeoutMs = 300_000)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    /** POST /writing/tasks/{id}/revise 修改当前文档（核心：作用于 currentContent） */
    suspend fun revise(
        id: String, instruction: String, mode: String,
        currentContent: String, selection: String? = null,
    ): ApiResult<JsonObject?> =
        when (val r = api.post(Endpoints.WritingTasks.revise(id), buildMap<String, Any?> {
            put("instruction", instruction)
            put("mode", mode)
            put("current_content", currentContent)
            if (!selection.isNullOrBlank()) put("selection", selection)
        }, timeoutMs = 300_000)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    /** POST /writing/tasks/{id}/versions 保存当前编辑为新版本 */
    suspend fun saveVersion(id: String, content: String, note: String?): ApiResult<JsonObject?> =
        when (val r = api.post(Endpoints.WritingTasks.versions(id), buildMap<String, Any?> {
            put("content", content)
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

    suspend fun export(id: String, redHeader: Boolean, target: File) =
        api.downloadGet(Endpoints.WritingTasks.export(id, redHeader), target)

    /** 加入训练数据：instruction + AI 初稿 + 人工最终稿 → pending_review */
    suspend fun addToTraining(id: String, finalContent: String) =
        api.post(Endpoints.WritingTasks.trainingSample(id), mapOf("final_content" to finalContent))

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
