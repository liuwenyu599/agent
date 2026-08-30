package com.judicialai.desktop.features.ppt

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File

class PptViewModel(private val repo: PptRepository) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var templates by mutableStateOf(listOf<JsonObject>())
        private set
    var documents by mutableStateOf(listOf<JsonObject>())
        private set
    var templateId by mutableStateOf<String?>(null)
    var docId by mutableStateOf<String?>(null)
        private set
    var outlineText by mutableStateOf("")
    var status by mutableStateOf<String?>(null)
    var busy by mutableStateOf(false)
        private set
    var downloadingId by mutableStateOf<String?>(null)
        private set

    fun loadTemplates() {
        scope.launch {
            when (val r = repo.templates()) {
                is ApiResult.Ok -> {
                    templates = r.data
                    if (templateId == null) templateId = r.data.firstOrNull()?.get("id")?.str()
                }
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun loadDocuments() {
        scope.launch {
            when (val r = repo.documents()) {
                is ApiResult.Ok -> documents = r.data
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun uploadTemplate(file: File) {
        busy = true
        status = "上传并学习模板中…"
        scope.launch {
            when (val r = repo.uploadTemplate(file)) {
                is ApiResult.Ok -> { status = "模板学习完成"; loadTemplates() }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    fun deleteTemplate(id: String) {
        scope.launch {
            when (val r = repo.deleteTemplate(id)) {
                is ApiResult.Ok -> loadTemplates()
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun createOutline(sourceType: String, topic: String, content: String,
                      slideCount: Int, audience: String, scene: String) {
        busy = true
        status = "生成大纲中…"
        scope.launch {
            when (val r = repo.outline(sourceType, topic, content, slideCount, audience, scene)) {
                is ApiResult.Ok -> {
                    docId = r.data.first
                    outlineText = r.data.second
                    status = "大纲已生成，可编辑后点击“生成 PPT”"
                }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    fun generate() {
        val did = docId ?: return
        if (outlineText.isBlank()) return
        busy = true
        status = "生成 PPT 中（模板学习渲染）…"
        scope.launch {
            val outlineJson = runCatching { Json.parseToJsonElement(outlineText) }
                .getOrElse { JsonPrimitive(outlineText) }
            when (val r = repo.generate(did, outlineJson, templateId)) {
                is ApiResult.Ok -> { status = "生成完成，请到“我的 PPT”下载"; loadDocuments() }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    fun download(id: String, title: String, target: File) {
        downloadingId = id
        scope.launch {
            status = when (val r = repo.downloadDocument(id, target)) {
                is ApiResult.Ok -> r.data
                is ApiResult.Err -> r.message
            }
            downloadingId = null
        }
    }

    fun deleteDocument(id: String) {
        scope.launch {
            when (val r = repo.deleteDocument(id)) {
                is ApiResult.Ok -> loadDocuments()
                is ApiResult.Err -> status = r.message
            }
        }
    }
}

