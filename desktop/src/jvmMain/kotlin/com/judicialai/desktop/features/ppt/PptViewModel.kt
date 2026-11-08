package com.judicialai.desktop.features.ppt

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.logging.ClientLog
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import java.io.File
import java.time.LocalDate

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

data class PptLibraryMaterial(
    val id: String, val name: String, val caption: String, val url: String,
    val source: String = "personal", val category: String = "我的图片",
    val credit: String = "",
)

data class PptVisualIssue(
    val page: Int, val code: String, val severity: String, val message: String,
)

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
    raw: JsonObject = buildJsonObject {},
) {
    var type by mutableStateOf(type)
    var title by mutableStateOf(title)
    var layout by mutableStateOf(raw["layout"].str())
    var layoutLocked by mutableStateOf(raw["layout_locked"].toString() == "true")
    /** 要点编辑为纯文本，一行一个要点 */
    var pointsText by mutableStateOf(points.joinToString("\n"))
    var sources by mutableStateOf(sources)

    /**
     * 保留服务端大纲中的完整页面 JSON。
     * 工作台目前只直接编辑 type/title/points/sources，但 blocks/image/chart/notes/layout
     * 等字段必须原样保留，否则“重新打开 → 保存草稿”会把丰富页面降维成纯文本页。
     */
    private var rawSlide by mutableStateOf(raw)

    fun points(): List<String> =
        pointsText.split("\n").map { it.trim() }.filter { it.isNotEmpty() }

    fun rawSnapshot(): JsonObject = rawSlide

    fun toJson(): JsonObject = buildJsonObject {
        rawSlide.forEach { (key, value) -> put(key, value) }
        put("type", type)
        put("title", title)
        put("layout", layout)
        put("layout_locked", layoutLocked)
        putJsonArray("points") { points().forEach { add(it) } }
        putJsonArray("sources") { sources.forEach { add(it) } }
    }

    fun replaceWith(slide: JsonObject) {
        rawSlide = slide
        val t = slide["type"].str()
        if (t.isNotBlank()) type = t
        title = slide["title"].str().ifBlank { title }
        layout = slide["layout"].str()
        layoutLocked = slide["layout_locked"].toString() == "true"
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
            raw = slide,
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
    var themeId by mutableStateOf<String?>(null)
    var themes by mutableStateOf(listOf<JsonObject>())
        private set
    var status by mutableStateOf<String?>(null)
    var busy by mutableStateOf(false)
        private set
    var downloadingId by mutableStateOf<String?>(null)
        private set
    var templateEditor by mutableStateOf<JsonObject?>(null)
        private set
    var templateEditorBusy by mutableStateOf(false)
        private set
    var layoutOptions by mutableStateOf(listOf<JsonObject>())
        private set

    // ---- 入口页 ----
    var topic by mutableStateOf("")
    var slideCount by mutableStateOf("")
    private val today = LocalDate.now()
    var presenter by mutableStateOf(AppState.pptPresenter)
        private set
    var generationYear by mutableStateOf(
        AppState.pptGenerationYear.ifBlank { today.year.toString() })
        private set
    var location by mutableStateOf(AppState.pptLocation)
        private set
    var reportDate by mutableStateOf(
        AppState.pptReportDate.ifBlank { today.toString() })
        private set

    fun updatePresenter(value: String) {
        presenter = value
        AppState.pptPresenter = value
    }

    fun updateGenerationYear(value: String) {
        generationYear = value
        AppState.pptGenerationYear = value
    }

    fun updateLocation(value: String) {
        location = value
        AppState.pptLocation = value
    }

    fun updateReportDate(value: String) {
        reportDate = value
        AppState.pptReportDate = value
    }
    val materials = mutableStateListOf<MaterialAnalysis>()
    var analyzing by mutableStateOf(false)
        private set
    var materialsTotals by mutableStateOf<MaterialsTotals?>(null)
        private set
    var libraryMaterials by mutableStateOf(listOf<PptLibraryMaterial>())
        private set
    val selectedMaterialIds = mutableStateListOf<String>()
    var autoImagesEnabled by mutableStateOf(true)
    var materialLibraryBusy by mutableStateOf(false)
        private set

    // ---- 知识库（结合知识库生成：服务端按主题做 RAG 语义检索，命中片段作为内容依据） ----
    var kbs by mutableStateOf(listOf<JsonObject>())
        private set
    val selectedKbIds = mutableStateListOf<String>()
    var kbsLoading by mutableStateOf(false)
        private set
    var kbsError by mutableStateOf<String?>(null)
        private set
    private var kbsLoaded = false

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

    /** 大纲生成协程句柄：「取消生成」用；切页不取消（协程独立于界面） */
    private var outlineJob: Job? = null

    /**
     * 「AI 智能设计」一次性标志：为 true 表示本次大纲生成完成后**不停在确认页**，
     * 直接按 [aiDesignTarget] 落草稿并提交 PPTAgent 异步设计任务。
     *
     * 用 State 而不是普通字段：入口页要据此显示「AI 智能设计中…」，得能触发重组。
     * **成败与取消都必须在 [launchOutline] 的 finally 里复位**，
     * 否则下一次普通「生成大纲」会被误当成 AI 设计（用户没选过保存位置，任务会静默不跑）。
     */
    var autoDesignAfterOutline by mutableStateOf(false)
        private set

    /** 「AI 智能设计」用户预先选好的 pptx 保存位置（提交任务时用，用完即清） */
    private var aiDesignTarget: File? = null

    // ---- 导出（生成 PPT）阶段与取消 ----
    /** 导出阶段文案（底部状态栏展示）：保存草稿 → PPTAgent 渲染 → 写入文件 */
    var exportStage by mutableStateOf("")
        private set
    private var exportJob: Job? = null

    // ---- 异步生成任务（PPTAgent 5–15 分钟：提交即返回 + 轮询 + 逐页预览） ----
    /**
     * 当前生成任务进度。句柄挂在 PptJobEngine（全局单例）上，
     * 所以切走页面再切回时 remember 重建 ViewModel 也不会丢——这里只是读它的入口。
     */
    val job: PptJobProgress? get() = PptJobEngine.current

    /** 有任务占着工作台（含已完成的），界面据此展示生成工作台而不是普通工作台 */
    val jobVisible: Boolean get() = PptJobEngine.current != null

    // ---- 逐页真实预览（服务端渲染 PNG；404/失败时回退结构化预览卡） ----
    var previewPages by mutableStateOf(listOf<String>())
        private set
    var previewRevision by mutableStateOf(0)
        private set
    var previewBusy by mutableStateOf(false)
        private set
    var visualReviewBusy by mutableStateOf(false)
        private set
    var visualReviewSummary by mutableStateOf<String?>(null)
        private set
    var visualReviewIssues by mutableStateOf(listOf<PptVisualIssue>())
        private set

    // ---- 撤销（快照栈：覆盖手动编辑与 AI 修改/结构调整，跨步骤有效） ----
    private data class SlideSnap(
        val type: String, val title: String,
        val layout: String, val pointsText: String, val sources: List<String>,
        val raw: JsonObject,
    )
    private data class DeckSnap(
        val title: String, val subtitle: String, val slides: List<SlideSnap>,
    )
    private val undoStack = ArrayDeque<DeckSnap>()
    var canUndo by mutableStateOf(false)
        private set

    // ---- AI 助手 ----
    var aiInstruction by mutableStateOf("")
    var outlineAdjustInstruction by mutableStateOf("")
    var aiBusy by mutableStateOf(false)
        private set
    var aiNote by mutableStateOf<String?>(null)
    var showSourceOf by mutableStateOf<String?>(null)

    // ================= 模板 / 文档列表 =================

    fun loadTemplates() {
        scope.launch {
            val result = repo.themes()
            if (result is ApiResult.Ok) themes = result.data
        }
        scope.launch {
            when (val r = repo.templates()) {
                is ApiResult.Ok -> {
                    templates = r.data
                    // 不替用户静默选择“列表第一项”。null 表示未显式选模板，
                    // 服务端使用自适应版式与政务配色；只有用户点击后才绑定模板。
                }
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun loadLibraryMaterials() {
        if (materialLibraryBusy) return
        materialLibraryBusy = true
        scope.launch {
            when (val result = repo.libraryMaterials()) {
                is ApiResult.Ok -> libraryMaterials = result.data.map {
                    PptLibraryMaterial(it["id"].str(), it["name"].str(),
                        it["caption"].str(),
                        it["thumb_url"].str().ifBlank { it["url"].str() },
                        it["source"].str().ifBlank { "personal" },
                        it["category"].str().ifBlank { "我的图片" },
                        it["credit"].str())
                }
                is ApiResult.Err -> status = result.message
            }
            materialLibraryBusy = false
        }
    }

    fun uploadLibraryMaterial(file: File) {
        if (materialLibraryBusy) return
        materialLibraryBusy = true
        status = "正在识别图片并加入素材库…"
        scope.launch {
            var reload = false
            when (val result = repo.uploadLibraryMaterial(file)) {
                is ApiResult.Ok -> {
                    status = result.data.obj()?.get("message").str().ifBlank { "图片已加入素材库" }
                    reload = true
                }
                is ApiResult.Err -> status = result.message
            }
            materialLibraryBusy = false
            if (reload) loadLibraryMaterials()
        }
    }

    fun uploadPublicImage(file: File, category: String, caption: String,
                          source: String, licenseNote: String) {
        if (materialLibraryBusy) return
        materialLibraryBusy = true
        status = "正在识别图片并加入公共图库…"
        scope.launch {
            when (val result = repo.uploadPublicImage(file, category, caption,
                                                       source, licenseNote)) {
                is ApiResult.Ok -> {
                    status = result.data.obj()?.get("message").str().ifBlank { "公共图片已上架" }
                    materialLibraryBusy = false
                    loadLibraryMaterials()
                }
                is ApiResult.Err -> { status = result.message; materialLibraryBusy = false }
            }
        }
    }

    fun updateImageCaption(material: PptLibraryMaterial, caption: String) {
        if (materialLibraryBusy) return
        materialLibraryBusy = true
        status = "正在更新图片说明…"
        scope.launch {
            when (val result = repo.updateImageCaption(material.id, material.source, caption)) {
                is ApiResult.Ok -> {
                    status = "图片说明已更新"
                    materialLibraryBusy = false
                    loadLibraryMaterials()
                }
                is ApiResult.Err -> {
                    status = result.message
                    materialLibraryBusy = false
                }
            }
        }
    }

    fun toggleLibraryMaterial(id: String) {
        autoImagesEnabled = false
        if (id in selectedMaterialIds) selectedMaterialIds.remove(id)
        else selectedMaterialIds.add(id)
    }

    fun toggleAutoImages() {
        autoImagesEnabled = !autoImagesEnabled
        if (autoImagesEnabled) selectedMaterialIds.clear()
    }

    private fun loadLayoutOptions(id: String?) {
        if (id.isNullOrBlank()) {
            layoutOptions = emptyList()
            return
        }
        scope.launch {
            when (val result = repo.templateDetail(id)) {
                is ApiResult.Ok -> if (templateId == id) {
                    layoutOptions = result.data["layout_library"].arr()
                        .mapNotNull { it.obj() }
                }
                is ApiResult.Err -> if (templateId == id) layoutOptions = emptyList()
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

    fun uploadTemplate(file: File, shared: Boolean = false, licenseNote: String = "") {
        busy = true
        status = "上传并学习模板中…"
        scope.launch {
            when (val r = repo.uploadTemplate(file, shared, licenseNote)) {
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

    fun openTemplateEditor(id: String) {
        if (templateEditorBusy) return
        templateEditorBusy = true
        status = "正在读取模板骨架…"
        scope.launch {
            when (val r = repo.templateDetail(id)) {
                is ApiResult.Ok -> {
                    templateEditor = r.data
                    status = null
                }
                is ApiResult.Err -> status = r.message
            }
            templateEditorBusy = false
        }
    }

    fun closeTemplateEditor() {
        templateEditor = null
    }

    fun saveTemplateEditor(
        id: String,
        name: String,
        category: String,
        description: String,
        font: String,
        layouts: Map<String, String>,
    ) {
        if (templateEditorBusy) return
        templateEditorBusy = true
        status = "正在保存模板骨架…"
        scope.launch {
            when (val r = repo.updateTemplate(
                id, name.trim(), category.trim(), description.trim(), font.trim(), layouts)) {
                is ApiResult.Ok -> {
                    status = "模板骨架已保存"
                    templateEditor = null
                    loadTemplates()
                }
                is ApiResult.Err -> status = r.message
            }
            templateEditorBusy = false
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

    fun downloadDrawio(id: String, target: File) {
        downloadingId = id
        scope.launch {
            status = when (val result = repo.downloadDrawio(id, target)) {
                is ApiResult.Ok -> result.data
                is ApiResult.Err -> result.message
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
        slides.map {
            SlideSnap(it.type, it.title, it.layout, it.pointsText,
                it.sources.toList(), it.rawSnapshot())
        },
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
        s.slides.forEach {
            slides.add(SlideEdit(it.type, it.title, it.pointsText.split("\n"), it.sources, it.raw)
                .also { slide -> slide.layout = it.layout })
        }
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

    /**
     * 进入新建页时加载一次可选知识库列表（服务端已按可见范围过滤）。
     * 失败静默：入口降级为不显示知识库区，不影响材料/主题路径。
     */
    fun loadKbs() {
        if (kbsLoaded || kbsLoading) return
        kbsLoading = true
        kbsError = null
        scope.launch {
            when (val r = repo.kbs()) {
                is ApiResult.Ok -> {
                    kbs = r.data
                    kbsLoaded = true
                }
                is ApiResult.Err -> {
                    // 瞬态网络错误不能永久吃掉知识库入口；保留重试机会。
                    kbsLoaded = false
                    kbsError = "知识库暂时加载失败"
                }
            }
            kbsLoading = false
        }
    }

    fun toggleKb(id: String) {
        if (id.isBlank()) return
        if (id in selectedKbIds) selectedKbIds.remove(id) else selectedKbIds.add(id)
    }

    // ================= 大纲生成（生成前预检 + 流式 + 回退 + 可取消） =================

    private fun outlineBody(): Map<String, Any?> {
        val content = buildString {
            // 关键信息放在材料正文之前：服务端会截取 content 前 6000 字，
            // 长材料也不能把年度/单位/落款日期截掉。
            if (generationYear.isNotBlank()) append("生成年份：").append(generationYear).append('\n')
            if (location.isNotBlank()) append("单位/地点：").append(location).append('\n')
            if (presenter.isNotBlank()) append("汇报人：").append(presenter).append('\n')
            if (reportDate.isNotBlank()) append("落款日期：").append(reportDate).append('\n')
            if (generationYear.isNotBlank() || location.isNotBlank() ||
                presenter.isNotBlank() || reportDate.isNotBlank()) append('\n')
            materials.forEach {
                append("【").append(it.filename).append("】\n").append(it.text).append("\n\n")
            }
        }.trim()
        return mutableMapOf<String, Any?>(
            "source_type" to if (materials.isNotEmpty()) "document" else "topic",
            "topic" to topic,
            "content" to content,
            "audience" to "",
            "scene" to "",
            "material_names" to materials.map { it.filename },
            "material_ids" to if (autoImagesEnabled) emptyList<String>() else selectedMaterialIds.toList(),
            "auto_images" to autoImagesEnabled,
            "theme_id" to themeId,
            "template_id" to templateId,
            "kb_ids" to selectedKbIds.toList(),
        ).apply {
            // “页数（可选）”为空时不要偷偷补默认值，让服务端按建议页数处理；
            // 用户明确填写时才触发精确页数约束。
            slideCount.toIntOrNull()?.let { put("slide_count", it) }
        }
    }

    /**
     * 发起一次大纲生成的公共前置流程（校验 + 防重复 + 生成前预检）。
     *
     * 两条路径共用这一段，避免「AI 智能设计」另写一套简化校验而漏掉防重复/预检：
     *
     * @param autoGenerate true 时生成页面方案后直接提交 PPT 任务；false 时停在确认页。
     * @param aiTarget 可选的本地导出位置；留空时生成结果保存在“我的作品”。
     */
    private fun beginOutline(autoGenerate: Boolean, aiTarget: File? = null) {
        val requestedPages = slideCount.toIntOrNull()
        if (slideCount.isNotBlank() && (requestedPages == null || requestedPages !in 2..18)) {
            status = "页数请输入 2–18，或留空由系统根据内容安排"
            return
        }
        if (topic.isBlank() && materials.isEmpty() && selectedKbIds.isEmpty()) {
            status = "请先填写汇报主题，或上传材料，或选择知识库"
            return
        }
        // 切走再切回会得到一个新的 ViewModel（busy 已重置），仅靠 busy 挡不住重复发起；
        // 而两次生成会并发跑，后完成的覆盖 pendingPptDocId，先完成的文档客户端就找不到了
        if (AppState.pptOutlineGenerating) {
            status = "还有一份正在生成，请稍候"
            return
        }
        if (pendingConfirm != null) return // 确认框还开着，等用户选择
        // 一次性标志统一在这里赋值：普通「生成大纲」顺带清掉上一次可能残留的标志
        autoDesignAfterOutline = autoGenerate
        aiDesignTarget = aiTarget
        busy = true
        AppState.pptLastError = null
        outlineStage = if (autoGenerate) "正在理解需求并规划页面…"
        else "正在检查关键信息是否齐全…"
        status = null
        val body = outlineBody()
        outlineJob = scope.launch {
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
                status = "生成前请确认几个关键信息（请确认后再生成）"
            } else {
                launchOutline(body)
            }
        }
    }

    /** 普通路径：只生成大纲，停在确认页供用户逐页确认与修改 */
    fun startOutline() = beginOutline(false)

    /**
     * 跳过页面方案确认，生成方案后直接提交 PPT 任务。
     *
     * 后台任务读取服务端已存的 `doc.outline` 来确定页数与内容，
     * 而 `doc_id` 只有大纲生成（SSE 的 done 事件）才会给——`startGenerateAsync` 开头
     * `val id = docId ?: return` 就是死在这上面。所以只能串行：先拿 docId，
     * 再在 [launchOutline] 末尾续接提交（见 [submitAiDesign]）。
     *
     * 预检发现信息不足时仍会弹确认框（[pendingConfirm]），用户明确确认后
     * 走 [confirmAndGenerate] 继续——那条路径同样认这个标志，所以仍能自动提交。
     *
     * @param target 可选的本地保存位置；留空时结果保存在“我的作品”。
     */
    fun startAiDesign(target: File? = null) {
        // 已经有任务在跑（生成中，或正卡在等用户回答追问）：再提交一份会顶掉在跑的那个，
        // 服务端也多半直接拒。在入口页就说清楚，好过点了之后没反应
        val running = job
        if (running != null && (running.isActive || running.status == PptJobStatus.CLARIFYING)) {
            status = "有一个 AI 设计任务正在进行（${running.stageText}），请先等它完成或取消"
            return
        }
        beginOutline(true, target)
    }

    /** 取消本次大纲生成：取消协程（底层 HTTP 请求随之中断），界面回到入口页 */
    fun cancelOutline() {
        outlineJob?.cancel()
        outlineJob = null
        pendingConfirm = null
        // 一次性标志：取消也算结束，必须复位，否则下一次「生成大纲」会被误当成 AI 设计
        autoDesignAfterOutline = false
        aiDesignTarget = null
        busy = false
        outlineStage = ""
        AppState.pptOutlineGenerating = false
        status = "已取消本次大纲生成"
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
        outlineJob = scope.launch { launchOutline(body) }
    }

    /** 取消本次生成（既不想确认也不想按默认方案跑） */
    fun cancelConfirm() {
        pendingConfirm = null
        status = null
        // 用户放弃确认 = 本次「AI 智能设计」到此为止：标志必须清掉，不能留到下一次生成
        autoDesignAfterOutline = false
        aiDesignTarget = null
    }

    /**
     * 真正发起大纲生成（预检通过或用户确认后调用）：
     * 全局标记保证切页不丢进度，结束（无论成败）一定复位。
     */
    private suspend fun launchOutline(body: Map<String, Any?>) {
        // 先取快照：finally 会无条件清掉标志，续接 AI 设计只能靠这份局部副本判断
        val autoDesign = autoDesignAfterOutline
        val autoTarget = aiDesignTarget
        // 全局标记：切到别的页面再切回时据此显示「正在生成中」；生成结束（无论成败）复位
        AppState.pptOutlineGenerating = true
        AppState.pptLastError = null
        outlineStage = if (autoDesign) "正在规划页面并准备生成 PPT…"
        else "正在理解材料与任务要求…"
        var ok = false
        try {
            ok = runOutline(body)
        } catch (e: CancellationException) {
            // 用户点了「取消生成」：向上抛出让协程正常结束，不当成失败
            throw e
        } catch (e: Exception) {
            status = "大纲生成中断：${e.message ?: "未知错误"}"
        } finally {
            // 生成协程不随页面切换取消，这里保证标记一定复位，不会永久卡在「生成中」
            busy = false
            AppState.pptOutlineGenerating = false
            // 一次性标志：成功 / 失败 / 取消三种情况都必须清掉，
            // 否则下一次普通「生成大纲」会被误当成 AI 设计（没有保存位置 → 任务静默不跑）
            autoDesignAfterOutline = false
            aiDesignTarget = null
        }
        // 失败原因记到全局：切走再切回时本地 status 会随 ViewModel 一起丢失，
        // 用户只会看到干净的入口页，以为生成"没了"
        AppState.pptLastError = if (ok) null
        else status?.takeIf { it.isNotBlank() } ?: "大纲生成未完成，请重试"
        // 「AI 智能设计」续接：走到这里说明 ok == true，applyOutline 已执行、docId 已有值，
        // 跳过确认页直接提交 PPTAgent 任务；大纲失败则不提交，停在原地把原因显示出来
        if (ok && autoDesign) submitAiDesign(autoTarget)
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
            @Suppress("UNCHECKED_CAST")
            val kbIds = (body["kb_ids"] as? List<String>) ?: emptyList()
            val slideCount = body["slide_count"] as? Int
            val audience = body["audience"] as? String ?: ""
            val scene = body["scene"] as? String ?: ""
            @Suppress("UNCHECKED_CAST")
            val materialNames = (body["material_names"] as? List<String>) ?: emptyList()
            @Suppress("UNCHECKED_CAST")
            val materialIds = (body["material_ids"] as? List<String>) ?: emptyList()
            val autoImages = body["auto_images"] as? Boolean ?: true
            when (val r2 = repo.outline(
                body["source_type"] as String, body["topic"] as String,
                body["content"] as String, slideCount, audience, scene,
                kbIds = kbIds, materialNames = materialNames,
                materialIds = materialIds, autoImages = autoImages,
                themeId = body["theme_id"] as? String,
                templateId = body["template_id"] as? String)) {
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

    private var outlineDesignSpec: JsonObject? = null

    private fun applyOutline(newDocId: String, outline: JsonObject) {
        if (newDocId.isNotBlank()) {
            docId = newDocId
            // 记录到全局：切到别的页面再切回时按此 id 从服务端恢复大纲与工作台
            AppState.pendingPptDocId = newDocId
        }
        outlineTitle = outline["title"].str().ifBlank { topic.ifBlank { "未命名PPT" } }
        outlineSubtitle = outline["subtitle"].str()
        outlineDesignSpec = outline["design_spec"].obj()
        selectedMaterialIds.clear()
        selectedMaterialIds.addAll(outline["material_ids"].arr().map { it.str() }
            .filter { it.isNotBlank() })
        autoImagesEnabled = outline["image_selection_mode"].str() == "auto"
        slides.clear()
        outline["slides"].arr().mapNotNull { it.obj() }.forEach { slides.add(SlideEdit.fromJson(it)) }
        if (slides.isEmpty()) {
            slides.add(SlideEdit("content", "第一页", listOf("点击右侧 AI 助手或直接编辑"), emptyList()))
        }
        selected = 0
        undoStack.clear()
        canUndo = false
        previewPages = emptyList()
        visualReviewIssues = emptyList()
        visualReviewSummary = null
        loadLayoutOptions(templateId)
        step = PptStep.OUTLINE
        outlineStage = ""
        status = "大纲已生成（${slides.size} 页），请逐页确认或修改"
    }

    /**
     * 「AI 智能设计」的第二段：大纲刚生成完（[applyOutline] 已写入 docId），
     * 这里**不停在确认页**，直接提交后台 PPT 任务。
     *
     * 复用 [startGenerateAsync] 而不是另写一份：那条路径已经处理了
     * 提交前落草稿（任务读取服务端 doc.outline，不落就是上一次的大纲）、
     * 提交即返回、以及后端没部署 /ppt/jobs 时回退同步导出——这里不该改回退策略。
     *
     * 与工作台顶部「AI 生成 PPT」的区别只是少了「再改改」那一步确认：
     * 用户在入口页点「AI 智能设计」时就已经表达过"直接设计"的意图。
     */
    private fun submitAiDesign(target: File?) {
        if (docId == null) {
            // 流式接口没回 doc_id（一次性回退同样可能为空）：提交不了任务。
            // 至少停在确认页让用户看到已经生成的大纲，而不是点了之后什么都不发生
            status = "AI 设计未能启动：本次大纲没拿到文档标识，请重试或先点「生成大纲」"
            AppState.pptLastError = status
            return
        }
        // 直接进工作台：任务一提交，界面就切到异步生成工作台（逐页出图 + 进度 + 可取消）；
        // 后端没部署 /ppt/jobs 时会回退同步导出，同样在工作台里看 exportStage 进度
        step = PptStep.WORKBENCH
        status = "页面方案已生成（${slides.size} 页），正在生成 PPT…"
        startGenerateAsync(target)
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

    /**
     * 大纲确认后的唯一出片入口：用户确认逐页内容后直接提交 PPTAgent。
     * 生成结果保存在服务端“我的作品”中；本地文件仅在用户之后主动点击下载时写出。
     * 复用现有异步任务链，提交前会先保存当前大纲，DeepPresenter/PPTAgent 读取的是确认后的版本。
     */
    fun confirmOutlineAndGenerate() {
        if (docId == null || slides.isEmpty()) {
            status = "请先生成并确认大纲"
            return
        }
        step = PptStep.WORKBENCH
        status = "大纲已确认，正在提交 AI 视觉设计任务；完成后自动保存到“我的作品”…"
        startGenerateAsync()
    }

    fun toWorkbench() {
        step = PptStep.WORKBENCH
        status = null
        refreshPreview()
    }
    fun backToOutline() { if (docId != null) step = PptStep.OUTLINE }
    /**
     * 从大纲确认页回到入口修改初始需求。
     * 保留 [docId] 和大纲内容，便于用户继续修改；关闭已打开文档请使用 [closeDocument]。
     */
    fun backToEntry() {
        step = PptStep.ENTRY
        AppState.pendingPptDocId = null
        AppState.pptLastError = null
    }

    /**
     * 关闭当前文档并回到新建入口。
     *
     * 与 [backToEntry] 的区别：[backToEntry] 只是从「大纲确认页」退回改初始需求，
     * 文档还在；这里是**真正退出这份 PPT**——必须把 `docId` 与大纲一起清掉，
     * 否则 `PptScreen` 里 `tab == 0 && step == WORKBENCH` 优先级更高，
     * 回到入口页后会立刻掉回工作台，用户永远出不去。
     *
     * 当前文档绑定、大纲与预览状态都会被清空；PPTAgent 生成任务是独立的长任务，
     * 仅在没有任务或任务已终态时清理其句柄，避免误删仍在生成、
     * 或正等待用户补充信息（CLARIFYING）的任务。
     */
    fun closeDocument() {
        step = PptStep.ENTRY
        docId = null
        slides.clear()
        outlineTitle = ""
        outlineSubtitle = ""
        outlineDesignSpec = null
        exportStage = ""
        previewPages = emptyList()
        previewBusy = false
        visualReviewBusy = false
        visualReviewIssues = emptyList()
        visualReviewSummary = null
        layoutOptions = emptyList()
        selectedMaterialIds.clear()
        autoImagesEnabled = true
        selected = 0
        status = null
        AppState.pendingPptDocId = null
        AppState.pptLastError = null

        val jobStatus = PptJobEngine.current?.status
        val jobIsRunning = jobStatus == PptJobStatus.SUBMITTED ||
            jobStatus == PptJobStatus.GENERATING ||
            jobStatus == PptJobStatus.CLARIFYING
        if (!jobIsRunning) {
            PptJobEngine.stopPolling()
            PptJobEngine.reset()
            AppState.pendingPptJobId = null
        }
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
                        templateId = d["template_id"].str().ifBlank { null }
                        applyOutline(id, ol)
                        step = PptStep.WORKBENCH
                        status = "已打开「${d["title"].str()}」"
                        // 打开成功即说明"上次生成失败"已成过去：不清的话那条红字横幅
                        // 会一直挂在入口页，用户每次切回 PPT 都以为又失败了
                        AppState.pptLastError = null
                        refreshPreview()
                    } else status = "文档内容为空"
                }
                is ApiResult.Err -> {
                    status = r.message
                    // 文档在服务端已不存在（被删除 / 换账号 / 服务端清理）：
                    // 必须清掉全局恢复句柄，否则每次切回 PPT 都会再请求一次这个 id
                    // 并弹同一条红字——这正是"切一次报一次错"的直接来源
                    if (r.status == 404 || r.status == 403 || r.status == 401) {
                        AppState.pendingPptDocId = null
                    }
                }
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
        outlineDesignSpec?.let { put("design_spec", it) }
        put("image_selection_mode",
            if (autoImagesEnabled) "auto" else if (selectedMaterialIds.isEmpty()) "off" else "manual")
        // 自动配图的候选范围由服务端决定，客户端不要回传空数组：
        // 空数组表示「明确不使用图片」，会把文档已记录的 material_ids 清掉，
        // 导致重新导出时公共图库图片无法解析。
        if (!autoImagesEnabled) {
            putJsonArray("material_ids") { selectedMaterialIds.forEach { add(it) } }
        }
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
    private var previewQueued = false

    fun refreshPreview() {
        val id = docId ?: return
        // 渲染进行中又收到新的刷新请求（切模板/手动刷新）：不能静默吞掉——
        // 排队一轮，当前渲染结束后按最新模板再渲染一次，否则用户切了模板看不到任何反应
        if (previewBusy) { previewQueued = true; return }
        previewBusy = true
        scope.launch {
            repo.saveDraft(id, outlineTitle, outlineJson(), templateId)
            val result = repo.preview(id)
            // 用户可能在渲染期间关闭文档或打开了另一份；旧请求不得回写新界面的预览状态。
            if (docId == id) {
                when (result) {
                    is ApiResult.Ok ->
                        previewPages = result.data.obj()?.get("pages").arr().map { it.str() }
                            .filter { it.isNotBlank() }.also { previewRevision++ }
                    is ApiResult.Err -> previewPages = emptyList() // 服务端未部署/无 LibreOffice
                }
                previewBusy = false
            } else {
                // 文档已切换：本次请求作废的同时必须把 busy 放掉，
                // 否则 previewBusy 永久卡死，之后所有刷新/切模板都会被当成"渲染中"吞掉
                previewBusy = false
            }
            // 排队中的刷新请求：按当前（可能已切换的）模板再来一轮
            if (previewQueued) {
                previewQueued = false
                if (docId != null) refreshPreview()
            }
        }
    }

    /**
     * 工作台内切换模板的唯一入口：写 templateId → 立即重渲染预览，
     * 并明确告诉用户"已生效 + 想出新片要重新生成"。此前直接赋值 + refreshPreview，
     * 渲染中切换会被静默吞掉（点了没反应），且没有任何文字反馈。
     */
    fun switchTemplate(id: String?) {
        if (templateId == id) return
        templateId = id
        loadLayoutOptions(id)
        val name = templates.firstOrNull { it["id"].str() == id }
            ?.get("name").str().ifBlank { null } ?: "自适应排版"
        status = "已切换为「$name」，正在重新渲染预览；要更新 PPT 成品请点「AI 生成 PPT」重新生成"
        refreshPreview()
    }

    fun selectSlideLayout(layoutId: String) {
        val slide = slides.getOrNull(selected) ?: return
        if (slide.layout == layoutId) return
        pushUndo()
        slide.layout = layoutId
        slide.layoutLocked = layoutId.isNotBlank()
        visualReviewIssues = emptyList()
        visualReviewSummary = null
        status = if (layoutId.isBlank()) "已恢复自动版式，正在刷新预览"
            else "已选择本页版式，正在刷新预览"
        refreshPreview()
    }

    fun runVisualReview() {
        val id = docId ?: return
        if (visualReviewBusy) return
        visualReviewBusy = true
        visualReviewSummary = "正在检查实际渲染页面…"
        visualReviewIssues = emptyList()
        scope.launch {
            when (val save = repo.saveDraft(id, outlineTitle, outlineJson(), templateId)) {
                is ApiResult.Err -> {
                    if (docId == id) {
                        visualReviewSummary = save.message
                        visualReviewBusy = false
                    }
                    return@launch
                }
                is ApiResult.Ok -> Unit
            }
            val result = repo.visualReview(id)
            if (docId != id) {
                visualReviewBusy = false
                return@launch
            }
            when (result) {
                is ApiResult.Ok -> {
                    val root = result.data.obj()
                    val checked = root?.get("rendered_pages_checked").int()
                    visualReviewSummary = root?.get("summary").str().ifBlank { "视觉复检完成" } +
                        if (checked > 0) " · 已让本地模型审看 $checked 页" else " · 已完成排版规则检查"
                    visualReviewIssues = root?.get("issues").arr().mapNotNull { item ->
                        item.obj()?.let { issue ->
                            PptVisualIssue(issue["page"].int(), issue["code"].str(),
                                issue["severity"].str(), issue["message"].str())
                        }
                    } ?: emptyList()
                }
                is ApiResult.Err -> {
                    visualReviewSummary = result.message
                    visualReviewIssues = emptyList()
                }
            }
            visualReviewBusy = false
        }
    }

    /**
     * 生成并导出：先保存草稿，再由 PPTAgent 真实渲染 pptx，最后让用户选保存位置下载。
     * 全程分阶段可见（exportStage），可取消。
     */
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
        exportStage = "正在保存大纲草稿…"
        status = null
        exportJob = scope.launch {
            var failed: String? = null
            try {
                repo.saveDraft(id, outlineTitle, outlineJson(), templateId)
                exportStage = "PPTAgent 正在按模板渲染 PPT…"
                when (val r = repo.generate(id, outlineJson(), templateId)) {
                    is ApiResult.Ok -> {
                        exportStage = "渲染完成，正在写入文件…"
                        // 紧跟 PPTAgent 渲染的这次下载按长任务放宽（默认 5 分钟可能不够）
                        status = when (val d = repo.downloadDocument(
                            id, target, timeoutMs = PptRepository.TIMEOUT_EXPORT_MS)) {
                            is ApiResult.Ok -> d.data
                            is ApiResult.Err -> d.message.also { failed = it }
                        }
                        loadDocuments()
                    }
                    is ApiResult.Err -> status = r.message.also { failed = it }
                }
            } catch (e: CancellationException) {
                // 用户点了「取消」：不当成失败
                throw e
            } catch (e: Exception) {
                failed = "导出失败：${e.message ?: "未知错误"}"
                status = failed
            } finally {
                // 导出协程同样不随页面切换取消，这里保证标记一定复位
                busy = false
                exportStage = ""
                AppState.pptExporting = false
            }
            // 切走期间导出失败时，本地 status 会随 ViewModel 一起丢失
            AppState.pptLastError = failed
        }
    }

    // ================= 异步生成（主路径）：提交 → 轮询 → 逐页预览 → 落盘 =================

    /**
     * 提交生成任务并立即返回（不等渲染）：POST /ppt/jobs → job_id。
     * 之后由 PptJobEngine 轮询进度，界面按阶段出缩略图，跑完自动把 pptx 写到 [target]。
     *
     * 服务端尚未部署 /ppt/jobs（HTTP 404/405）时**回退到同步导出**，
     * 保证后端没跟上时功能不倒退（同步路径的超时已放宽到 20 分钟）。
     */
    fun startGenerateAsync(target: File? = null, overrideMessage: String? = null) {
        val id = docId ?: return
        // 同 startOutline：切回页面后 busy 已重置，仅靠 busy 挡不住重复发起
        if (AppState.pptExporting) {
            status = "还有一份正在导出，请稍候"
            return
        }
        if (job?.isActive == true) {
            status = "有一个生成任务正在进行，请等待完成或先取消"
            return
        }
        // 重试时用提交时的原始需求：ViewModel 可能已被重建（切过页面），本地字段会是空的
        val message = overrideMessage?.takeIf { it.isNotBlank() } ?: buildJobMessage()
        busy = true
        AppState.pptExporting = true
        AppState.pptLastError = null
        exportStage = ""
        status = null
        scope.launch {
            // 大纲走服务端已存的 doc.outline（PPTAgent 直接读它算页数、拼需求），
            // 所以提交前必须先落一次草稿，否则服务端拿到的是上一次的大纲
            repo.saveDraft(id, outlineTitle, outlineJson(), templateId)
            val r = PptJobEngine.submit(repo, id, message, target)
            // 提交只是「登记任务」，秒回；真正的等待交给轮询，
            // 这里必须把 busy / 全局导出标记放掉，否则用户没法再操作（也挡住了回退路径）
            busy = false
            AppState.pptExporting = false
            when (r) {
                is ApiResult.Ok -> if (r.data.status == "failed") {
                    ClientLog.warn("异步生成被服务端拒绝：" + r.data.hint)
                    PptJobEngine.reset()
                    if (target != null) {
                        generateAndExport(target)
                    } else {
                        status = r.data.hint.ifBlank { "后台生成服务暂不可用，请联系管理员" }
                        AppState.pptLastError = status
                    }
                } else {
                    status = "已提交生成任务，可先去其他页面，完成后会自动回到这里"
                }
                is ApiResult.Err -> {
                    if (r.status == 404 || r.status == 405) {
                        ClientLog.warn("异步生成接口不可用（HTTP " + r.status + "）")
                        PptJobEngine.reset()
                        if (target != null) {
                            generateAndExport(target)
                        } else {
                            status = "服务器暂不支持后台生成，请联系管理员完成服务升级"
                            AppState.pptLastError = status
                        }
                    } else {
                        AppState.pptLastError = r.message
                        status = r.message
                    }
                }
            }
        }
    }

    /**
     * 给 PPTAgent 的补充需求（正文与页数由服务端已存的大纲带过去）。
     *
     * **不写页数**：后端 `num_pages = len(doc.outline["slides"])`，页数就是大纲条数，
     * message 里再写「请生成 N 页」会和大纲冲突（后端同学明确要求）。
     * 只写用户能确认的事实，不替他编需求。
     */
    private fun buildJobMessage(): String = buildString {
        if (topic.isNotBlank()) append("主题：").append(topic).append('\n')
        if (outlineTitle.isNotBlank() && outlineTitle != topic)
            append("标题：").append(outlineTitle).append('\n')
        if (generationYear.isNotBlank()) append("生成年份：").append(generationYear).append('\n')
        if (location.isNotBlank()) append("单位/地点：").append(location).append('\n')
        if (presenter.isNotBlank()) append("汇报人：").append(presenter).append('\n')
        if (reportDate.isNotBlank()) append("落款日期：").append(reportDate).append('\n')
        if (materials.isNotEmpty())
            append("参考材料：").append(materials.joinToString("、") { it.filename }).append('\n')
    }.trim()

    /**
     * 回答 PPTAgent 的追问：POST /ppt/jobs/{id}/clarify。
     * 后端带着「它问了什么 / 用户答了什么」的上下文续跑**同一个任务**，不会从头再来。
     */
    fun submitClarify(answer: String) {
        PptJobEngine.clarify(answer)
    }

    /**
     * 取消当前异步任务。
     * 语义是**停止等待**——PPTAgent 侧已启动的生成无法远程终止，会在服务端跑完（产物无人取），
     * 所以文案说「已停止等待」，不说「已终止生成」。
     */
    fun cancelJob() {
        PptJobEngine.cancel()
        status = "已停止等待本次生成（服务端会跑完，但不会保存到你的文件）"
    }

    /** 取消 / 完成后回到普通编辑工作台（清掉任务句柄，文件已保存则保留提示） */
    fun dismissJob() {
        PptJobEngine.reset()
        loadDocuments()
        status = null
        // 生成完成后回到编辑工作台：必须重渲染预览。
        // 否则看到的还是生成前的旧版式预览（甚至空骨架），
        // 用户会以为"生成的 PPT 长这样"或"换的模板没生效"。
        refreshPreview()
    }

    /** FAILED / CANCELLED 后重试：复用提交时需求；本地保存位置可稍后再选。 */
    fun retryJob() {
        val p = PptJobEngine.current ?: return
        val target = p.targetFile
        val message = p.message
        PptJobEngine.reset()
        startGenerateAsync(target, message)
    }

    /** 生成完成：补拉一次页面清单，兜住终态前最后一轮预览拉取失败导致的缺页缩略图 */
    fun refreshJobPages() {
        PptJobEngine.refreshPreviewOnce()
    }

    /**
     * DONE 状态下再下一份 pptx。
     * [target] 为 null 表示沿用提交时选好的位置；两者都没有时提示用户先选位置。
     */
    fun downloadJobResult(target: File? = null) {
        if (!PptJobEngine.download(target)) status = "请先选择保存位置"
    }

    /** 切回页面：把仍在跑的全局任务重新挂上（必要时续接轮询 / 补一次落盘） */
    fun resumeJob() {
        PptJobEngine.resumeIfNeeded(repo)
    }

    /**
     * 离开页面：停掉轮询协程。
     * 任务状态与目标文件都在服务端与全局对象里，回来时 [resumeJob] 会续上，
     * 不这样处理每个页面都会留下一条永远跑着的轮询协程。
     */
    fun stopJobPolling() {
        PptJobEngine.stopPolling()
    }

    /** 取消导出：中断等待（服务端已渲染的部分不影响，本地不会写入半成品文件） */
    fun cancelExport() {
        exportJob?.cancel()
        exportJob = null
        busy = false
        exportStage = ""
        AppState.pptExporting = false
        status = "已取消本次导出"
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

    fun aiVisual(kind: String) {
        val index = selected
        if (index !in slides.indices || aiBusy) return
        val original = slides[index].toJson()
        val document = docId
        val chosenTemplate = templateId
        val instruction = aiInstruction.trim()
        aiBusy = true
        aiNote = null
        scope.launch {
            when (val result = repo.aiVisual(kind, original, instruction, chosenTemplate)) {
                is ApiResult.Ok -> {
                    val payload = result.data.obj()
                    val changed = payload?.get("slide").obj()
                    if (changed != null) {
                        if (docId != document || templateId != chosenTemplate ||
                            slides.getOrNull(index)?.toJson() != original) {
                            aiNote = "文稿、页面或模板已变化，图示未覆盖当前内容，请重新生成"
                        } else {
                            pushUndo()
                            slides[index].replaceWith(changed)
                            val warning = payload?.get("warnings").arr().firstOrNull()?.str()
                            aiNote = warning ?: "已更新第 ${index + 1} 页图示"
                            refreshPreview()
                        }
                    } else aiNote = "AI 未返回有效图示"
                }
                is ApiResult.Err -> aiNote = result.message
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

    /** 大纲确认页：按一句自然语言整体调整，并把结果立即写回服务端草稿。 */
    fun aiAdjustOutline() {
        val instruction = outlineAdjustInstruction.trim()
        if (instruction.isBlank() || slides.isEmpty() || aiBusy) return
        aiBusy = true
        aiNote = null
        scope.launch {
            when (val r = repo.aiOutlineAdjust(outlineJson(), instruction)) {
                is ApiResult.Ok -> {
                    val ol = r.data.obj()?.get("outline").obj()
                    if (ol != null) {
                        pushUndo()
                        outlineTitle = ol["title"].str().ifBlank { outlineTitle }
                        outlineSubtitle = ol["subtitle"].str()
                        val arr = ol["slides"].arr().mapNotNull { it.obj() }
                        if (arr.isNotEmpty()) {
                            slides.clear()
                            arr.forEach { slides.add(SlideEdit.fromJson(it)) }
                            selected = selected.coerceIn(
                                0, (slides.size - 1).coerceAtLeast(0))
                            outlineAdjustInstruction = ""
                            aiNote = "大纲已按要求调整"
                            val id = docId
                            if (id != null) {
                                repo.saveDraft(id, outlineTitle, outlineJson(), templateId)
                            }
                        } else {
                            aiNote = "AI 未返回有效大纲"
                        }
                    } else {
                        aiNote = "AI 未返回有效大纲"
                    }
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
