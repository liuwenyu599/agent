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

/** PPT 助手数据访问（对应 Web PptView / PptTemplateLib） */
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
        api.downloadGet(Endpoints.Ppt.documentDownload(id), target)

    suspend fun deleteDocument(id: String) = api.del(Endpoints.Ppt.documentDelete(id))
}

