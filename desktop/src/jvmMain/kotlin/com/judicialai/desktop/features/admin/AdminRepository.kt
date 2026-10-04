package com.judicialai.desktop.features.admin

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.obj
import kotlinx.serialization.json.JsonObject
import java.io.File

/** 管理后台数据访问（对应 Web AdminView.vue 调用的接口） */
class AdminRepository(private val api: ApiClient) {

    suspend fun stats(): ApiResult<JsonObject> =
        when (val r = api.get(Endpoints.Knowledge.STATS)) {
            is ApiResult.Ok -> r.data.obj().let {
                if (it != null) ApiResult.Ok(it) else ApiResult.Err(null, "返回数据为空")
            }
            is ApiResult.Err -> r
        }

    suspend fun users(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Users.LIST)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    suspend fun createUser(body: Map<String, Any?>) = api.post(Endpoints.Users.CREATE, body)

    /** 批量导入用户（.xlsx / .csv）：逐行容错，返回每行结果 */
    suspend fun batchImportUsers(file: File) =
        api.upload(Endpoints.Users.BATCH_IMPORT, "file", listOf(file))

    /** 科室字典：直接取自现有科室接口，禁止前端自由输入科室 */
    suspend fun departments(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Organization.LIST)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    suspend fun updateUser(id: String, body: Map<String, Any?>) =
        api.put(Endpoints.Users.item(id), body)

    suspend fun resetPassword(id: String, password: String) =
        api.post(Endpoints.Users.resetPassword(id), mapOf("password" to password))

    suspend fun deleteUser(id: String) = api.del(Endpoints.Users.item(id))

    suspend fun kbs(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Knowledge.LIST)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    /**
     * 新建知识库。kbType 必须显式传：服务端缺省是 personal（仅创建者可见），
     * 管理后台不指定类型会建出一个谁都看不见的私人库。
     */
    suspend fun createKb(name: String, description: String, kbType: String) =
        api.post(Endpoints.Knowledge.CREATE,
            mapOf("name" to name, "description" to description, "kb_type" to kbType))

    /** 恢复归档文档（重新发布 + 重建向量索引） */
    suspend fun unarchive(docId: String) =
        api.post(Endpoints.Knowledge.documentUnarchive(docId), emptyMap<String, String>())

    suspend fun deleteKb(id: String) = api.del(Endpoints.Knowledge.kb(id))

    suspend fun pendingDocs(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Knowledge.PENDING)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    suspend fun docsByStatus(status: String): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Knowledge.DOCUMENTS, mapOf("status" to status))) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    suspend fun review(docId: String, action: String, comment: String) =
        api.post(Endpoints.Knowledge.REVIEW,
            mapOf("doc_id" to docId, "action" to action, "comment" to comment))

    suspend fun archive(docId: String) =
        api.post(Endpoints.Knowledge.documentArchive(docId), emptyMap<String, String>())
}
