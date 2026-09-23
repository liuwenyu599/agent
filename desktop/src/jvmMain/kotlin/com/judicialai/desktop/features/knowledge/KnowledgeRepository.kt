package com.judicialai.desktop.features.knowledge

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
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

    suspend fun deleteKb(id: String) = api.del(Endpoints.Knowledge.kb(id))

    suspend fun listDocuments(kbId: String): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Knowledge.documents(kbId))) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
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
