package com.judicialai.desktop.features.knowledge

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import java.io.File

class KnowledgeViewModel(private val repo: KnowledgeRepository) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var kbs by mutableStateOf(listOf<JsonObject>())
        private set
    var currentKb by mutableStateOf<JsonObject?>(null)
        private set
    var docs by mutableStateOf(listOf<JsonObject>())
        private set
    var stats by mutableStateOf(listOf<Pair<String, String>>())
        private set
    var status by mutableStateOf<String?>(null)
    var busy by mutableStateOf(false)
        private set

    /** 顶部统计条（对应 Web /knowledge/stats） */
    fun loadStats() {
        scope.launch {
            when (val r = repo.stats()) {
                is ApiResult.Ok -> {
                    val o = r.data.obj()
                    if (o != null) stats = listOf(
                        "知识库数" to o["kb_count"].int().toString(),
                        "文档总数" to o["doc_count"].int().toString(),
                        "已发布" to o["published"].int().toString(),
                        "待审核" to o["pending"].int().toString(),
                        "会话总数" to o["session_count"].int().toString(),
                        "总用户数" to o["user_count"].int().toString(),
                    )
                }
                is ApiResult.Err -> Unit
            }
        }
    }

    fun back() {
        currentKb = null
        docs = emptyList()
    }

    fun loadKbs() {
        scope.launch {
            when (val r = repo.listKb()) {
                is ApiResult.Ok -> kbs = r.data
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun select(kb: JsonObject) {
        currentKb = kb
        loadDocs()
    }

    fun loadDocs() {
        val kbId = currentKb?.get("id")?.str() ?: return
        scope.launch {
            when (val r = repo.listDocuments(kbId)) {
                is ApiResult.Ok -> docs = r.data
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun create(name: String, desc: String) {
        scope.launch {
            when (val r = repo.createKb(name, desc)) {
                is ApiResult.Ok -> loadKbs()
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun deleteKb(id: String) {
        scope.launch {
            when (val r = repo.deleteKb(id)) {
                is ApiResult.Ok -> {
                    if (id == currentKb?.get("id")?.str()) {
                        currentKb = null
                        docs = emptyList()
                    }
                    loadKbs()
                }
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun upload(files: List<File>) {
        val kbId = currentKb?.get("id")?.str() ?: return
        if (files.isEmpty()) return
        busy = true
        status = "上传中，请稍候…"
        scope.launch {
            when (val r = repo.upload(kbId, files)) {
                is ApiResult.Ok -> { status = "上传完成"; loadDocs() }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    fun deleteDocument(docId: String) {
        scope.launch {
            when (val r = repo.deleteDocument(docId)) {
                is ApiResult.Ok -> loadDocs()
                is ApiResult.Err -> status = r.message
            }
        }
    }
}

