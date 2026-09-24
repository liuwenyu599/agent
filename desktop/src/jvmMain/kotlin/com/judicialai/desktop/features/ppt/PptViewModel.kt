package com.judicialai.desktop.features.ppt

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.app.AppState
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
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import java.io.File

/** 工作台步骤：极简入口 → 大纲确认（可编辑） → 三栏工作台 */
enum class PptStep { ENTRY, OUTLINE, WORKBENCH }

/** 一份材料的分析结果（材料是一等公民：分析结果对用户可见） */
class MaterialAnalysis(
    val filename: String,
    val chars: Int,
    val summary: String,
    val keyPoints: List<String>,
    val tables: Int,
    val text: String,
)

/** 材料分析聚合统计："已分析 N 份材料，提取 X 个重点，识别 Y 张数据表" */
data class MaterialsTotals(val materials: Int = 0, val keyPoints: Int = 0, val tables: Int = 0)

/** 生成前预检提出的待确认问题（答案预填默认方案，可改） */
class ConfirmQuestion(val question: String, val default: String) {
    var answer by mutableStateOf(default)
}

/** 一页幻灯片的可编辑模型（标题/要点/页型可改，sources 内容依据只读展示） */
class SlideEdit(
    type: String,
    title: String,
    points: List<String>,
    sources: List<String>,
) {
    var type by mutableStateOf(type)
    var title by mutableStateOf(title)
    /** 要点编辑为纯文本，一行一个要点 */
    var pointsText by mutableStateOf(points.joinToString("\n"))
    var sources by mutableStateOf(sources)

    fun points(): List<String> =
        pointsText.split("\n").map { it.trim() }.filter { it.isNotEmpty() }

    fun toJson(): JsonObject = buildJsonObject {
        put("type", type)
        put("title", title)
        putJsonArray("points") { points().forEach { add(it) } }
        putJsonArray("sources") { sources.forEach { add(it) } }
    }

    fun replaceWith(slide: JsonObject) {
        val t = slide["type"].str()
        if (t.isNotBlank()) type = t
        title = slide["title"].str().ifBlank { title }
        val pts = slide["points"].arr().map { it.str() }.filter { it.isNotBlank() }
        if (pts.isNotEmpty()) pointsText = pts.joinToString("\n")
        val src = slide["sources"].arr().map { it.str() }.filter { it.isNotBlank() }
        if (src.isNotEmpty()) sources = src
    }

    companion object {
        fun fromJson(slide: JsonObject) = SlideEdit(
            type = slide["type"].str().ifBlank { "content" },
            title = slide["title"].str(),
            points = slide["points"].arr().map { it.str() }.filter { it.isNotBlank() },
            sources = slide["sources"].arr().map { it.str() }.filter { it.isNotBlank() },
        )
    }
}

