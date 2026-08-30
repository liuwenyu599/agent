package com.judicialai.desktop.features.templates

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.str
import kotlinx.serialization.json.JsonObject

/** 写作模板数据访问（对应 Web templates API） */
class TemplatesRepository(private val api: ApiClient) {

    suspend fun list(): ApiResult<List<JsonObject>> = when (val r = api.get(Endpoints.Templates.LIST)) {
        is ApiResult.Ok -> ApiResult.Ok(r.data.items())
        is ApiResult.Err -> r
    }

    suspend fun categories(): ApiResult<List<String>> =
        when (val r = api.get(Endpoints.Templates.CATEGORIES)) {
            is ApiResult.Ok -> ApiResult.Ok(
                r.data.items().map { it["name"].str().ifBlank { it.str() } }.filter { it.isNotBlank() })
            is ApiResult.Err -> r
        }

    suspend fun initBuiltin() = api.post(Endpoints.Templates.INIT)

    suspend fun create(body: Map<String, Any?>) = api.post(Endpoints.Templates.CREATE, body)

    suspend fun update(id: String, body: Map<String, Any?>) =
        api.put(Endpoints.Templates.item(id), body)

    suspend fun delete(id: String) = api.del(Endpoints.Templates.item(id))

    suspend fun detail(id: String) = api.get(Endpoints.Templates.item(id))

    /** 使用模板生成公文（对应 Web TemplateView：组装要素 + system_prompt 调 /chat/send） */
    suspend fun generate(message: String, systemPrompt: String) =
        api.post(Endpoints.Chat.SEND, mapOf(
            "message" to message,
            "system_prompt" to systemPrompt,
            "use_rag" to true,
            "source" to "template",
        ), timeoutMs = 180_000)

    /** 记录使用次数 */
    suspend fun markUsed(id: String) = api.post(Endpoints.Templates.use(id), emptyMap<String, String>())

    /** 生成结果导出 Word（走 /chat/export/docx） */
    suspend fun exportResult(title: String, content: String, target: java.io.File) =
        api.downloadPost(Endpoints.Chat.EXPORT_DOCX,
            mapOf("title" to title, "content" to content), target)
}

