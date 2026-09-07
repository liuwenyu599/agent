package com.judicialai.desktop.features.training

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import java.io.File

class TrainingViewModel(private val repo: TrainingRepository) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    // 总览统计
    var overview by mutableStateOf(listOf<Pair<String, String>>())
        private set

    // 数据资产
    var assets by mutableStateOf(listOf<JsonObject>())
        private set
    var assetTotal by mutableStateOf(0)
        private set
    var assetPage by mutableStateOf(1)
    var assetSourceFilter by mutableStateOf("")
    var assetKeyword by mutableStateOf("")

    // 样本审核
    var samples by mutableStateOf(listOf<JsonObject>())
        private set
    var sampleTotal by mutableStateOf(0)
        private set
    var sampleCounts by mutableStateOf(mapOf<String, Int>())
        private set
    var samplePage by mutableStateOf(1)
    var sampleStatusFilter by mutableStateOf("candidate")

    // 数据集
    var datasets by mutableStateOf(listOf<JsonObject>())
        private set

    // 训练任务
    var jobs by mutableStateOf(listOf<JsonObject>())
        private set
    var jobLog by mutableStateOf("")
    var currentJob by mutableStateOf<JsonObject?>(null)

    // 模型版本
    var models by mutableStateOf(listOf<JsonObject>())
        private set

    var status by mutableStateOf<String?>(null)
    var busy by mutableStateOf(false)

    private fun notify(msg: String) { status = msg }

    fun loadOverview() {
        scope.launch {
            when (val r = repo.overview()) {
                is ApiResult.Ok -> {
                    val o = r.data.obj() ?: return@launch
                    val sc = o["sample_counts"].obj()
                    overview = listOf(
                        "数据资产" to o["asset_count"].int().toString(),
                        "候选样本" to (sc?.get("candidate")).int().toString(),
                        "已审核样本" to (sc?.get("approved")).int().toString(),
                        "训练任务" to (o["job_counts"].obj()?.values?.sumOf { it.int() } ?: 0).toString(),
                        "模型版本" to o["model_count"].int().toString(),
                    )
                }
                is ApiResult.Err -> Unit
            }
        }
    }

    // ---- 数据资产 ----
    fun loadAssets(page: Int = assetPage) {
        assetPage = page
        scope.launch {
            when (val r = repo.listAssets(assetSourceFilter, assetKeyword, page)) {
                is ApiResult.Ok -> {
                    assets = r.data["items"]?.items() ?: emptyList()
                    assetTotal = r.data["total"].int()
                }
                is ApiResult.Err -> notify("加载数据资产失败：${r.message}")
            }
        }
    }

    fun importDir(path: String, sourceType: String) {
        if (path.isBlank()) { notify("请填写外部目录路径"); return }
        busy = true
        scope.launch {
            when (val r = repo.importDir(path, sourceType)) {
                is ApiResult.Ok -> {
                    val o = r.data.obj()
                    notify("导入完成：新增 ${o?.get("created").int() ?: 0}，跳过 ${o?.get("skipped").int() ?: 0}")
                    loadAssets(); loadOverview()
                }
                is ApiResult.Err -> notify("导入失败：${r.message}")
            }
            busy = false
        }
    }

    fun importFile(file: File) {
        busy = true
        scope.launch {
            when (val r = repo.importFile(file)) {
                is ApiResult.Ok -> {
                    notify("文件导入完成")
                    loadAssets(); loadOverview()
                }
                is ApiResult.Err -> notify("导入失败：${r.message}")
            }
            busy = false
        }
    }

    fun generateSample(assetId: String) {
        busy = true
        scope.launch {
            when (val r = repo.generateSample(assetId)) {
                is ApiResult.Ok -> { notify("已生成候选样本，请到「样本审核」查看"); loadSamples() }
                is ApiResult.Err -> notify("生成失败：${r.message}")
            }
            busy = false
        }
    }

    fun deleteAsset(id: String) {
        scope.launch {
            when (repo.deleteAsset(id)) {
                is ApiResult.Ok -> { notify("已删除"); loadAssets(); loadOverview() }
                is ApiResult.Err -> notify("删除失败")
            }
        }
    }

    // ---- 样本审核 ----
    fun loadSamples(page: Int = samplePage) {
        samplePage = page
        scope.launch {
            when (val r = repo.listSamples(sampleStatusFilter, "", page)) {
                is ApiResult.Ok -> {
                    val o = r.data.obj() ?: return@launch
                    samples = o["items"]?.items() ?: emptyList()
                    sampleTotal = o["total"].int()
                    sampleCounts = o["counts"].obj()?.mapValues { it.value.int() } ?: emptyMap()
                }
                is ApiResult.Err -> notify("加载样本失败：${r.message}")
            }
        }
    }

    fun reviewSample(id: String, action: String) {
        scope.launch {
            when (repo.reviewSample(id, action)) {
                is ApiResult.Ok -> { loadSamples(); loadOverview() }
                is ApiResult.Err -> notify("操作失败")
            }
        }
    }

    fun editSample(id: String, instruction: String, input: String, output: String) {
        scope.launch {
            when (repo.editSample(id, instruction, input, output)) {
                is ApiResult.Ok -> { notify("已保存"); loadSamples() }
                is ApiResult.Err -> notify("保存失败")
            }
        }
    }

    fun deleteSample(id: String) {
        scope.launch {
            when (repo.deleteSample(id)) {
                is ApiResult.Ok -> { loadSamples(); loadOverview() }
                is ApiResult.Err -> notify("删除失败")
            }
        }
    }

    // ---- 数据集 ----
    fun loadDatasets() {
        scope.launch {
            when (val r = repo.listDatasets()) {
                is ApiResult.Ok -> datasets = r.data
                is ApiResult.Err -> notify("加载数据集失败：${r.message}")
            }
        }
    }

    fun createDataset(name: String, description: String) {
        if (name.isBlank()) { notify("请填写数据集名称"); return }
        scope.launch {
            when (repo.createDataset(name, description)) {
                is ApiResult.Ok -> { notify("数据集已创建"); loadDatasets() }
                is ApiResult.Err -> notify("创建失败")
            }
        }
    }

    fun createVersion(datasetId: String, version: String) {
        if (version.isBlank()) { notify("请填写版本号"); return }
        busy = true
        scope.launch {
            when (val r = repo.createVersion(datasetId, version)) {
                is ApiResult.Ok -> {
                    val cr = r.data.obj()?.get("check_report").obj()
                    notify("版本 $version 已生成：有效 ${cr?.get("valid").int()} / ${cr?.get("total").int()}")
                    loadDatasets()
                }
                is ApiResult.Err -> notify("生成版本失败：${r.message}")
            }
            busy = false
        }
    }

    // ---- 训练任务 ----
    fun loadJobs() {
        scope.launch {
            when (val r = repo.listJobs()) {
                is ApiResult.Ok -> jobs = r.data
                is ApiResult.Err -> notify("加载任务失败：${r.message}")
            }
        }
    }

    fun createJob(body: Map<String, Any?>) {
        busy = true
        scope.launch {
            when (val r = repo.createJob(body)) {
                is ApiResult.Ok -> { notify("训练任务已启动（独立进程运行）"); loadJobs() }
                is ApiResult.Err -> notify("启动失败：${r.message}")
            }
            busy = false
        }
    }

    fun loadJobDetail(id: String) {
        scope.launch {
            when (val r = repo.jobDetail(id)) {
                is ApiResult.Ok -> {
                    val o = r.data.obj() ?: return@launch
                    currentJob = o["job"].obj()
                    jobLog = o["log"].str()
                    loadJobs()
                }
                is ApiResult.Err -> notify("加载任务详情失败")
            }
        }
    }

    fun cancelJob(id: String) {
        scope.launch {
            when (repo.cancelJob(id)) {
                is ApiResult.Ok -> { notify("已取消"); loadJobs() }
                is ApiResult.Err -> notify("取消失败")
            }
        }
    }

    // ---- 模型版本 ----
    fun loadModels() {
        scope.launch {
            when (val r = repo.listModels()) {
                is ApiResult.Ok -> models = r.data
                is ApiResult.Err -> notify("加载模型版本失败：${r.message}")
            }
        }
    }

    fun publishModel(id: String) = modelAction(id, publish = true)
    fun archiveModel(id: String) = modelAction(id, publish = false)

    private fun modelAction(id: String, publish: Boolean) {
        scope.launch {
            val r = if (publish) repo.publishModel(id) else repo.archiveModel(id)
            when (r) {
                is ApiResult.Ok -> { notify(if (publish) "已发布" else "已归档"); loadModels() }
                is ApiResult.Err -> notify("操作失败：${r.message}")
            }
        }
    }
}
