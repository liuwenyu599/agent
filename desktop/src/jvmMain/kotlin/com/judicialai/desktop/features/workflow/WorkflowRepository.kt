package com.judicialai.desktop.features.workflow

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.obj
import kotlinx.serialization.json.JsonObject

/** 工作流程数据访问（对应 Web workflow.js 与 backend/api/workflow.py） */
class WorkflowRepository(private val api: ApiClient) {

    /** GET /workflow/templates → {"templates": [...]} */
    suspend fun templates(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Workflow.TEMPLATES)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    /** GET /workflow/instances → {"instances": [...]} */
    suspend fun instances(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Workflow.INSTANCES)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    suspend fun instanceDetail(id: String): ApiResult<JsonObject> =
        when (val r = api.get(Endpoints.Workflow.instance(id))) {
            is ApiResult.Ok -> r.data.obj().let {
                if (it != null) ApiResult.Ok(it) else ApiResult.Err(null, "返回数据为空")
            }
            is ApiResult.Err -> r
        }

    /** POST /workflow/instances {template_code, title, workflow_context} */
    suspend fun createInstance(templateCode: String, title: String) =
        api.post(Endpoints.Workflow.INSTANCES, mapOf(
            "template_code" to templateCode,
            "title" to title,
            "workflow_context" to emptyMap<String, String>(),
        ))

    /** PUT /workflow/instances/{id} {title} → 重命名工作流程（历史记录入口共用） */
    suspend fun renameInstance(id: String, title: String) =
        api.put(Endpoints.Workflow.instance(id), mapOf("title" to title))

    /**
     * POST /workflow/instances/{id}/ai-adjust {instruction}
     * AI 按自然语言要求调整节点（增/删/改名/改写作要求/调顺序），
     * 返回调整后的完整实例 + reply 调整说明。耗时操作，走长超时。
     */
    suspend fun aiAdjust(id: String, instruction: String) =
        api.post(Endpoints.Workflow.instance(id) + "/ai-adjust",
            mapOf("instruction" to instruction), timeoutMs = 180_000)

    suspend fun deleteInstance(id: String) = api.del(Endpoints.Workflow.instance(id))

    /** POST /workflow/nodes/{id}/generate {instruction, save} */
    suspend fun generateNode(nodeInstId: String, instruction: String = "") =
        api.post(Endpoints.Workflow.nodeGenerate(nodeInstId),
            mapOf("instruction" to instruction, "save" to true), timeoutMs = 180_000)

    /** PUT /workflow/nodes/{id} {content?, status?} */
    suspend fun updateNode(nodeInstId: String, content: String? = null, status: String? = null) =
        api.put(Endpoints.Workflow.nodeUpdate(nodeInstId), buildMap<String, Any?> {
            content?.let { put("content", it) }
            status?.let { put("status", it) }
        })
}
