package com.judicialai.desktop.features.approval

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.Endpoints

/** 审核流转数据访问：全部走 /approvals 后端接口，无任何本地假数据。 */
class ApprovalRepository(private val api: ApiClient) {

    suspend fun list(view: String, page: Int = 1) =
        api.get(Endpoints.Approvals.LIST, mapOf("view" to view, "page" to page.toString()))

    suspend fun counts() = api.get(Endpoints.Approvals.COUNTS)

    suspend fun detail(id: String) = api.get(Endpoints.Approvals.item(id))

    suspend fun actions(id: String) = api.get(Endpoints.Approvals.actions(id))

    suspend fun submit(documentId: String, urgency: String = "normal") =
        api.post(
            Endpoints.Approvals.CREATE,
            mapOf("document_id" to documentId, "urgency" to urgency),
        )

    suspend fun act(id: String, action: String, comment: String) =
        api.post(
            Endpoints.Approvals.action(id),
            mapOf("action" to action, "comment" to comment),
        )
}
