package com.judicialai.desktop.features.templates

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.app.PendingTemplateWrite
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.bool
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

class TemplatesViewModel(private val repo: TemplatesRepository) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var templates by mutableStateOf(listOf<JsonObject>())
        private set
    var categories by mutableStateOf(listOf<String>())
        private set
    var filterCat by mutableStateOf<String?>(null)
    var status by mutableStateOf<String?>(null)

    var usingTemplate by mutableStateOf<JsonObject?>(null)
        private set

    var tier by mutableStateOf<String?>(null)

    var adapting by mutableStateOf(false)
        private set
    var adaptError by mutableStateOf<String?>(null)
        private set

    var draft by mutableStateOf<JsonObject?>(null)
        private set

    var selectedId by mutableStateOf<String?>(null)
        private set
    var preview by mutableStateOf<JsonObject?>(null)
        private set

    val canSaveDeptTemplate: Boolean
        get() = AppState.isKnowledgeAdmin || AppState.isDeveloper

    fun tierOf(t: JsonObject): String = t["tier"].str().ifBlank { "system" }

    /**
     * 预览兼容层：服务端 structure 的正式结构是 [{name, guide}, ...]，
     * 旧 PreviewPane 仍按字符串数组渲染。这里只对 preview 做显示归一化，
     * 原模板对象/编辑保存仍保留对象数组，避免破坏 guide 等结构化字段。
     */
    private fun normalizePreviewStructure(t: JsonObject): JsonObject {
        val raw = t["structure"].arr()
        if (raw.isEmpty()) return t
        val names = raw.mapNotNull { item ->
            item.obj()?.get("name").str().ifBlank { item.str() }.takeIf { it.isNotBlank() }
        }
        if (names.isEmpty()) return t
        return JsonObject(t + ("structure" to JsonArray(names.map(::JsonPrimitive))))
    }

    fun select(t: JsonObject) {
        val id = t["id"].str()
        selectedId = id
        preview = normalizePreviewStructure(t)
        scope.launch {
            when (val r = repo.detail(id)) {
                is ApiResult.Ok -> preview = normalizePreviewStructure(r.data.obj() ?: t)
                is ApiResult.Err -> Unit
            }
        }
    }

    fun clearSelection() {
        selectedId = null
        preview = null
    }

    fun shown(): List<JsonObject> {
        val base = templates.filter { filterCat == null || it["category"].str() == filterCat }
        return if (tier == null) base else base.filter { tierOf(it) == tier }
    }

    fun startUse(t: JsonObject) {
        usingTemplate = t
        scope.launch { repo.markUsed(t["id"].str()) }
    }

    fun cancelUse() {
        usingTemplate = null
    }

    fun launchWorkspace(params: Map<String, Pair<String, String>>) {
        val t = usingTemplate ?: return
        val elements = t["params_schema"].arr().mapNotNull { it.obj() }.mapNotNull { f ->
            val name = f["name"].str()
            val label = f["label"].str().ifBlank { name }
            val v = params[name]?.second?.trim().orEmpty()
            if (v.isEmpty()) null else "$label：$v"
        }
        var msg = if (elements.isEmpty()) {
            "请使用模板「${t["name"].str()}」生成一份公文。"
        } else {
            "请根据以下要素生成公文：\n\n" + elements.joinToString("\n")
        }
        t["content_template"].str().takeIf { it.isNotBlank() }?.let {
            msg += "\n\n【结构参考】\n$it"
        }
        AppState.lastTemplateUseId = t["id"].str()
        AppState.lastTemplateUseValues = params.mapValues { it.value.second }
        AppState.pendingWritingTemplate = PendingTemplateWrite(
            templateId = t["id"].str(),
            templateName = t["name"].str(),
            docType = t["category"].str(),
            title = t["name"].str(),
            message = msg,
        )
        usingTemplate = null
        AppState.navigate(AppScreen.WRITING)
    }

    fun load() {
        scope.launch {
            when (val r = repo.list()) {
                is ApiResult.Ok -> templates = r.data
                is ApiResult.Err -> status = r.message
            }
            when (val r = repo.categories()) {
                is ApiResult.Ok -> categories = r.data
                is ApiResult.Err -> {}
            }
        }
    }

    fun initBuiltin() {
        scope.launch {
            when (val r = repo.initBuiltin()) {
                is ApiResult.Ok -> { status = "已初始化内置模板"; load() }
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun adaptForDepartment(t: JsonObject, hints: String) {
        adapting = true
        status = null
        scope.launch {
            when (val r = repo.adaptForDept(t["id"].str(), hints)) {
                is ApiResult.Ok -> {
                    draft = r.data.obj()
                    if (draft == null) status = "未生成模板调整草案"
                }
                is ApiResult.Err -> status = r.message
            }
            adapting = false
        }
    }

    fun saveAdaptedTemplate(name: String, content: String) {
        val d = draft ?: return
        if (name.isBlank() || content.isBlank()) {
            status = "模板名称与正文不能为空"
            return
        }
        val category = d["category"].str().ifBlank { "科室模板" }
        val baseType = d["base_type"].str().ifBlank { "公文" }
        val templateKind = d["template_kind"].str().ifBlank { "official_doc" }
        val writingStyle = d["writing_style"].str().ifBlank { "正式公文" }
        val wordCount = d["word_count"].int().let { if (it > 0) it else 1000 }
        val paramsSchema = d["params_schema"] ?: JsonArray(emptyList())
        val structure = d["structure"] ?: JsonArray(emptyList())
        val tags = d["tags"] ?: JsonArray(emptyList())

        scope.launch {
            val r = if (canSaveDeptTemplate) {
                repo.saveDeptTemplate(mapOf(
                    "name" to name,
                    "content_template" to content,
                    "category" to category,
                    "base_type" to baseType,
                    "description" to d["description"].str(),
                    "params_schema" to paramsSchema,
                    "structure" to structure,
                    "system_prompt" to d["system_prompt"].str(),
                    "writing_guide" to d["writing_guide"].str(),
                    "writing_style" to writingStyle,
                    "word_count" to wordCount,
                    "need_red_header" to d["need_red_header"].bool(),
                    "need_signature" to d["need_signature"].bool(true),
                    "need_date" to d["need_date"].bool(true),
                    "need_doc_number" to d["need_doc_number"].bool(),
                    "template_kind" to templateKind,
                    "tags" to tags,
                    "source_template_id" to d["source_template_id"].str(),
                ))
            } else {
                repo.create(mapOf(
                    "name" to name,
                    "category" to category,
                    "base_type" to baseType,
                    "content_template" to content,
                    "description" to d["description"].str()
                        .ifBlank { "基于系统模板按个人写作习惯调整" },
                    "visibility" to "personal",
                    "params_schema" to paramsSchema,
                    "structure" to structure,
                    "system_prompt" to d["system_prompt"].str(),
                    "writing_guide" to d["writing_guide"].str(),
                    "writing_style" to writingStyle,
                    "word_count" to wordCount,
                    "need_red_header" to d["need_red_header"].bool(),
                    "need_signature" to d["need_signature"].bool(true),
                    "need_date" to d["need_date"].bool(true),
                    "need_doc_number" to d["need_doc_number"].bool(),
                    "template_kind" to templateKind,
                    "tags" to tags,
                ))
            }
            when (r) {
                is ApiResult.Ok -> {
                    status = if (canSaveDeptTemplate) "已保存为本科室模板" else "已保存为我的模板"
                    draft = null
                    load()
                }
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun cancelDraft() {
        draft = null
        status = null
    }

    fun save(editing: JsonObject?, body: Map<String, Any?>) {
        scope.launch {
            val r = if (editing == null) repo.create(body)
            else repo.update(editing["id"].str(), body)
            when (r) {
                is ApiResult.Ok -> { status = "已保存"; load() }
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun delete(id: String) {
        scope.launch {
            when (val r = repo.delete(id)) {
                is ApiResult.Ok -> load()
                is ApiResult.Err -> status = r.message
            }
        }
    }
}
