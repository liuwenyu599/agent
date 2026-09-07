package com.judicialai.desktop.features.documents

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.serialization.json.JsonObject
import java.io.File

/** 我的文档（文档版本管理）数据访问，对应后端 /documents 路由。 */
class DocumentsRepository(private val api: ApiClient) {

    /** GET /documents → {"items": [...]} */
    suspend fun list(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Documents.LIST)) {
            is ApiResult.Ok -> {
                val items = r.data.obj()?.get("items")?.arr()?.mapNotNull { it.obj() }
                    ?: r.data.items()
                ApiResult.Ok(items)
            }
            is ApiResult.Err -> r
        }

    /** GET /documents/{id} → 详情（含 content/quality/versions） */
    suspend fun detail(id: String): ApiResult<JsonObject?> =
        when (val r = api.get(Endpoints.Documents.item(id))) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    /** POST /documents 手动新建 */
    suspend fun create(title: String, content: String): ApiResult<JsonObject?> =
        when (val r = api.post(Endpoints.Documents.LIST,
            mapOf("title" to title, "content" to content))) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    /** PUT /documents/{id} 保存编辑 -> 新版本 */
    suspend fun saveVersion(id: String, content: String, title: String?, note: String?): ApiResult<JsonObject?> =
        when (val r = api.put(Endpoints.Documents.item(id), buildMap<String, Any?> {
            put("content", content)
            if (!title.isNullOrBlank()) put("title", title)
            if (!note.isNullOrBlank()) put("note", note)
        })) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    /** GET /documents/{id}/versions/{no} 查看历史版本 */
    suspend fun version(id: String, no: Int): ApiResult<JsonObject?> =
        when (val r = api.get(Endpoints.Documents.version(id, no))) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.obj())
            is ApiResult.Err -> r
        }

    suspend fun delete(id: String) = api.del(Endpoints.Documents.item(id))

    /** GET /documents/{id}/export/docx 导出公文格式 Word */
    suspend fun exportDocx(id: String, target: File) =
        api.downloadGet(Endpoints.Documents.exportDocx(id), target)
}
