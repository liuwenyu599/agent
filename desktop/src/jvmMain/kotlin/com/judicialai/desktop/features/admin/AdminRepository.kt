package com.judicialai.desktop.features.admin

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.obj
import kotlinx.serialization.json.JsonObject

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

    suspend fun createKb(name: String, description: String) =
        api.post(Endpoints.Knowledge.CREATE, mapOf("name" to name, "description" to description))

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

    suspend fun adminSessions(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Chat.ADMIN_SESSIONS)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    suspend fun deleteSession(id: String) = api.del(Endpoints.Chat.adminSessionDelete(id))
}

