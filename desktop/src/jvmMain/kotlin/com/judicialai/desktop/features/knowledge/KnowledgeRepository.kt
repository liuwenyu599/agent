package com.judicialai.desktop.features.knowledge

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.features.chat.model.KnowledgeCitation
import kotlinx.serialization.json.JsonObject
import java.io.File

data class KnowledgeAskOutcome(
    val reply: String,
    val sessionId: String?,
    val citations: List<KnowledgeCitation>,
)

/** 知识库数据访问（对应 Web knowledge.js） */
class KnowledgeRepository(private val api: ApiClient) {

    suspend fun listKb(): ApiResult<List<JsonObject>> = when (val r = api.get(Endpoints.Knowledge.LIST)) {
        is ApiResult.Ok -> ApiResult.Ok(r.data.items())
        is ApiResult.Err -> r
    }

    /** kbType：public / department / personal，服务端按角色校验 */
    suspend fun createKb(name: String, description: String, kbType: String) =
        api.post(Endpoints.Knowledge.CREATE, mapOf(
            "name" to name, "description" to description, "kb_type" to kbType))

    /** 编辑知识库：名称 / 描述 / 类型（kbType 为 null 表示不改类型；类型调整由服务端按角色校验） */
    suspend fun updateKb(id: String, name: String, description: String, kbType: String?) =
        api.put(Endpoints.Knowledge.kb(id), buildMap<String, Any?> {
            put("name", name)
            put("description", description)
            if (kbType != null) put("kb_type", kbType)
        })

    suspend fun deleteKb(id: String) = api.del(Endpoints.Knowledge.kb(id))

    suspend fun listDocuments(
        kbId: String,
        page: Int = 1,
        pageSize: Int = 20,
        sort: String = "newest",
    ): ApiResult<JsonObject?> =
        when (val r = api.get(
            Endpoints.Knowledge.documents(kbId) +
                "?page=$page&page_size=$pageSize&sort=" +
                java.net.URLEncoder.encode(sort, "UTF-8")
        )) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    /**
     * 库内文档搜索：GET /knowledge/{kbId}/documents/search?q=。
     * 服务端一次返回全部结果：标题命中排前（match=title）、内容命中排后（match=content，带 snippet）。
     */
    suspend fun searchDocuments(kbId: String, q: String): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Knowledge.documents(kbId) + "/search?q=" +
                java.net.URLEncoder.encode(q, "UTF-8"))) {
            is ApiResult.Ok -> ApiResult.Ok(
                r.data.obj()?.get("data").arr().mapNotNull { it.obj() })
            is ApiResult.Err -> r
        }

    /** GET /knowledge/documents/{id} 查看文档全文（含 content） */
    suspend fun getDocument(docId: String): ApiResult<JsonObject?> =
        when (val r = api.get(Endpoints.Knowledge.document(docId))) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    /** PUT /knowledge/documents/{id} 编辑标题/正文；正文变化时后端重新分块并重建该文档向量 */
    suspend fun updateDocument(docId: String, title: String?, content: String?) =
        api.put(Endpoints.Knowledge.document(docId), buildMap<String, Any?> {
            if (title != null) put("title", title)
            if (content != null) put("content", content)
        })

    suspend fun upload(kbId: String, files: List<File>) =
        if (files.size == 1)
            api.upload(Endpoints.Knowledge.UPLOAD, "file", files, mapOf("kb_id" to kbId))
        else
            api.upload(Endpoints.Knowledge.BATCH_UPLOAD, "files", files, mapOf("kb_id" to kbId))

    suspend fun deleteDocument(docId: String) = api.del(Endpoints.Knowledge.document(docId))

    suspend fun ask(
        message: String,
        sessionId: String?,
        attachmentIds: List<String>,
    ): ApiResult<KnowledgeAskOutcome> {
        val body = buildMap<String, Any?> {
            put("message", message)
            put("session_id", sessionId)
            if (attachmentIds.isNotEmpty()) put("attachment_ids", attachmentIds)
        }
        return when (val r = api.post(Endpoints.Knowledge.ASK, body, timeoutMs = 180_000)) {
            is ApiResult.Ok -> {
                val root = r.data.obj()
                val citations = root?.get("sources").arr().mapNotNull { e ->
                    val o = e.obj() ?: return@mapNotNull null
                    val source = o["source"].str()
                    if (source.isBlank()) return@mapNotNull null
                    KnowledgeCitation(
                        source = source,
                        kbId = o["kb_id"].str(),
                        kbName = o["kb_name"].str(),
                        kbType = o["kb_type"].str(),
                        docId = o["doc_id"].str(),
                        docTitle = o["doc_title"].str(),
                        chunkId = o["chunk_id"].str(),
                        chunkIndex = o["chunk_index"].int(),
                        excerpt = o["content"].str(),
                    )
                } ?: emptyList()
                ApiResult.Ok(KnowledgeAskOutcome(
                    reply = root?.get("reply").str(),
                    sessionId = root?.get("session_id").str().ifBlank { null },
                    citations = citations,
                ))
            }
            is ApiResult.Err -> r
        }
    }
}
