package com.judicialai.desktop.features.formatcheck

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import com.judicialai.desktop.core.logging.ClientLog
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.bool
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import java.io.File

/** 文档版本：修改前（源文档） / 当前版本（已应用修改后） */
enum class DocVersion(val label: String, val query: String) {
    ORIGINAL("修改前", "original"),
    CURRENT("当前版本", "current"),
}

/** 文档区缩放档位（编辑器基准字号 sp） */
enum class DocZoom(val label: String, val baseSp: Float) {
    SMALL("小", 12f),
    MEDIUM("中", 15f),
    LARGE("大", 18f),
}

/**
 * 公文格式审校工作台状态。
 *
 * 关键约定：**修改状态以服务端为准**。`appliedIds` / `resolvedIds` 全部来自后端返回的
 * `applied_ids` / `resolved_ids`（元素是 issue id，不是列表下标），
 * 不做本地乐观更新，也不再默认全选（旧版默认全选是错的）。
 *
 * 中栏编辑器：整篇文档是一个连续可编辑文本（`editorText`），段落间用单个换行连接，
 * 不再按段落分块渲染（旧实现空段落 + 段前段后距叠加，视觉上「全是换行」）。
 * 「修改前」只读，「当前版本」可编辑；手动编辑只影响本地预览（`editorDirty`），
 * 不会写回服务端，也不会进入导出稿 —— 导出仍以「应用修改」的自动修正为准。
 */
