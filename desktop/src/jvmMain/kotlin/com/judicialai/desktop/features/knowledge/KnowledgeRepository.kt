package com.judicialai.desktop.features.knowledge

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.items
import kotlinx.serialization.json.JsonObject
import java.io.File

/** 知识库数据访问（对应 Web knowledge.js） */
class KnowledgeRepository(private val api: ApiClient) {

    suspend fun listKb(): ApiResult<List<JsonObject>> = when (val r = api.get(Endpoints.Knowledge.LIST)) {
        is ApiResult.Ok -> ApiResult.Ok(r.data.items())
        is ApiResult.Err -> r
    }

    suspend fun createKb(name: String, description: String) =
        api.post(Endpoints.Knowledge.CREATE, mapOf("name" to name, "description" to description))

    suspend fun deleteKb(id: String) = api.del(Endpoints.Knowledge.kb(id))

    suspend fun listDocuments(kbId: String): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Knowledge.documents(kbId))) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    suspend fun upload(kbId: String, files: List<File>) =
        if (files.size == 1)
            api.upload(Endpoints.Knowledge.UPLOAD, "file", files, mapOf("kb_id" to kbId))
        else
            api.upload(Endpoints.Knowledge.BATCH_UPLOAD, "files", files, mapOf("kb_id" to kbId))

    suspend fun deleteDocument(docId: String) = api.del(Endpoints.Knowledge.document(docId))

    suspend fun stats() = api.get(Endpoints.Knowledge.STATS)
}

