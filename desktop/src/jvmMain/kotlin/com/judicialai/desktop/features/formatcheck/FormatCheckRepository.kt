package com.judicialai.desktop.features.formatcheck

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.items
import kotlinx.serialization.json.JsonObject
import java.io.File

/** 格式校验数据访问（对应 Web format_check.js） */
class FormatCheckRepository(private val api: ApiClient) {

    suspend fun check(file: File, useAi: Boolean) =
        api.upload(Endpoints.FormatCheck.CHECK, "file", listOf(file),
            mapOf("use_ai" to useAi.toString()), timeoutMs = 180_000)

    suspend fun records(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.FormatCheck.RECORDS)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    suspend fun paragraphs(recordId: String): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.FormatCheck.paragraphs(recordId))) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    suspend fun fix(recordId: String, acceptedIndices: List<Int>, target: File) =
        api.downloadPost(Endpoints.FormatCheck.FIX,
            mapOf("record_id" to recordId, "accepted_indices" to acceptedIndices), target)
}

