package com.judicialai.desktop.features.knowledge

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.obj
import kotlinx.serialization.json.JsonObject
import java.io.File

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

    suspend fun listDocuments(kbId: String): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Knowledge.documents(kbId))) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
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
}
