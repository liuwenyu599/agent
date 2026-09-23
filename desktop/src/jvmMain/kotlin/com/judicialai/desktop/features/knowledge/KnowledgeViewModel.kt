package com.judicialai.desktop.features.knowledge

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.int
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
    /** 顶部统计条：公共 / 科室 / 个人知识库数目 + 文档总数（由可见知识库列表计算，不走管理员统计接口） */
    var stats by mutableStateOf(listOf<Pair<String, String>>())
        private set
    var status by mutableStateOf<String?>(null)
    var busy by mutableStateOf(false)
        private set

    // ---- 文档查看 / 编辑弹窗 ----
    var docDialogId by mutableStateOf<String?>(null)
        private set
    var docDialogTitle by mutableStateOf("")
    var docDialogContent by mutableStateOf("")
    var docDialogBusy by mutableStateOf(false)
        private set

    /** 知识库分类：科室库 = public 且带 department_code */
    private fun kindOf(kb: JsonObject): String = when {
        kb["department_code"].str().isNotBlank() -> "department"
        kb["type"].str() == "public" -> "public"
        else -> "personal"
    }

    private fun computeStats() {
        stats = listOf(
            "公共知识库" to kbs.count { kindOf(it) == "public" }.toString(),
            "科室知识库" to kbs.count { kindOf(it) == "department" }.toString(),
            "个人知识库" to kbs.count { kindOf(it) == "personal" }.toString(),
            "文档总数" to kbs.sumOf { it["doc_count"].int() }.toString(),
        )
    }

    fun back() {
        currentKb = null
        docs = emptyList()
    }

    fun loadKbs() {
        scope.launch {
            when (val r = repo.listKb()) {
                is ApiResult.Ok -> {
                    kbs = r.data
                    computeStats()
                }
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

    /** kbType：public（仅系统管理员）/ department（科室管理员）/ personal（普通用户） */
    fun create(name: String, desc: String, kbType: String) {
        scope.launch {
            when (val r = repo.createKb(name, desc, kbType)) {
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

    // ---- 文档查看 / 编辑 ----

    /** 打开文档详情（全文内容），进入查看/编辑弹窗 */
    fun openDocument(docId: String) {
        if (docId.isBlank() || docDialogBusy) return
        docDialogBusy = true
        scope.launch {
            when (val r = repo.getDocument(docId)) {
                is ApiResult.Ok -> {
                    val d = r.data
                    if (d != null) {
                        docDialogId = docId
                        docDialogTitle = d["title"].str()
                        docDialogContent = d["content"].str()
                    } else {
                        status = "文档内容为空"
                    }
                }
                is ApiResult.Err -> status = r.message
            }
            docDialogBusy = false
        }
    }

    fun closeDocument() {
        docDialogId = null
        docDialogTitle = ""
        docDialogContent = ""
    }

    /** 保存编辑：后端重新分块并重建该文档向量，检索内容同步更新 */
    fun saveDocument() {
        val id = docDialogId ?: return
        if (docDialogBusy) return
        docDialogBusy = true
        scope.launch {
            when (val r = repo.updateDocument(id, docDialogTitle, docDialogContent)) {
                is ApiResult.Ok -> {
                    status = "已保存，检索内容已同步更新"
                    closeDocument()
                    loadDocs()
                }
                is ApiResult.Err -> status = r.message
            }
            docDialogBusy = false
        }
    }
}
