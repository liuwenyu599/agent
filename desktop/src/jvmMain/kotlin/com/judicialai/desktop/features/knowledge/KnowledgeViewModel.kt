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
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
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
    var docPage by mutableStateOf(1)
        private set
    var docTotal by mutableStateOf(0)
        private set
    val docPageSize: Int = 20
    var docSort by mutableStateOf("newest")
        private set
    /** 顶部统计条：公共 / 科室 / 个人知识库数目 + 文档总数（由可见知识库列表计算，不走管理员统计接口） */
    var stats by mutableStateOf(listOf<Pair<String, String>>())
        private set
    var status by mutableStateOf<String?>(null)
    var busy by mutableStateOf(false)
        private set

    /** 知识库编辑弹窗（管理员）：名称 / 描述 / 类型 */
    var editingKb by mutableStateOf<JsonObject?>(null)

    // ---- 库内文档搜索 ----
    /** 当前搜索词；输入即搜（300ms 防抖） */
    var searchQuery by mutableStateOf("")
        private set
    /**
     * 搜索结果：null = 未在搜索（显示普通文档列表）；非 null = 搜索结果。
     * 服务端一次请求返回全部结果（标题命中排前、内容命中排后），
     * 拿到即替换显示，不等任何「后续查询」。
     */
    var searchResults by mutableStateOf<List<JsonObject>?>(null)
        private set
    var searching by mutableStateOf(false)
        private set
    private var searchJob: Job? = null

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
        docPage = 1
        docTotal = 0
        clearSearch()
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
        docPage = 1
        clearSearch()
        loadDocs()
    }

    fun loadDocs(page: Int = docPage) {
        val kbId = currentKb?.get("id")?.str() ?: return
        val requested = page.coerceAtLeast(1)
        scope.launch {
            when (val r = repo.listDocuments(kbId, requested, docPageSize, docSort)) {
                is ApiResult.Ok -> {
                    val o = r.data
                    docs = o?.get("data").arr().mapNotNull { it.obj() }
                    docTotal = o?.get("total").int()
                    docPage = o?.get("page").int().coerceAtLeast(1)
                }
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun setDocSort(sort: String) {
        if (sort == docSort) return
        docSort = sort
        docPage = 1
        loadDocs(1)
    }

    fun prevDocPage() {
        if (docPage > 1) loadDocs(docPage - 1)
    }

    fun nextDocPage() {
        if (docPage * docPageSize < docTotal) loadDocs(docPage + 1)
    }

    // ---- 库内搜索：即输即搜，结果一返回就显示 ----

    fun search(q: String) {
        searchQuery = q
        val kbId = currentKb?.get("id")?.str()
        if (q.isBlank() || kbId == null) {
            searchJob?.cancel()
            searching = false
            searchResults = null
            return
        }
        // 防抖：连续输入只发最后一次；每次只发一个请求，响应到达立刻出列表
        searchJob?.cancel()
        searchJob = scope.launch {
            searching = true
            delay(300)
            when (val r = repo.searchDocuments(kbId, q.trim())) {
                is ApiResult.Ok -> searchResults = r.data
                is ApiResult.Err -> status = r.message
            }
            searching = false
        }
    }

    fun clearSearch() {
        searchJob?.cancel()
        searchQuery = ""
        searchResults = null
        searching = false
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

    /**
     * 编辑知识库（管理员）：类型可改为公共 / 科室 / 个人。
     * 保存后以服务端返回的「实际生效类型」核对所选类型：
     * 旧版本服务端不支持改类型时会静默忽略，这里发现不一致必须明说，
     * 不能提示「已更新」让人误以为类型改成功了。
     */
    fun updateKb(id: String, name: String, desc: String, kbType: String) {
        scope.launch {
            when (val r = repo.updateKb(id, name, desc, kbType)) {
                is ApiResult.Ok -> {
                    editingKb = null
                    val d = r.data.obj()
                    val effectiveType = d?.get("type")?.str().orEmpty()
                    val deptCode = d?.get("department_code")?.str().orEmpty()
                    val effectiveKind = when {
                        deptCode.isNotBlank() -> "department"
                        effectiveType == "public" -> "public"
                        effectiveType.isBlank() -> kbType // 旧服务端不回传类型：无法核对，按成功处理
                        else -> "personal"
                    }
                    status = if (effectiveKind == kbType) {
                        "知识库已更新"
                    } else {
                        val label = when (effectiveKind) {
                            "department" -> "科室"; "public" -> "公共"; else -> "个人"
                        }
                        "名称/描述已保存，但类型未生效（实际仍为「$label」）：可能是权限不足，或服务端版本过旧需要更新"
                    }
                    loadKbs()
                }
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
                        clearSearch()
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
                is ApiResult.Ok -> {
                    loadDocs()
                    // 正在搜索时同步删掉结果里的这一条
                    searchResults?.let { list ->
                        searchResults = list.filter { it["id"].str() != docId }
                    }
                }
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