class FormatCheckViewModel(private val repo: FormatCheckRepository) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    // ---- 左栏：校验记录 ----
    var records by mutableStateOf(listOf<JsonObject>())
        private set
    var currentRecordId by mutableStateOf<String?>(null)
        private set

    // ---- 右栏：校验结果 ----
    var currentRecord by mutableStateOf<JsonObject?>(null)
        private set
    var issues by mutableStateOf(listOf<JsonObject>())
        private set
    /**
     * 已应用的修改（服务端返回的 applied_ids，元素为 **issue id** 而非列表下标）。
     * 语义：当前版本已按该条改过，但**还没经过重新校验确认**。
     */
    var appliedIds by mutableStateOf(setOf<Int>())
        private set
    /**
     * 已修正（服务端返回的 resolved_ids）。
     * 语义：重新校验后确认该问题已消失（已写进文档并复检通过），**不可撤销**。
     *
     * 注意 issues 是 append-only：老条目的 id 与下标永不变，recheck 只追加新问题，
     * 「已修正」靠本集合表达，而不是靠问题从列表里消失。
     */
    var resolvedIds by mutableStateOf(setOf<Int>())
        private set
    /** 未解决问题数，直接取后端派生的 open_issue_count，不本地推算 */
    var openIssueCount by mutableStateOf(0)
        private set
    var selectedIssueId by mutableStateOf<Int?>(null)
        private set

    // ---- 中栏：连续文本编辑器 ----
    var paragraphsOriginal by mutableStateOf(listOf<JsonObject>())
        private set
    var paragraphsCurrent by mutableStateOf(listOf<JsonObject>())
        private set
    var version by mutableStateOf(DocVersion.ORIGINAL)
        private set
    var zoom by mutableStateOf(DocZoom.MEDIUM)

    /** 中栏编辑器内容（整篇连续文本）。 */
    var editorText by mutableStateOf(TextFieldValue(""))
        private set
    /** 用户是否做过手动编辑（仅本地预览，不写回服务端、不进导出稿）。 */
    var editorDirty by mutableStateOf(false)
        private set

    /** 段落下标 → 编辑器字符区间（用于「定位第 N 段」时选中对应文本）。 */
    private var paraRanges: List<IntRange> = emptyList()

    // ---- 通用 ----
    var error by mutableStateOf<String?>(null)
    var status by mutableStateOf<String?>(null)
    /**
     * 中性提示（非错误、非成功）：用于「操作执行了但结果可能不符合预期」的场景，
     * 例如纯 AI 校验记录跳过规则复检。UI 上用中性色 NoticeBar，不走红色 error 条。
     */
    var notice by mutableStateOf<String?>(null)
    var busy by mutableStateOf(false)
        private set
    var useAi by mutableStateOf(true)

    // ---------------- 中栏编辑器 ----------------

    /** 把段落列表拼成连续文本并重建段落字符区间映射。 */
    private fun loadEditor(paragraphs: List<JsonObject>) {
        val sb = StringBuilder()
        val ranges = ArrayList<IntRange>(paragraphs.size)
        paragraphs.forEach { p ->
            val start = sb.length
            sb.append(p["text"].str())
            ranges.add(start until sb.length)
            sb.append('\n')
        }
        paraRanges = ranges
        editorText = TextFieldValue(sb.toString().trimEnd('\n'))
        editorDirty = false
    }

    /**
     * 切换版本：重载编辑器内容（放弃未保存的手动编辑，由 UI 提前确认）。
     * 命名不用 setVersion——属性 version 的自动生成 setter 与它 JVM 签名冲突。
     */
    fun switchVersion(v: DocVersion) {
        if (v == version) return
        version = v
        loadEditor(if (v == DocVersion.ORIGINAL) paragraphsOriginal else paragraphsCurrent)
    }

    /** 用户输入。手动编辑只影响本地预览，不参与导出。 */
    fun onEditorChange(v: TextFieldValue) {
        if (version == DocVersion.ORIGINAL) return // 修改前只读，双保险（UI 层也 readOnly）
        editorText = v
        editorDirty = true
    }

    /** 放弃手动编辑，恢复为服务端返回的当前版本文本。 */
    fun resetEditor() {
        loadEditor(if (version == DocVersion.ORIGINAL) paragraphsOriginal else paragraphsCurrent)
        status = "已恢复为服务端版本"
    }

    /**
     * 选中一条问题并尽量把编辑器光标/选区定位到对应段落。
     * 用户手动编辑过文本后，段落区间映射可能漂移，此时只选中不定位（不伪造位置）。
     */
    fun focusIssue(index: Int) {
        selectedIssueId = index
        if (editorDirty) return
        val issue = issues.getOrNull(index) ?: return
        val pi = (issue["paragraph_index"] as? JsonPrimitive)?.intOrNull ?: return
        val r = paraRanges.getOrNull(pi) ?: return
        if (r.last < editorText.text.length) {
            editorText = editorText.copy(selection = TextRange(r.first, r.last + 1))
        }
    }

    // ---------------- 左栏 ----------------

    fun loadRecords() {
        scope.launch {
            when (val r = repo.records()) {
                is ApiResult.Ok -> records = r.data
                is ApiResult.Err -> fail("读取校验记录失败", r.message)
            }
        }
    }

    /** 上传并校验（只收 .docx，筛选在 UI 层做） */
    fun check(file: File) {
        busy = true
        error = null
        status = "校验中，请稍候…"
        scope.launch {
            when (val r = repo.check(file, useAi)) {
                is ApiResult.Ok -> {
                    val o = r.data.obj()
                    if (o == null) {
                        fail("校验响应格式异常", "响应不是 JSON 对象")
                        status = null
                    } else {
                        status = "校验完成"
                        loadRecords()
                        openRecord(recordIdOf(o))
                    }
                }
                is ApiResult.Err -> {
                    fail("校验失败", r.message)
                    status = null
                }
            }
            busy = false
        }
    }

    fun deleteRecord(id: String) {
        scope.launch {
            busy = true
            when (val r = repo.deleteRecord(id)) {
                is ApiResult.Ok -> {
                    if (currentRecordId == id) clearCurrent()
                    loadRecords()
                }
                is ApiResult.Err -> fail("删除记录失败", r.message)
            }
            busy = false
        }
    }

    // ---------------- 打开记录 ----------------

    /** 打开记录：并发拉「记录详情 + 修改前段落 + 当前段落」三份数据 */
    fun openRecord(id: String) {
        if (id.isBlank()) {
            error = "未能定位校验记录（id 为空）"
            ClientLog.error("format-check openRecord: id 为空")
            return
        }
        error = null
        notice = null
        currentRecordId = id
        scope.launch {
            busy = true
            val recDeferred = async { repo.record(id) }
            val origDeferred = async { repo.paragraphs(id, DocVersion.ORIGINAL.query) }
            val curDeferred = async { repo.paragraphs(id, DocVersion.CURRENT.query) }

            when (val rec = recDeferred.await()) {
                is ApiResult.Ok -> {
                    currentRecord = rec.data
                    applyStateFrom(rec.data)
                    selectedIssueId = null
                }
                is ApiResult.Err -> fail("打开记录失败", rec.message)
            }
            when (val po = origDeferred.await()) {
                is ApiResult.Ok -> paragraphsOriginal = po.data
                is ApiResult.Err -> fail("读取「修改前」段落失败", po.message)
            }
            when (val pc = curDeferred.await()) {
                is ApiResult.Ok -> paragraphsCurrent = pc.data
                is ApiResult.Err -> fail("读取「当前版本」段落失败", pc.message)
            }
            // 段落就绪后加载编辑器（默认「修改前」视图）
            version = DocVersion.ORIGINAL
            loadEditor(paragraphsOriginal)
            busy = false
        }
    }

    // ---------------- 应用 / 撤销 / 重新校验 ----------------

    /** 单条 issue 的后端 id；后端尚未下发 id 时退化为列表下标（与契约 id=0..n-1 同义） */
    fun issueIdOf(index: Int): Int? {
        val issue = issues.getOrNull(index) ?: return null
        val raw = issue["id"]
        return (raw as? JsonPrimitive)?.intOrNull
            ?: raw.str().trim().toIntOrNull()
            ?: index
    }

    fun applyIssue(index: Int) {
        val id = currentRecordId
        if (id.isNullOrBlank()) { error = "请先打开一条校验记录"; return }
        val issueId = issueIdOf(index)
        if (issueId == null) { error = "问题下标越界：$index"; return }
        scope.launch {
            busy = true
            when (val r = repo.applyIssue(id, issueId)) {
                is ApiResult.Ok -> {
                    applyIdsFrom(r.data)
                    paragraphsCurrent = r.data["paragraphs"].arr().mapNotNull { it.obj() }
                    version = DocVersion.CURRENT
                    loadEditor(paragraphsCurrent)
                    status = null
                }
                is ApiResult.Err -> fail("应用修改失败", r.message)
            }
            busy = false
        }
    }

    fun undoIssue(index: Int) {
        val id = currentRecordId
        if (id.isNullOrBlank()) { error = "请先打开一条校验记录"; return }
        val issueId = issueIdOf(index)
        if (issueId == null) { error = "问题下标越界：$index"; return }
        scope.launch {
            busy = true
            when (val r = repo.undoIssue(id, issueId)) {
                is ApiResult.Ok -> {
                    applyIdsFrom(r.data)
                    paragraphsCurrent = r.data["paragraphs"].arr().mapNotNull { it.obj() }
                    version = DocVersion.CURRENT
                    loadEditor(paragraphsCurrent)
                    status = null
                }
                is ApiResult.Err -> fail("撤销修改失败", r.message)
            }
            busy = false
        }
    }

    fun recheck() {
        val id = currentRecordId
        if (id.isNullOrBlank()) { error = "请先打开一条校验记录"; return }
        error = null
        notice = null
        scope.launch {
            busy = true
            when (val r = repo.recheck(id)) {
                is ApiResult.Ok -> {
                    val o = r.data
                    currentRecord = o
                    applyStateFrom(o)
                    selectedIssueId = null
                    val po = repo.paragraphs(id, DocVersion.ORIGINAL.query)
                    val pc = repo.paragraphs(id, DocVersion.CURRENT.query)
                    if (po is ApiResult.Ok) paragraphsOriginal = po.data
                    else if (po is ApiResult.Err) fail("读取「修改前」段落失败", po.message)
                    if (pc is ApiResult.Ok) paragraphsCurrent = pc.data
                    else if (pc is ApiResult.Err) fail("读取「当前版本」段落失败", pc.message)
                    // 复检后段落已刷新，编辑器跟随当前选中版本重载
                    loadEditor(if (version == DocVersion.ORIGINAL) paragraphsOriginal else paragraphsCurrent)
                    // 纯 AI 校验记录（check_mode == ai_only，无规则）不支持规则复检：
                    // 后端会返回 skipped_reason=ai_only_record。这不是错误，给一条中性说明，
                    // 否则用户点「重新校验」会觉得什么都没发生。
                    val skipped = o["skipped_reason"].str()
                    notice = if (skipped == "ai_only_record") {
                        "该记录为纯 AI 校验模式，规则复检不适用，本次未产生复检结果。"
                    } else {
                        null
                    }
                    status = if (notice == null) "已重新校验" else null
                }
                is ApiResult.Err -> fail("重新校验失败", r.message)
            }
            busy = false
        }
    }

    // ---------------- 导出 ----------------

    fun export(target: File) {
        val id = currentRecordId
        if (id.isNullOrBlank()) {
            error = "请先打开一条校验记录再导出"
            ClientLog.error("format-check export: 记录 id 为空")
            return
        }
        val indices = appliedIds.sorted()
        scope.launch {
            busy = true
            status = when (val r = repo.fix(id, indices, target)) {
                is ApiResult.Ok -> r.data
                is ApiResult.Err -> {
                    fail("导出修正稿失败", r.message)
                    null
                }
            }
            busy = false
        }
    }

    /** 用户在保存对话框取消时给出可见反馈，避免「点了没反应」 */
    fun onSaveCancelled() {
        status = "已取消保存"
    }

    fun clearError() {
        error = null
    }

    // ---------------- 规则管理 ----------------

    var rules by mutableStateOf(listOf<JsonObject>())
        private set
    /** 正在编辑的规则表单；null 表示未打开 */
    var editingRule by mutableStateOf<RuleForm?>(null)

    fun loadRules() {
        scope.launch {
            when (val r = repo.rules()) {
                is ApiResult.Ok -> rules = r.data
                is ApiResult.Err -> fail("读取格式规则失败", r.message)
            }
        }
    }

    fun openRuleEditor(rule: JsonObject?) {
        editingRule = rule?.let {
            RuleForm(
                id = it["id"].str(),
                name = it["name"].str(),
                target = it["target"].str().ifBlank { "body" },
                severity = it["severity"].str().ifBlank { "error" },
                checksJson = it["checks"]?.toString() ?: "{}",
                remark = it["remark"].str(),
                isDefault = it["is_default"].bool(),
                isActive = it["is_active"].bool(true),
            )
        } ?: RuleForm()
    }

    fun saveRule() {
        val form = editingRule ?: return
        if (form.name.isBlank()) {
            status = "规则名称不能为空"
            return
        }
        val checks = try {
            kotlinx.serialization.json.Json.parseToJsonElement(form.checksJson).jsonObject
        } catch (e: Exception) {
            status = "校验项不是合法 JSON，请检查格式（例如 {\"font_size_pt\": 16}）"
            return
        }
        val body = mapOf<String, Any?>(
            "name" to form.name, "target" to form.target, "checks" to checks,
            "severity" to form.severity, "is_default" to form.isDefault,
            "is_active" to form.isActive, "remark" to form.remark,
        )
        busy = true
        scope.launch {
            val r = if (form.id.isBlank()) repo.createRule(body) else repo.updateRule(form.id, body)
            when (r) {
                is ApiResult.Ok -> {
                    status = "规则已保存"
                    editingRule = null
                    loadRules()
                }
                is ApiResult.Err -> fail("保存规则失败", ruleErrorOf(r))
            }
            busy = false
        }
    }

    fun deleteRule(id: String) {
        if (id.isBlank()) {
            error = "未能定位规则（id 为空），请刷新后重试"
            return
        }
        busy = true
        scope.launch {
            when (val r = repo.deleteRule(id)) {
                is ApiResult.Ok -> {
                    status = "规则已删除"
                    loadRules()
                }
                is ApiResult.Err -> fail("删除规则失败", ruleErrorOf(r))
            }
            busy = false
        }
    }

    // ---------------- 内部 ----------------

    private fun clearCurrent() {
        currentRecordId = null
        currentRecord = null
        issues = emptyList()
        notice = null
        appliedIds = emptySet()
        resolvedIds = emptySet()
        openIssueCount = 0
        paragraphsOriginal = emptyList()
        paragraphsCurrent = emptyList()
        selectedIssueId = null
        version = DocVersion.ORIGINAL
        editorText = TextFieldValue("")
        editorDirty = false
        paraRanges = emptyList()
    }

    /**
     * 用「记录详情」响应整体刷状态（issues / applied_ids / resolved_ids / open_issue_count）。
     * 字段名缺失时安全退化为空集合 / 0，不抛异常。
     */
    private fun applyStateFrom(o: JsonObject) {
        issues = o["issues"].arr().mapNotNull { it.obj() }
        appliedIds = intSetOf(o["applied_ids"])
        resolvedIds = intSetOf(o["resolved_ids"])
        openIssueCount = openCountOf(o["open_issue_count"], 0)
    }

    /**
     * 用 apply / undo 的响应刷状态。
     *
     * 后端约定：这两个接口**不回 issues**（append-only，只有 recheck 会新增条目），
     * 所以这里不动 issues —— 避免老问题被顺手清掉。
     * 它们会回 `open_issue_count`，因此「未解决 K 项」能即时更新，不用等重校验。
     * recheck 后服务端会把 applied_ids 重置为 []、resolved_ids 保留，
     * 所以这里一律**以服务端返回值为准覆盖**，不做本地增量推算。
     */
    private fun applyIdsFrom(o: JsonObject) {
        appliedIds = intSetOf(o["applied_ids"])
        resolvedIds = intSetOf(o["resolved_ids"])
        openIssueCount = openCountOf(o["open_issue_count"], openIssueCount)
    }

    /** 记录 id：check 响应用 record_id，历史列表项用 id，两个都要认 */
    private fun recordIdOf(rec: JsonObject?): String =
        (rec?.get("id") ?: rec?.get("record_id"))?.str()?.trim().orEmpty()

    /**
     * 解析未解决问题数：直接用后端派生的 open_issue_count，不本地推算。
     * 字段缺失或解析不出时**保持传入的兜底值**（apply/undo 传当前值，避免显示跳变）。
     */
    private fun openCountOf(el: JsonElement?, fallback: Int): Int =
        (el as? JsonPrimitive)?.intOrNull
            ?: el.str().trim().toIntOrNull()
            ?: fallback

    /**
     * 解析 id 集合：元素是 issue id。
     * 兼容后端把数字以字符串下发的情况（"3" 与 3 都认），解析不出就丢弃该元素。
     */
    private fun intSetOf(el: JsonElement?): Set<Int> =
        el.arr().mapNotNull {
            (it as? JsonPrimitive)?.intOrNull ?: it.str().trim().toIntOrNull()
        }.toSet()

    /** 规则管理错误文案：403 翻译成明确的权限提示，不把英文 detail 直接抛给用户 */
    private fun ruleErrorOf(r: ApiResult.Err): String = when {
        r.status == 403 -> "需要管理员及以上权限才能维护格式规则（当前账号无权限）"
        else -> r.message
    }

    /** 统一失败处理：UI 可见 + 落日志，绝不静默 */
    private fun fail(prefix: String, detail: String?) {
        val msg = if (detail.isNullOrBlank()) prefix else "$prefix：$detail"
        error = msg
        ClientLog.error("format-check $prefix${if (detail.isNullOrBlank()) "" else " | $detail"}")
    }

    // ---------------- 三态判定（已修正 / 已应用 / 未处理） ----------------

    /** 该条是否已修正（重新校验确认）；已修正不可撤销 */
    fun isResolved(index: Int): Boolean {
        val id = issueIdOf(index) ?: return false
        return resolvedIds.contains(id)
    }

    /** 该条是否已应用（已改但未复检） */
    fun isApplied(index: Int): Boolean {
        val id = issueIdOf(index) ?: return false
        return !resolvedIds.contains(id) && appliedIds.contains(id)
    }

    /** 兼容旧引用：已应用数量 */
    val appliedCount: Int get() = appliedIds.count { !resolvedIds.contains(it) }

    /** 已修正数量（用于顶部统计展示） */
    val resolvedCount: Int get() = resolvedIds.size
}

/** 规则编辑表单（checks 以 JSON 文本编辑，保存时校验合法性） */
data class RuleForm(
    val id: String = "",
    val name: String = "",
    val target: String = "body",
    val severity: String = "error",
    val checksJson: String = "{}",
    val remark: String = "",
    val isDefault: Boolean = false,
    val isActive: Boolean = true,
)
