package com.judicialai.desktop.features.workflow

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject

class WorkflowViewModel(private val repo: WorkflowRepository) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var templates by mutableStateOf(listOf<JsonObject>())
        private set
    var instances by mutableStateOf(listOf<JsonObject>())
        private set
    var detail by mutableStateOf<JsonObject?>(null)
        private set
    var status by mutableStateOf<String?>(null)
    var busy by mutableStateOf(false)
        private set
    var generatingNodeId by mutableStateOf<String?>(null)
        private set

    fun load() {
        scope.launch {
            when (val r = repo.templates()) {
                is ApiResult.Ok -> templates = r.data
                is ApiResult.Err -> status = r.message
            }
            when (val r = repo.instances()) {
                is ApiResult.Ok -> instances = r.data
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun create(templateCode: String, title: String) {
        busy = true
        scope.launch {
            when (val r = repo.createInstance(templateCode, title)) {
                is ApiResult.Ok -> {
                    status = "已创建"
                    load()
                    r.data.obj()?.get("id")?.str()?.takeIf { it.isNotBlank() }?.let { open(it) }
                }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    fun open(id: String) {
        scope.launch {
            when (val r = repo.instanceDetail(id)) {
                is ApiResult.Ok -> detail = r.data
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun closeDetail() { detail = null }

    fun refreshDetail() {
        detail?.get("id")?.str()?.takeIf { it.isNotBlank() }?.let { open(it) }
    }

    fun removeInstance(id: String) {
        scope.launch {
            when (val r = repo.deleteInstance(id)) {
                is ApiResult.Ok -> { status = "已删除"; load() }
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun generateNode(nodeInstId: String) {
        generatingNodeId = nodeInstId
        status = "节点生成中，请稍候…"
        scope.launch {
            when (val r = repo.generateNode(nodeInstId)) {
                is ApiResult.Ok -> { status = "生成完成"; refreshDetail() }
                is ApiResult.Err -> status = r.message
            }
            generatingNodeId = null
        }
    }

    fun saveNode(nodeInstId: String, content: String) {
        scope.launch {
            when (val r = repo.updateNode(nodeInstId, content = content)) {
                is ApiResult.Ok -> { status = "已保存"; refreshDetail() }
                is ApiResult.Err -> status = r.message
            }
        }
    }
}