class PptViewModel(private val repo: PptRepository) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    // ---- 模板 / 文档列表 ----
    var templates by mutableStateOf(listOf<JsonObject>())
        private set
    var documents by mutableStateOf(listOf<JsonObject>())
        private set
    var templateId by mutableStateOf<String?>(null)
    var status by mutableStateOf<String?>(null)
    var busy by mutableStateOf(false)
        private set
    var downloadingId by mutableStateOf<String?>(null)
        private set

    // ---- 入口页 ----
    var topic by mutableStateOf("")
    var slideCount by mutableStateOf("10")
    var presenter by mutableStateOf("")
    var reportDate by mutableStateOf("")
    val materials = mutableStateListOf<MaterialAnalysis>()
    var analyzing by mutableStateOf(false)
        private set
    var materialsTotals by mutableStateOf<MaterialsTotals?>(null)
        private set

    // ---- 生成前预检（信息不足先确认，90 秒未确认按默认方案生成） ----
    var pendingConfirm by mutableStateOf<List<ConfirmQuestion>?>(null)
        private set

    // ---- 大纲 / 工作台 ----
    var step by mutableStateOf(PptStep.ENTRY)
        private set
    var docId by mutableStateOf<String?>(null)
        private set
    var outlineTitle by mutableStateOf("")
    var outlineSubtitle by mutableStateOf("")
    val slides = mutableStateListOf<SlideEdit>()
    var selected by mutableStateOf(0)
    var outlineStage by mutableStateOf("")
        private set

    // ---- 逐页真实预览（服务端渲染 PNG；404/失败时回退结构化预览卡） ----
    var previewPages by mutableStateOf(listOf<String>())
        private set
    var previewBusy by mutableStateOf(false)
        private set

    // ---- 撤销（快照栈：覆盖手动编辑与 AI 修改/结构调整，跨步骤有效） ----
    private data class SlideSnap(
        val type: String, val title: String,
        val pointsText: String, val sources: List<String>,
    )
    private data class DeckSnap(
        val title: String, val subtitle: String, val slides: List<SlideSnap>,
    )
    private val undoStack = ArrayDeque<DeckSnap>()
    var canUndo by mutableStateOf(false)
        private set

    // ---- AI 助手 ----
    var aiInstruction by mutableStateOf("")
    var aiBusy by mutableStateOf(false)
        private set
    var aiNote by mutableStateOf<String?>(null)
    var showSourceOf by mutableStateOf<String?>(null)

    // ================= 模板 / 文档列表 =================

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

    fun download(id: String, target: File) {
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
        // 文档已删除：恢复标记必须一起清掉，否则切回页面会去请求一个不存在的文档
        if (AppState.pendingPptDocId == id) AppState.pendingPptDocId = null
        scope.launch {
            when (val r = repo.deleteDocument(id)) {
                is ApiResult.Ok -> loadDocuments()
                is ApiResult.Err -> status = r.message
            }
        }
    }

    // ================= 撤销 =================

    private fun snapshot(): DeckSnap = DeckSnap(
        outlineTitle, outlineSubtitle,
        slides.map { SlideSnap(it.type, it.title, it.pointsText, it.sources.toList()) },
    )

    private fun pushUndo() {
        undoStack.addLast(snapshot())
        if (undoStack.size > 50) undoStack.removeFirst()
        canUndo = true
    }

    /** 撤销一步：恢复上一个大纲快照（手动增删移动页、AI 单页修改、结构调整均可撤销） */
    fun undo() {
        val s = undoStack.removeLastOrNull() ?: return
        outlineTitle = s.title
        outlineSubtitle = s.subtitle
        slides.clear()
        s.slides.forEach { slides.add(SlideEdit(it.type, it.title, it.pointsText.split("\n"), it.sources)) }
        selected = selected.coerceIn(0, (slides.size - 1).coerceAtLeast(0))
        canUndo = undoStack.isNotEmpty()
        status = "已撤销"
    }

    // ================= 入口页：材料分析 =================

    fun analyzeMaterials(files: List<File>) {
        if (files.isEmpty()) return
        analyzing = true
        status = "正在分析 ${files.size} 份材料…"
        scope.launch {
            when (val r = repo.analyzeMaterials(files)) {
                is ApiResult.Ok -> {
                    val root = r.data.obj()
                    val items = root?.get("items").arr().mapNotNull { it.obj() }
                    items.forEach { m ->
                        materials.add(MaterialAnalysis(
                            filename = m["filename"].str(),
                            chars = m["chars"].int(),
                            summary = m["summary"].str(),
                            keyPoints = m["key_points"].arr().map { it.str() }
                                .filter { it.isNotBlank() },
                            tables = m["tables"].int(),
                            text = m["text"].str(),
                        ))
                    }
                    val t = root?.get("totals").obj()
                    materialsTotals = MaterialsTotals(
                        materials = materials.size,
                        keyPoints = t?.get("key_points")?.int()
                            ?: materials.sumOf { it.keyPoints.size },
                        tables = t?.get("tables")?.int() ?: materials.sumOf { it.tables },
                    )
                    status = root?.get("message")?.str()?.ifBlank { null }
                        ?: "已分析 ${items.size} 份材料，可继续添加或直接生成大纲"
                }
                is ApiResult.Err -> status = r.message
            }
            analyzing = false
        }
    }

    fun removeMaterial(index: Int) {
        if (index in materials.indices) materials.removeAt(index)
        materialsTotals = if (materials.isEmpty()) null else MaterialsTotals(
            materials = materials.size,
            keyPoints = materials.sumOf { it.keyPoints.size },
            tables = materials.sumOf { it.tables },
        )
    }

    // ================= 大纲生成（生成前预检 + 流式 + 回退） =================

    private fun outlineBody(): Map<String, Any?> {
        val content = buildString {
            materials.forEach {
                append("【").append(it.filename).append("】\n").append(it.text).append("\n\n")
            }
            if (presenter.isNotBlank()) append("汇报人：").append(presenter).append('\n')
            if (reportDate.isNotBlank()) append("汇报时间：").append(reportDate).append('\n')
        }.trim()
        return mapOf(
            "source_type" to if (materials.isNotEmpty()) "document" else "topic",
            "topic" to topic,
            "content" to content,
            "slide_count" to (slideCount.toIntOrNull() ?: 10),
            "audience" to "",
            "scene" to "",
            "material_names" to materials.map { it.filename },
        )
    }

    fun startOutline() {
        if (topic.isBlank() && materials.isEmpty()) {
            status = "请先填写汇报主题，或上传材料"
            return
        }
        // 切走再切回会得到一个新的 ViewModel（busy 已重置），仅靠 busy 挡不住重复发起；
        // 而两次生成会并发跑，后完成的覆盖 pendingPptDocId，先完成的文档客户端就找不到了
        if (AppState.pptOutlineGenerating) {
            status = "还有一份正在生成，请稍候"
            return
        }
        if (pendingConfirm != null) return // 确认框还开着，等用户选择
        busy = true
        AppState.pptLastError = null
        outlineStage = "正在检查关键信息是否齐全…"
        status = null
        val body = outlineBody()
        scope.launch {
            // 生成前预检：信息不足时先向用户确认（每个问题附默认方案），避免 AI 瞎编；
            // 预检接口失败一律放行，不阻塞生成
            var questions: List<ConfirmQuestion> = emptyList()
            when (val r = repo.precheck(body)) {
                is ApiResult.Ok -> {
                    val d = r.data.obj()
                    if (d != null && d["sufficient"]?.toString()?.contains("false") == true) {
                        questions = d["questions"].arr().mapNotNull { it.obj() }
                            .map { ConfirmQuestion(it["question"].str(), it["default"].str()) }
                            .filter { it.question.isNotBlank() }
                    }
                }
                is ApiResult.Err -> Unit
            }
            if (questions.isNotEmpty()) {
                busy = false
                outlineStage = ""
                pendingConfirm = questions
                status = "生成前请确认几个关键信息（90 秒未确认将按默认方案生成）"
            } else {
                launchOutline(body)
            }
        }
    }

    /** 确认问题答案后生成；useAnswers=false 表示全部按默认方案 */
    fun confirmAndGenerate(useAnswers: Boolean) {
        val qs = pendingConfirm ?: return
        pendingConfirm = null
        val extra = buildString {
            append("【生成前与用户确认的关键信息（以此为准，不得编造）】")
            qs.forEach { q ->
                val a = (if (useAnswers) q.answer else q.default).ifBlank { q.default }
                append('\n').append(q.question).append("：")
                    .append(a.ifBlank { "按政务汇报通用惯例处理" })
            }
        }
        val body = outlineBody().toMutableMap()
        body["content"] = (((body["content"] as? String) ?: "") + "\n\n" + extra).trim()
        busy = true
        status = null
        scope.launch { launchOutline(body) }
    }

    /** 取消本次生成（既不想确认也不想按默认方案跑） */
    fun cancelConfirm() {
        pendingConfirm = null
        status = null
    }

    /**
     * 真正发起大纲生成（预检通过或用户确认后调用）：
     * 全局标记保证切页不丢进度，结束（无论成败）一定复位。
     */
    private suspend fun launchOutline(body: Map<String, Any?>) {
        // 全局标记：切到别的页面再切回时据此显示「正在生成中」；生成结束（无论成败）复位
        AppState.pptOutlineGenerating = true
        AppState.pptLastError = null
        outlineStage = "正在理解材料与任务要求…"
        var ok = false
        try {
            ok = runOutline(body)
        } catch (e: Exception) {
            status = "大纲生成中断：${e.message ?: "未知错误"}"
        } finally {
            // 生成协程不随页面切换取消，这里保证标记一定复位，不会永久卡在「生成中」
            busy = false
            AppState.pptOutlineGenerating = false
        }
        // 失败原因记到全局：切走再切回时本地 status 会随 ViewModel 一起丢失，
        // 用户只会看到干净的入口页，以为生成"没了"
        AppState.pptLastError = if (ok) null
        else status?.takeIf { it.isNotBlank() } ?: "大纲生成未完成，请重试"
    }

    /**
     * 执行一次大纲生成：优先 SSE 流式（过程可见）；
     * 服务端未部署流式接口（404）或流中断且未拿到 done → 回退一次性接口。
     * @return 是否成功拿到大纲（成功时已通过 applyOutline 写入本地与全局状态）
     */
    private suspend fun runOutline(body: Map<String, Any?>): Boolean {
        var doneOk = false
        var streamErr: ApiResult.Err? = null
        when (val r = repo.outlineStream(body) { ev ->
            when (ev["type"].str()) {
                "stage" -> outlineStage = ev["text"].str()
                "done" -> {
                    val d = ev["data"].obj()
                    val ol = d?.get("outline").obj()
                    if (d != null && ol != null) {
                        applyOutline(d["doc_id"].str(), ol)
                        doneOk = true
                    }
                }
                "error" -> status = ev["message"].str().ifBlank { "大纲生成失败" }
            }
        }) {
            is ApiResult.Ok -> Unit
            is ApiResult.Err -> streamErr = r
        }
        // 服务端未部署流式接口或流中断且未拿到 done → 回退一次性接口
        if (!doneOk && streamErr != null) {
            outlineStage = "正在生成大纲…"
            when (val r2 = repo.outline(
                body["source_type"] as String, body["topic"] as String,
                body["content"] as String, body["slide_count"] as Int, "", "")) {
                is ApiResult.Ok -> {
                    val ol = runCatching {
                        kotlinx.serialization.json.Json.parseToJsonElement(r2.data.second).obj()
                    }.getOrNull()
                    if (ol != null) {
                        applyOutline(r2.data.first ?: "", ol)
                        doneOk = true
                    } else status = "大纲解析失败，请重试"
                }
                is ApiResult.Err -> status = r2.message
            }
        }
        return doneOk
    }

    private fun applyOutline(newDocId: String, outline: JsonObject) {
        if (newDocId.isNotBlank()) {
            docId = newDocId
            // 记录到全局：切到别的页面再切回时按此 id 从服务端恢复大纲与工作台
            AppState.pendingPptDocId = newDocId
        }
        outlineTitle = outline["title"].str().ifBlank { topic.ifBlank { "未命名PPT" } }
        outlineSubtitle = outline["subtitle"].str()
        slides.clear()
        outline["slides"].arr().mapNotNull { it.obj() }.forEach { slides.add(SlideEdit.fromJson(it)) }
        if (slides.isEmpty()) {
            slides.add(SlideEdit("content", "第一页", listOf("点击右侧 AI 助手或直接编辑"), emptyList()))
        }
        selected = 0
        undoStack.clear()
        canUndo = false
        previewPages = emptyList()
        step = PptStep.OUTLINE
        outlineStage = ""
        status = "大纲已生成（${slides.size} 页），请逐页确认或修改"
    }

    fun addSlideAfter(index: Int) {
        pushUndo()
        val at = (index + 1).coerceIn(0, slides.size)
        slides.add(at, SlideEdit("content", "新页面", listOf(""), emptyList()))
        selected = at
    }

    fun removeSlide(index: Int) {
        if (slides.size <= 1 || index !in slides.indices) return
        pushUndo()
        slides.removeAt(index)
        selected = selected.coerceIn(0, slides.size - 1)
    }

    fun moveSlide(index: Int, delta: Int) {
        val to = index + delta
        if (index !in slides.indices || to !in slides.indices) return
        pushUndo()
        val s = slides.removeAt(index)
        slides.add(to, s)
        selected = to
    }

    fun toWorkbench() {
        step = PptStep.WORKBENCH
        status = null
        refreshPreview()
    }
    fun backToOutline() { if (docId != null) step = PptStep.OUTLINE }
    /**
     * 回到极简入口页：用户明确放弃当前这份文档，
     * 清掉跨页面恢复标记与上次失败原因，避免下次进页面又自动打开它、或一直挂着旧错误。
     */
    fun backToEntry() {
        step = PptStep.ENTRY
        AppState.pendingPptDocId = null
        AppState.pptLastError = null
    }

    // ================= 打开已有文档 / 导入 PPT 续改 =================

    fun openDocument(id: String) {
        busy = true
        status = "正在打开文档…"
        scope.launch {
            when (val r = repo.document(id)) {
                is ApiResult.Ok -> {
                    val d = r.data.obj()
                    val ol = d?.get("outline").obj()
                    if (d != null && ol != null) {
                        d["template_id"].str().ifBlank { null }?.let { templateId = it }
                        applyOutline(id, ol)
                        step = PptStep.WORKBENCH
                        status = "已打开「${d["title"].str()}」"
                        refreshPreview()
                    } else status = "文档内容为空"
                }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    fun importPptx(file: File) {
        busy = true
        status = "正在解析「${file.name}」…"
        scope.launch {
            when (val r = repo.importPptx(file)) {
                is ApiResult.Ok -> {
                    val d = r.data.obj()
                    val ol = d?.get("outline").obj()
                    if (d != null && ol != null) {
                        applyOutline(d["doc_id"].str(), ol)
                        step = PptStep.WORKBENCH
                        status = d["message"].str().ifBlank { "已导入，可继续编辑" }
                        refreshPreview()
                    } else status = "导入结果为空"
                }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    // ================= 保存 / 生成 / 导出 / 预览 =================

    private fun outlineJson(): JsonObject = buildJsonObject {
        put("title", outlineTitle)
        put("subtitle", outlineSubtitle)
        putJsonArray("slides") { slides.forEach { add(it.toJson()) } }
    }

    fun saveDraft(showTip: Boolean = true) {
        val id = docId ?: return
        scope.launch {
            when (val r = repo.saveDraft(id, outlineTitle, outlineJson(), templateId)) {
                is ApiResult.Ok -> if (showTip) status = "草稿已保存"
                is ApiResult.Err -> if (showTip) status = r.message
            }
        }
    }

    /** 先保存草稿，再渲染为逐页 PNG 供工作台真实版式预览（失败自动回退结构化卡） */
    fun refreshPreview() {
        val id = docId ?: return
        if (previewBusy) return
        previewBusy = true
        scope.launch {
            repo.saveDraft(id, outlineTitle, outlineJson(), templateId)
            when (val r = repo.preview(id)) {
                is ApiResult.Ok ->
                    previewPages = r.data.obj()?.get("pages").arr().map { it.str() }
                        .filter { it.isNotBlank() }
                is ApiResult.Err -> previewPages = emptyList() // 服务端未部署/无 LibreOffice
            }
            previewBusy = false
        }
    }

    /** 生成并导出：先保存草稿，再渲染 pptx，最后让用户选保存位置 */
    fun generateAndExport(target: File) {
        val id = docId ?: return
        // 同 startOutline：切回页面后 busy 已重置，仅靠 busy 挡不住重复导出，
        // 而两次导出会写同一个文件
        if (AppState.pptExporting) {
            status = "还有一份正在导出，请稍候"
            return
        }
        busy = true
        AppState.pptExporting = true
        AppState.pptLastError = null
        status = "正在生成 PPT（模板学习渲染）…"
        scope.launch {
            var failed: String? = null
            try {
                repo.saveDraft(id, outlineTitle, outlineJson(), templateId)
                when (val r = repo.generate(id, outlineJson(), templateId)) {
                    is ApiResult.Ok -> {
                        status = when (val d = repo.downloadDocument(id, target)) {
                            is ApiResult.Ok -> d.data
                            is ApiResult.Err -> d.message.also { failed = it }
                        }
                        loadDocuments()
                    }
                    is ApiResult.Err -> status = r.message.also { failed = it }
                }
            } catch (e: Exception) {
                failed = "导出失败：${e.message ?: "未知错误"}"
                status = failed
            } finally {
                // 导出协程同样不随页面切换取消，这里保证标记一定复位
                busy = false
                AppState.pptExporting = false
            }
            // 切走期间导出失败时，本地 status 会随 ViewModel 一起丢失
            AppState.pptLastError = failed
        }
    }

    // ================= AI 助手（单页局部编辑优先） =================

    /** 单页局部修改：润色 / 扩写 / 精简 / 重写 / 自定义（可撤销） */
    fun aiSlide(action: String, instruction: String = "") {
        val i = selected
        if (i !in slides.indices) return
        aiBusy = true
        aiNote = null
        scope.launch {
            when (val r = repo.aiSlideAction(action, slides[i].toJson(), instruction)) {
                is ApiResult.Ok -> {
                    val slide = r.data.obj()?.get("slide").obj()
                    if (slide != null) {
                        pushUndo()
                        slides[i].replaceWith(slide)
                        aiNote = "已更新第 ${i + 1} 页"
                        refreshPreview()
                    } else aiNote = "AI 未返回有效修改"
                }
                is ApiResult.Err -> aiNote = r.message
            }
            aiBusy = false
        }
    }

    /** 结构调整：add 在此页后新增 / split 拆分本页 / merge 与下一页合并（可撤销） */
    fun aiStructure(action: String) {
        if (slides.isEmpty()) return
        val i = selected.coerceIn(0, slides.size - 1)
        if (action == "merge" && i >= slides.size - 1) {
            aiNote = "最后一页无法与下一页合并"
            return
        }
        aiBusy = true
        aiNote = null
        scope.launch {
            when (val r = repo.aiStructure(action, slides.map { it.toJson() }, i)) {
                is ApiResult.Ok -> {
                    val arr = r.data.obj()?.get("slides").arr().orEmpty().mapNotNull { it.obj() }
                    if (arr.isNotEmpty()) {
                        pushUndo()
                        slides.clear()
                        arr.forEach { slides.add(SlideEdit.fromJson(it)) }
                        selected = i.coerceIn(0, slides.size - 1)
                        aiNote = "结构已调整（共 ${slides.size} 页）"
                        refreshPreview()
                    } else aiNote = "AI 未返回有效结构"
                }
                is ApiResult.Err -> aiNote = r.message
            }
            aiBusy = false
        }
    }

    /** 内容依据查看：材料文本（本次会话内分析过的材料才有全文） */
    fun materialOf(filename: String): MaterialAnalysis? =
        materials.find { it.filename == filename }
}
