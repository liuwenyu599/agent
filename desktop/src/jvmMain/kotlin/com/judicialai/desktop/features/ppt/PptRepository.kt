package com.judicialai.desktop.features.ppt

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import java.io.File

/** PPT 助手数据访问（对应 Web PptView / PptTemplateLib + 工作台重设计新接口） */
class PptRepository(private val api: ApiClient) {

    suspend fun templates(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Ppt.TEMPLATES)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    suspend fun uploadTemplate(file: File) =
        api.upload(Endpoints.Ppt.TEMPLATE_UPLOAD, "file", listOf(file), timeoutMs = 300_000)

    suspend fun deleteTemplate(id: String) = api.del(Endpoints.Ppt.templateDelete(id))

    /** 返回 (docId, outlineJson) */
    suspend fun outline(
        sourceType: String, topic: String, content: String,
        slideCount: Int, audience: String, scene: String,
    ): ApiResult<Pair<String?, String>> {
        val body = mapOf(
            "source_type" to sourceType, "topic" to topic, "content" to content,
            "slide_count" to slideCount, "audience" to audience, "scene" to scene,
        )
        return when (val r = api.post(Endpoints.Ppt.OUTLINE, body, timeoutMs = 180_000)) {
            is ApiResult.Ok -> {
                val d = r.data.obj()
                ApiResult.Ok(
                    (d?.get("doc_id")?.str()?.ifBlank { null }) to
                        (d?.get("outline")?.toString() ?: ""))
            }
            is ApiResult.Err -> r
        }
    }

    /** 流式大纲（SSE）：onEvent 回调 {type: stage|done|error} 事件 */
    suspend fun outlineStream(body: Map<String, Any?>, onEvent: (JsonObject) -> Unit) =
        api.postStream(Endpoints.Ppt.OUTLINE_STREAM, body,
            timeoutMs = 300_000, onEvent = onEvent)

    /** 材料分析：多文件上传，逐份返回 {filename, chars, summary, key_points, tables, text} + totals */
    suspend fun analyzeMaterials(files: List<File>) =
        api.upload(Endpoints.Ppt.MATERIALS_ANALYZE, "files", files, timeoutMs = 300_000)

    /** 上传已有 .pptx 继续修改 → {doc_id, outline, message} */
    suspend fun importPptx(file: File) =
        api.upload(Endpoints.Ppt.DOCUMENT_IMPORT, "file", listOf(file), timeoutMs = 300_000)

    suspend fun document(id: String) = api.get(Endpoints.Ppt.document(id))

    /** 保存草稿（大纲编辑结果写回服务端，不改变文档状态） */
    suspend fun saveDraft(id: String, title: String, outline: JsonObject, templateId: String?) =
        api.put(Endpoints.Ppt.documentDraft(id),
            mapOf("title" to title, "outline" to outline, "template_id" to templateId))

    /** 渲染当前草稿为逐页 PNG 预览 → {pages: [url...], count} */
    suspend fun preview(id: String) =
        api.post(Endpoints.Ppt.documentPreview(id), emptyMap<String, Any?>(), timeoutMs = 300_000)

    /** 单页局部修改：action = rewrite / expand / condense / custom */
    suspend fun aiSlideAction(action: String, slide: JsonObject, instruction: String) =
        api.post(Endpoints.Ppt.AI_SLIDE_ACTION,
            mapOf("action" to action, "slide" to slide, "instruction" to instruction),
            timeoutMs = 180_000)

    /** 结构调整：action = add / split / merge */
    suspend fun aiStructure(action: String, slides: List<JsonObject>, index: Int) =
        api.post(Endpoints.Ppt.AI_STRUCTURE,
            mapOf("action" to action, "slides" to slides, "index" to index, "instruction" to ""),
            timeoutMs = 180_000)

    suspend fun generate(docId: String, outline: JsonElement, templateId: String?) =
        api.post(Endpoints.Ppt.GENERATE,
            mapOf("doc_id" to docId, "outline" to outline, "template_id" to templateId),
            timeoutMs = 300_000)

    suspend fun documents(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Ppt.DOCUMENTS)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    suspend fun downloadDocument(id: String, target: File) =
        api.downloadPost(Endpoints.Ppt.documentExport(id), emptyMap(), target)

    suspend fun deleteDocument(id: String) = api.del(Endpoints.Ppt.documentDelete(id))

    /** PATCH /ppt/documents/{id} {title} → 重命名演示文稿 */
    suspend fun renameDocument(id: String, title: String) =
        api.patch(Endpoints.Ppt.document(id), mapOf("title" to title))
}
