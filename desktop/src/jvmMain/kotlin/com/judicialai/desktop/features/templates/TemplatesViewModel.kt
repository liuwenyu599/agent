package com.judicialai.desktop.features.templates

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
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
import kotlinx.serialization.json.JsonObject

class TemplatesViewModel(private val repo: TemplatesRepository) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var templates by mutableStateOf(listOf<JsonObject>())
        private set
    var categories by mutableStateOf(listOf<String>())
        private set
    var filterCat by mutableStateOf<String?>(null)
    var status by mutableStateOf<String?>(null)

    /** 公文助手填写视图状态（对应 Web TemplateView） */
    var usingTemplate by mutableStateOf<JsonObject?>(null)
        private set
    var generating by mutableStateOf(false)
        private set
    var result by mutableStateOf("")
        private set

    // ---- 模板三层：系统模板 / 本科室模板 / 我的模板（tier 由后端按归属判定）----
    var tier by mutableStateOf<String?>(null)

    /**
     * 系统模板 → 本科室模板的 AI 草案（未落库）。
     * 知识管理员校核后再保存，保证「AI 建议 + 人工确认」。
     */
    var adapting by mutableStateOf(false)
        private set
    var adaptError by mutableStateOf<String?>(null)
        private set

    /** 系统模板 → 本科室模板草案（未落库，AI 建议 + 人工确认后才保存） */
    var draft by mutableStateOf<Map<String, String>?>(null)
        private set

    fun tierOf(t: JsonObject): String = t["tier"].str().ifBlank { "system" }

    fun shown(): List<JsonObject> {
        val base = templates.filter { filterCat == null || it["category"].str() == filterCat }
        return if (tier == null) base else base.filter { tierOf(it) == tier }
    }

    fun startUse(t: JsonObject) {
        usingTemplate = t
        result = ""
        scope.launch { repo.markUsed(t["id"].str()) }
    }

    fun cancelUse() {
        usingTemplate = null
        result = ""
    }

    /** 组装要素与 system_prompt，调 /chat/send（与 Web TemplateView.generate 一致） */
    fun generate(params: Map<String, Pair<String, String>>) {
        val t = usingTemplate ?: return
        val elements = t["params_schema"].arr().mapNotNull { it.obj() }.mapNotNull { f ->
            val name = f["name"].str()
            val label = f["label"].str().ifBlank { name }
            val v = params[name]?.second?.trim().orEmpty()
            if (v.isEmpty()) null else "$label：$v"
        }
        var sp = t["system_prompt"].str().ifBlank { "你是一位资深的司法行政公文写作专家。" }
        sp += "\n\n写作要求：\n1. 写作风格：${t["writing_style"].str().ifBlank { "正式公文" }}；"
        sp += "\n2. 字数要求：约 ${t["word_count"].int().let { if (it > 0) it else 1000 }} 字；"
        if (t["need_red_header"].bool()) sp += "\n3. 需要包含红头（发文机关标识）；"
        if (t["need_signature"].bool()) sp += "\n4. 需要包含落款（发文机关署名）；"
        if (t["need_date"].bool()) sp += "\n5. 需要包含成文日期；"
        if (t["need_doc_number"].bool()) sp += "\n6. 需要包含发文字号；"
        sp += "\n\n请根据以下要素生成完整的公文正文，不要简单填空，要根据要素展开成流畅、规范的公文。"
        sp += "\n\n【格式要求】\n1. 不要输出 Markdown 标记（如 **、## 等），不要输出 HTML 标签；\n2. 纯文本输出，段落之间用空行分隔；\n3. 一级标题（如“一、评查范围”）独占一行，前后空一行；\n4. 落款信息（联系人、电话、单位、日期、文号）每项独占一行；\n5. 不要输出解释性文字，直接给公文正文。"

        var msg = "请根据以下要素生成公文：\n\n" + elements.joinToString("\n")
        t["content_template"].str().takeIf { it.isNotBlank() }?.let {
            msg += "\n\n【结构参考】\n$it"
        }

        generating = true
        status = null
        scope.launch {
            when (val r = repo.generate(msg, sp)) {
                is ApiResult.Ok -> result = r.data.obj()?.get("reply")?.str()
                    ?: r.data.obj()?.get("message")?.str() ?: ""
                is ApiResult.Err -> status = r.message
            }
            generating = false
        }
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

    /** 把系统模板按本科室写作习惯生成科室模板草案（只返回建议，不落库） */
    fun adaptForDepartment(t: JsonObject, hints: String) {
        adapting = true
        status = null
        scope.launch {
            when (val r = repo.adaptForDept(t["id"].str(), hints)) {
                is ApiResult.Ok -> {
                    val o = r.data.obj()
                    draft = if (o == null) null else mapOf(
                        "source_template_id" to o["source_template_id"].str(),
                        "name" to o["name"].str(),
                        "dept_name" to o["dept_name"].str(),
                        "category" to o["category"].str(),
                        "content_template" to o["content_template"].str(),
                        "source" to o["source"].str(),
                    )
                    if (draft == null) status = "未生成科室模板草案"
                }
                is ApiResult.Err -> status = r.message
            }
            adapting = false
        }
    }

    /** 人工确认后保存为本科室模板（科室归属由服务端写入） */
    fun saveDepartmentTemplate(name: String, content: String) {
        val d = draft ?: return
        if (name.isBlank() || content.isBlank()) {
            status = "模板名称与正文不能为空"
            return
        }
        scope.launch {
            when (val r = repo.saveDeptTemplate(mapOf(
                "name" to name,
                "content_template" to content,
                "category" to d["category"].orEmpty(),
                "source_template_id" to d["source_template_id"].orEmpty(),
            ))) {
                is ApiResult.Ok -> {
                    status = "已保存为本科室模板"
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

    /** 导出当前生成结果为 Word */
    fun exportResult(title: String, target: java.io.File) {
        scope.launch {
            status = when (val r = repo.exportResult(title, result, target)) {
                is ApiResult.Ok -> r.data
                is ApiResult.Err -> r.message
            }
        }
    }
}

