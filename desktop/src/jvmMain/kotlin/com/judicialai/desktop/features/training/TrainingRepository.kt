package com.judicialai.desktop.features.training

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.items
import kotlinx.serialization.json.JsonObject
import java.io.File

/** 数据资产中心 + 模型训练 数据访问（对应后端 training 路由） */
class TrainingRepository(private val api: ApiClient) {

    suspend fun overview() = api.get(Endpoints.Training.OVERVIEW)

    // ---- 数据资产 ----
    suspend fun listAssets(sourceType: String, keyword: String, page: Int): ApiResult<JsonObject> =
        api.get(Endpoints.Training.ASSETS, buildMap {
            if (sourceType.isNotBlank()) put("source_type", sourceType)
            if (keyword.isNotBlank()) put("keyword", keyword)
            put("page", page.toString())
        }).let { r -> when (r) {
            is ApiResult.Ok -> r.data.let { ApiResult.Ok(it as? JsonObject ?: JsonObject(emptyMap())) }
            is ApiResult.Err -> r
        } }

    suspend fun getAsset(id: String) = api.get(Endpoints.Training.asset(id))

    suspend fun importDir(path: String, sourceType: String) =
        api.post(Endpoints.Training.IMPORT_DIR,
            mapOf("path" to path, "source_type" to sourceType, "recursive" to true))

    suspend fun importFile(file: File) =
        api.upload(Endpoints.Training.IMPORT_FILE, "file", listOf(file))

    suspend fun generateSample(assetId: String) =
        api.post(Endpoints.Training.assetGenerateSample(assetId))

    suspend fun deleteAsset(id: String) = api.del(Endpoints.Training.asset(id))

    // ---- 样本审核 ----
    suspend fun listSamples(status: String, source: String, page: Int) =
        api.get(Endpoints.Training.SAMPLES, buildMap {
            if (status.isNotBlank()) put("status", status)
            if (source.isNotBlank()) put("source", source)
            put("page", page.toString())
        })

    suspend fun reviewSample(id: String, action: String) =
        api.post(Endpoints.Training.sampleReview(id) + "?action=$action")

    suspend fun editSample(id: String, instruction: String, input: String, output: String) =
        api.put(Endpoints.Training.sample(id),
            mapOf("instruction" to instruction, "input" to input, "output" to output))

    suspend fun deleteSample(id: String) = api.del(Endpoints.Training.sample(id))

    // ---- 数据集 ----
    suspend fun listDatasets(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Training.DATASETS)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    suspend fun createDataset(name: String, description: String) =
        api.post(Endpoints.Training.DATASETS, mapOf("name" to name, "description" to description))

    suspend fun createVersion(datasetId: String, version: String) =
        api.post(Endpoints.Training.datasetVersions(datasetId),
            mapOf("version" to version, "val_ratio" to 0.05))

    // ---- 训练任务 ----
    suspend fun listJobs(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Training.JOBS)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    suspend fun createJob(body: Map<String, Any?>) = api.post(Endpoints.Training.JOBS, body)

    suspend fun jobDetail(id: String) = api.get(Endpoints.Training.job(id))

    suspend fun cancelJob(id: String) = api.post(Endpoints.Training.jobCancel(id))

    // ---- 模型版本 ----
    suspend fun listModels(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Training.MODELS)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    suspend fun publishModel(id: String) = api.post(Endpoints.Training.modelPublish(id))

    suspend fun archiveModel(id: String) = api.post(Endpoints.Training.modelArchive(id))
}

