package com.judicialai.desktop.features.writing

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.features.chat.model.ChatAttachment
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date

/**
 * 智能写作工作台状态机。
 *
 * 步骤：1 填写需求 → 2 上传材料 → 3 检索依据 → 4 AI 起草 → 5 结果编辑 → 6 导出保存
 * 入口：零门槛一句话（entryInput），或左侧要素表单；两条路径最终都汇入同一份草稿状态。
 */
class WritingViewModel(private val repo: WritingRepository) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    // ---- 步骤 ----
    var step by mutableStateOf(1)
        private set

    // ---- 任务要素（左栏） ----
    var docType by mutableStateOf("通知")
    var title by mutableStateOf("")
    var recipient by mutableStateOf("")      // 发文对象 / 主送机关
    var authority by mutableStateOf("")      // 发文机关（落款）
    var urgency by mutableStateOf("普通")
    var secrecy by mutableStateOf("公开")
    var requirements by mutableStateOf("")   // 写作要求
    var attachments by mutableStateOf(listOf<ChatAttachment>())
        private set
    var useRag by mutableStateOf(true)
    var useSimilar by mutableStateOf(true)
    var useTemplate by mutableStateOf(true)

    // ---- 草稿（中栏） ----
    var content by mutableStateOf("")
    var docNumber by mutableStateOf("")
        private set
    var docDate by mutableStateOf("")
        private set
    var generatedAt by mutableStateOf("")
        private set

    // ---- 质量与依据（右栏） ----
    var qualityLevel by mutableStateOf<String?>(null)
        private set
    var qualityIssues by mutableStateOf(listOf<String>())
        private set
    var unverifiedCitations by mutableStateOf(listOf<String>())
        private set
    var references by mutableStateOf(listOf<String>())
        private set

    // ---- 文档/版本 ----
    var documentId by mutableStateOf<String?>(null)
        private set
    var versionNo by mutableStateOf(0)
        private set
    var sessionId by mutableStateOf<String?>(null)
        private set
    /** AI 初稿原文（用于加入训练数据时作为 draft） */
    var aiDraft by mutableStateOf("")
        private set

    // ---- 入口对话 ----
    var entryInput by mutableStateOf("")

    var status by mutableStateOf<String?>(null)
    var busy by mutableStateOf(false)
        private set

    val hasDraft: Boolean get() = content.isNotBlank()
    val hasMaterials: Boolean get() = attachments.isNotEmpty()

    /** 要素完整度（左栏清单用）：返回 (label, ok) 列表 */
    fun completeness(): List<Pair<String, Boolean>> = listOf(
        "文种" to docType.isNotBlank(),
        "标题" to title.isNotBlank(),
        "发文对象" to recipient.isNotBlank(),
        "发文机关" to authority.isNotBlank(),
        "写作要求" to requirements.isNotBlank(),
        "事实材料" to (attachments.isNotEmpty() || references.isNotEmpty()),
    )

    // ---------- 零门槛入口 ----------

    /** 一句话启动：系统解析意图 → 自动检索 → V1.2 起草 → 质检 → 自动存草稿 */
    fun startFromIntent() {
        val text = entryInput.trim()
        if (text.isBlank() || busy) return
        status = "正在理解您的写作意图并起草…"
        step = 4
        doSend(text) { }
    }

    // ---------- 材料 ----------

    fun uploadMaterials(files: List<File>) {
        if (files.isEmpty()) return
        busy = true
        status = "上传材料中…"
        scope.launch {
            when (val r = repo.uploadMaterials(files)) {
                is ApiResult.Ok -> {
                    attachments = attachments + r.data
                    status = "已上传 ${r.data.size} 份材料"
                    if (step < 2) step = 2
                }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    fun removeAttachment(a: ChatAttachment) {
        attachments = attachments - a
        scope.launch { repo.deleteAttachment(a.id) }
    }

    // ---------- 起草 ----------

    /** 按要素表单起草（无材料时合法：由调用方选择路径后进入） */
    fun draft(outlineOnly: Boolean = false) {
        if (busy) return
        if (title.isBlank() && requirements.isBlank()) {
            status = "请先填写标题或写作要求"
            return
        }
        val sb = StringBuilder()
        if (outlineOnly) {
            sb.append("请为以下公文只生成提纲框架（不要正文）：")
        } else {
            sb.append("请起草一份").append(docType)
        }
        if (title.isNotBlank()) sb.append("，标题：").append(title)
        if (requirements.isNotBlank()) sb.append("。写作要求：").append(requirements)
        if (recipient.isNotBlank()) sb.append("。主送机关：").append(recipient)
        if (authority.isNotBlank()) sb.append("。落款单位：").append(authority)
        if (outlineOnly) sb.append("。")
        status = if (outlineOnly) "正在生成提纲框架…" else "V1.2 正在起草…"
        step = if (outlineOnly) 3 else 4
        doSend(sb.toString()) { }
    }

    /** AI 助手操作：智能修改 / 扩写润色 / 精简篇幅 / 补充政策依据 等 */
    fun aiAssist(instruction: String) {
        if (busy || !hasDraft) return
        val msg = buildString {
            append("以下是当前公文草稿：\n")
            append(content.take(6000))
            append("\n\n请").append(instruction)
            append("，直接输出修改后的完整公文，不要解释。")
        }
        status = "AI 处理中：$instruction"
        doSend(msg) { }
    }

    /** 从资料库找依据（无材料路径之一）：仅检索不生成全文 */
    fun retrieveReferences() {
        if (busy) return
        val topic = title.ifBlank { requirements.ifBlank { entryInput } }
        if (topic.isBlank()) {
            status = "请先告诉我写作主题"
            return
        }
        status = "正在从资料库检索写作依据…"
        step = 3
        doSend("请围绕主题「$topic」列出可引用的政策依据和事实材料要点，不需要写正文。") { }
    }

    private fun doSend(message: String, after: () -> Unit) {
        busy = true
        scope.launch {
            when (val r = repo.send(
                message, sessionId, useRag,
                attachments.map { it.id }, null,
            )) {
                is ApiResult.Ok -> {
                    val d = r.data
                    sessionId = d.sessionId ?: sessionId
                    references = d.sources.ifEmpty { references }
                    if (d.reply.isNotBlank()) {
                        content = d.reply
                        if (aiDraft.isBlank()) aiDraft = d.reply
                        // 标题：正文首个非空行（公文标题居中行）
                        if (title.isBlank()) {
                            title = d.reply.lineSequence()
                                .firstOrNull { it.isNotBlank() }?.trim()
                                ?.take(60).orEmpty()
                        }
                        generatedAt = SimpleDateFormat("yyyy-MM-dd HH:mm").format(Date())
                    }
                    d.documentId?.let { documentId = it }
                    d.documentNumber?.let { docNumber = it }
                    d.documentDate?.let { docDate = it }
                    qualityLevel = d.qualityLevel
                    qualityIssues = d.qualityIssues
                    unverifiedCitations = d.unverifiedCitations
                    if (versionNo == 0 && d.documentId != null) versionNo = 1
                    status = when (d.qualityLevel) {
                        "A" -> "起草完成，质检优秀"
                        "B" -> "起草完成，质检通过（有 ${d.qualityIssues.size} 项提示）"
                        "D" -> "起草未通过质检，请修改要求后重新生成"
                        else -> "起草完成"
                    }
                    if (hasDraft) step = 5
                }
                is ApiResult.Err -> {
                    status = r.message
                    if (step > 2) step = 2
                }
            }
            busy = false
            after()
        }
    }

    /** 重新生成 */
    fun regenerate() {
        if (entryInput.isNotBlank() && title.isBlank()) startFromIntent() else draft()
    }

    // ---------- 版本 / 导出 / 训练 ----------

    fun saveVersion(note: String? = null) {
        if (busy || !hasDraft) return
        busy = true
        scope.launch {
            when (val r = repo.saveVersion(documentId, title, content, docType, note)) {
                is ApiResult.Ok -> {
                    documentId = r.data.first
                    versionNo = r.data.second
                    status = "已保存版本 v${r.data.second}"
                    if (step < 6) step = 6
                }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    fun export(redHeader: Boolean, target: File) {
        if (busy || !hasDraft) return
        busy = true
        status = "导出 Word 中…"
        scope.launch {
            when (val r = repo.export(redHeader, title, content, docNumber, docDate,
                recipient, authority, target)) {
                is ApiResult.Ok -> {
                    status = "已导出：${target.name}"
                    if (step < 6) step = 6
                }
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    fun addToTraining() {
        val sid = sessionId
        if (sid == null) { status = "请先完成一次 AI 起草"; return }
        if (!hasDraft) return
        busy = true
        scope.launch {
            val instruction = buildString {
                append("起草").append(docType)
                if (title.isNotBlank()) append("：").append(title)
                if (requirements.isNotBlank()) append("（").append(requirements).append("）")
            }
            when (val r = repo.addToTraining(sid, instruction, aiDraft.ifBlank { content }, content)) {
                is ApiResult.Ok -> status = "已加入训练候选样本（AI 初稿 + 当前稿）"
                is ApiResult.Err -> status = r.message
            }
            busy = false
        }
    }

    /** 全部重置，回到零门槛入口 */
    fun newTask() {
        step = 1
        title = ""; recipient = ""; requirements = ""
        attachments = emptyList()
        content = ""; docNumber = ""; docDate = ""; generatedAt = ""
        qualityLevel = null; qualityIssues = emptyList()
        unverifiedCitations = emptyList(); references = emptyList()
        documentId = null; versionNo = 0; sessionId = null; aiDraft = ""
        entryInput = ""
        status = null
    }
}
