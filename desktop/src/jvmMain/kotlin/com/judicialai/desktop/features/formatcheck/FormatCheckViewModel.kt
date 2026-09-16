package com.judicialai.desktop.features.formatcheck

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.bool
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import java.io.File

class FormatCheckViewModel(private val repo: FormatCheckRepository) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var records by mutableStateOf(listOf<JsonObject>())
        private set
    var current by mutableStateOf<JsonObject?>(null)
        private set
    var issues by mutableStateOf(listOf<JsonObject>())
        private set
    var accepted by mutableStateOf(setOf<Int>())
    var useAi by mutableStateOf(true)
    var status by mutableStateOf<String?>(null)
    var busy by mutableStateOf(false)
        private set

    fun loadRecords() {
        scope.launch {
            when (val r = repo.records()) {
                is ApiResult.Ok -> records = r.data
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun check(file: File) {
        busy = true
        status = "校验中，请稍候…"
        scope.launch {
            when (val r = repo.check(file, useAi)) {
                is ApiResult.Ok -> {
                    status = "校验完成"
                    loadRecords()
                    r.data.obj()?.let { openRecord(it) }
                }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    fun openRecord(rec: JsonObject) {
        current = rec
        issues = emptyList()
        scope.launch {
            when (val r = repo.paragraphs(rec["id"].str())) {
                is ApiResult.Ok -> {
                    issues = r.data.flatMap { p ->
                        val list = p["issues"].arr().mapNotNull { it.obj() }
                        if (list.isNotEmpty()) list else listOf(p)
                    }.filter { it["type"].str().isNotBlank() || it["message"].str().isNotBlank() }
                    accepted = issues.indices.toSet()
                }
                is ApiResult.Err -> status = r.message
            }
            if (issues.isEmpty()) {
                issues = rec["issues"].arr().mapNotNull { it.obj() }
                accepted = issues.indices.toSet()
            }
        }
    }

    fun fix(target: File) {
        val recId = current?.get("id")?.str() ?: return
        busy = true
        status = "生成修正稿…"
        scope.launch {
            status = when (val r = repo.fix(recId, accepted.toList(), target)) {
                is ApiResult.Ok -> r.data
                is ApiResult.Err -> r.message
            }
            busy = false
        }
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
                is ApiResult.Err -> status = r.message
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
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    fun deleteRule(id: String) {
        busy = true
        scope.launch {
            when (val r = repo.deleteRule(id)) {
                is ApiResult.Ok -> {
                    status = "规则已删除"
                    loadRules()
                }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }
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

