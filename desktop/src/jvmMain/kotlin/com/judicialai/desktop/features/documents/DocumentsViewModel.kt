package com.judicialai.desktop.features.documents

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import java.io.File

class DocumentsViewModel(private val repo: DocumentsRepository) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var documents by mutableStateOf(listOf<JsonObject>())
        private set
    var currentId by mutableStateOf<String?>(null)
        private set
    var title by mutableStateOf("")
    var content by mutableStateOf("")
    var docNumber by mutableStateOf("")
        private set
    var docDate by mutableStateOf("")
        private set
    var currentVersion by mutableStateOf(0)
        private set
    var versions by mutableStateOf(listOf<JsonObject>())
        private set
    var quality by mutableStateOf<JsonObject?>(null)
        private set
    var contentCheck by mutableStateOf<JsonObject?>(null)
        private set
    /** 查看历史版本时非空（只读预览） */
    var previewVersion by mutableStateOf<JsonObject?>(null)
        private set
    var status by mutableStateOf<String?>(null)
    var busy by mutableStateOf(false)
        private set

    fun refresh() {
        scope.launch {
            when (val r = repo.list()) {
                is ApiResult.Ok -> documents = r.data
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun open(id: String) {
        busy = true
        previewVersion = null
        scope.launch {
            when (val r = repo.detail(id)) {
                is ApiResult.Ok -> {
                    val d = r.data
                    if (d != null) {
                        currentId = id
                        title = d["title"].str()
                        content = d["content"].str()
                        docNumber = d["document_number"].str()
                        docDate = d["document_date"].str()
                        currentVersion = d["current_version"].int()
                        versions = d["versions"].arr().mapNotNull { it.obj() }
                        quality = d["quality"].obj()
                        contentCheck = d["content_check"].obj()
                        status = null
                    }
                }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    fun createNew() {
        currentId = null
        title = ""
        content = ""
        docNumber = ""
        docDate = ""
        currentVersion = 0
        versions = emptyList()
        quality = null
        contentCheck = null
        previewVersion = null
    }

    fun save(note: String?) {
        busy = true
        scope.launch {
            val id = currentId
            val r = if (id == null) repo.create(title.ifBlank { "未命名文档" }, content)
                    else repo.saveVersion(id, content, title, note)
            when (r) {
                is ApiResult.Ok -> {
                    status = if (id == null) "已创建文档" else "已保存为新版本"
                    r.data?.get("id")?.str()?.let { open(it) } ?: refresh()
                }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    fun previewVersion(no: Int) {
        val id = currentId ?: return
        scope.launch {
            when (val r = repo.version(id, no)) {
                is ApiResult.Ok -> previewVersion = r.data
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun closePreview() { previewVersion = null }

    fun delete() {
        val id = currentId ?: return
        busy = true
        scope.launch {
            when (val r = repo.delete(id)) {
                is ApiResult.Ok -> {
                    status = "已删除"
                    createNew()
                    refresh()
                }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    fun export(target: File) {
        val id = currentId ?: return
        busy = true
        status = "导出中…"
        scope.launch {
            when (val r = repo.exportDocx(id, target)) {
                is ApiResult.Ok -> status = "已导出：${target.absolutePath}"
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }
}
