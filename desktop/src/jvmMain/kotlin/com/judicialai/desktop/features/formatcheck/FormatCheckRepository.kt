package com.judicialai.desktop.features.formatcheck

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.obj
import kotlinx.serialization.json.JsonObject
import java.io.File

/** 格式校验数据访问（对应后端 format-check 系列接口） */
class FormatCheckRepository(private val api: ApiClient) {

    suspend fun check(file: File, useAi: Boolean) =
        api.upload(Endpoints.FormatCheck.CHECK, "file", listOf(file),
            mapOf("use_ai" to useAi.toString()), timeoutMs = 180_000)

    suspend fun records(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.FormatCheck.RECORDS)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    /** GET /format-check/records/{id} → 记录详情（含 issues / applied_ids / resolved_ids / open_issue_count） */
    suspend fun record(id: String): ApiResult<JsonObject> =
        when (val r = api.get(Endpoints.FormatCheck.record(id))) {
            is ApiResult.Ok -> {
                val o = r.data.obj()
                if (o != null) ApiResult.Ok(o)
                else ApiResult.Err(null, "记录响应不是对象：$id")
            }
            is ApiResult.Err -> r
        }

    /**
     * GET /format-check/records/{id}/paragraphs?version=original|current
     *
     * 响应固定为 {"paragraphs":[...], "page":{...}}；这里**直接取 paragraphs 键**，
     * 不走 JsonExt.items()（它不认该键，会永远返回空列表）。
     *
     * 同级新增的 `page`（页边距 / 页面尺寸，供页面级 issue 使用）**不解析、不渲染**，
     * 因为只按 key 取值，未知字段天然被安全忽略，后端继续加字段也不会把这里打挂。
     */
    suspend fun paragraphs(id: String, version: String): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.FormatCheck.paragraphs(id, version))) {
            is ApiResult.Ok -> ApiResult.Ok(
                r.data.obj()?.get("paragraphs").arr().mapNotNull { it.obj() }
            )
            is ApiResult.Err -> r
        }

    /**
     * PUT /format-check/records/{id}/content {"paragraphs": [...]}
     * 保存中栏人工正文修改：写回服务端成为新基线，应用/解决状态由后端重置。
     */
    suspend fun updateContent(id: String, paragraphs: List<String>,
                              formatting: Map<String, Map<String, Any>> = emptyMap()): ApiResult<JsonObject> =
        asObject(api.put(Endpoints.FormatCheck.updateContent(id),
            mapOf("paragraphs" to paragraphs, "formatting" to formatting)))

    /** POST /format-check/records/{id}/apply {"issue_id":n} → {applied_ids, resolved_ids, paragraphs} */
    suspend fun applyIssue(id: String, issueId: Int): ApiResult<JsonObject> =
        asObject(api.post(Endpoints.FormatCheck.apply(id), mapOf("issue_id" to issueId)))

    /** POST /format-check/records/{id}/undo {"issue_id":n} → {applied_ids, resolved_ids, paragraphs} */
    suspend fun undoIssue(id: String, issueId: Int): ApiResult<JsonObject> =
        asObject(api.post(Endpoints.FormatCheck.undo(id), mapOf("issue_id" to issueId)))

    /** POST /format-check/records/{id}/recheck → 与 check 相同结构 */
    suspend fun recheck(id: String): ApiResult<JsonObject> =
        asObject(api.post(Endpoints.FormatCheck.recheck(id), emptyMap<String, String>()))

    /** 把原始 JsonElement 响应收敛成 JsonObject，非对象时给出可读错误 */
    private fun asObject(r: ApiResult<kotlinx.serialization.json.JsonElement>): ApiResult<JsonObject> =
        when (r) {
            is ApiResult.Ok -> {
                val o = r.data.obj()
                if (o != null) ApiResult.Ok(o)
                else ApiResult.Err(null, "后端响应不是对象，无法解析")
            }
            is ApiResult.Err -> r
        }

    /** DELETE /format-check/records/{id} */
    suspend fun deleteRecord(id: String) = api.del(Endpoints.FormatCheck.record(id))

    suspend fun fix(recordId: String, acceptedIndices: List<Int>, target: File) =
        api.downloadPost(Endpoints.FormatCheck.FIX,
            mapOf("record_id" to recordId, "accepted_indices" to acceptedIndices), target)

    // ---- 规则管理 ----

    suspend fun rules(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.FormatCheck.RULES)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    /** POST /format-check/rules/compile：白话描述 → AI 生成校验项（不落库） */
    suspend fun compileRule(target: String, description: String, name: String?): ApiResult<JsonObject> =
        asObject(api.post(Endpoints.FormatCheck.RULES_COMPILE, buildMap<String, Any?> {
            put("target", target)
            put("description", description)
            if (!name.isNullOrBlank()) put("name", name)
        }))

    suspend fun createRule(body: Map<String, Any?>) =
        api.post(Endpoints.FormatCheck.RULES, body)

    suspend fun updateRule(id: String, body: Map<String, Any?>) =
        api.put(Endpoints.FormatCheck.rule(id), body)

    suspend fun setRuleActive(id: String, active: Boolean) =
        api.patch(Endpoints.FormatCheck.ruleActive(id), mapOf("is_active" to active))

    suspend fun deleteRule(id: String) = api.del(Endpoints.FormatCheck.rule(id))
}
