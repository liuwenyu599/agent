package com.judicialai.desktop.features.writing

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.features.chat.SendOutcome
import com.judicialai.desktop.features.chat.model.ChatAttachment
import java.io.File

/**
 * 智能写作工作台数据访问。
 * 起草/修改走 /chat/send（后端写作流水线：RAG + 后处理 + 质检 + 内容核查 + 自动草稿），
 * 版本管理走 /documents，导出走 /chat/export 或 /documents/{id}/export/docx。
 */
class WritingRepository(private val api: ApiClient) {

    /** 发起写作请求（起草 / AI 修改 / 提纲），返回流水线完整结果 */
    suspend fun send(
        message: String, sessionId: String?, useRag: Boolean,
        attachmentIds: List<String>, referenceTemplateId: String?,
    ): ApiResult<SendOutcome> {
        val body = buildMap<String, Any?> {
            put("message", message)
            put("session_id", sessionId)
            put("use_rag", useRag)
            if (attachmentIds.isNotEmpty()) put("attachment_ids", attachmentIds)
            if (!referenceTemplateId.isNullOrBlank()) put("reference_template_id", referenceTemplateId)
        }
        return when (val r = api.post(Endpoints.Chat.SEND, body, timeoutMs = 300_000)) {
            is ApiResult.Ok -> {
                val d = r.data.obj()
                val quality = d?.get("quality")?.obj()
                val issues = quality?.get("issues")?.arr()
                    ?.mapNotNull { it.obj()?.get("message")?.str() }
                    ?.filter { it.isNotBlank() } ?: emptyList()
                val unverified = d?.get("content_check")?.obj()?.get("unverified")?.arr()
                    ?.map { it.str() }?.filter { it.isNotBlank() } ?: emptyList()
                val refs = d?.get("sources")?.arr()?.map { it.str() }
                    ?.filter { it.isNotBlank() } ?: emptyList()
                ApiResult.Ok(SendOutcome(
                    reply = d?.get("reply")?.str().orEmpty(),
                    sources = refs,
                    sessionId = d?.get("session_id")?.str()?.ifBlank { null },
                    documentId = d?.get("document_id")?.str()?.ifBlank { null },
                    documentNumber = d?.get("document_number")?.str()?.ifBlank { null },
                    documentDate = d?.get("document_date")?.str()?.ifBlank { null },
                    qualityLevel = quality?.get("level")?.str()?.ifBlank { null },
                    qualityIssues = issues,
                    unverifiedCitations = unverified,
                ))
            }
            is ApiResult.Err -> r
        }
    }

    suspend fun uploadMaterials(files: List<File>): ApiResult<List<ChatAttachment>> =
        when (val r = api.upload(Endpoints.Chat.ATTACHMENTS_UPLOAD, "files", files)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items().map {
                ChatAttachment(it["id"].str(),
                    it["filename"].str().ifBlank { it["name"].str() },
                    it["kind"].str().ifBlank { "doc" },
                    it["parse_status"].str() == "failed")
            })
            is ApiResult.Err -> r
        }

    suspend fun deleteAttachment(id: String) = api.del(Endpoints.Chat.attachmentDelete(id))

    /** 保存当前编辑内容为新版本（无文档则先创建） */
    suspend fun saveVersion(
        documentId: String?, title: String, content: String,
        docType: String?, note: String?,
    ): ApiResult<Pair<String, Int>> {
        if (documentId == null) {
            val r = api.post(Endpoints.Documents.LIST, buildMap<String, Any?> {
                put("title", title.ifBlank { "未命名文档" })
                put("content", content)
                if (!docType.isNullOrBlank()) put("doc_type", docType)
                put("note", note ?: "工作台创建")
            })
            return when (r) {
                is ApiResult.Ok -> {
                    val d = r.data.obj()
                    ApiResult.Ok((d?.get("id").str()) to (d?.get("current_version").int()))
                }
                is ApiResult.Err -> r
            }
        }
        val r = api.put(Endpoints.Documents.item(documentId), buildMap<String, Any?> {
            put("content", content)
            put("title", title.ifBlank { "未命名文档" })
            if (!note.isNullOrBlank()) put("note", note)
        })
        return when (r) {
            is ApiResult.Ok -> {
                val d = r.data.obj()
                ApiResult.Ok((d?.get("id").str()) to (d?.get("current_version").int()))
            }
            is ApiResult.Err -> r
        }
    }

    /** 导出：redHeader=true 走红头公文格式，否则通用 Word */
    suspend fun export(
        redHeader: Boolean, title: String, content: String,
        docNumber: String, docDate: String, recipient: String, signature: String,
        target: File,
    ): ApiResult<String> {
        val payload = mapOf(
            "title" to title, "content" to content, "doc_number" to docNumber,
            "date_text" to docDate, "recipient" to recipient, "signature" to signature,
        )
        val path = if (redHeader) Endpoints.Chat.EXPORT_OFFICIAL else Endpoints.Chat.EXPORT_DOCX
        return api.downloadPost(path, payload, target)
    }

    /** 加入训练数据（AI 初稿 + 人工最终稿 → 候选样本） */
    suspend fun addToTraining(sessionId: String, instruction: String, draft: String, output: String) =
        api.post(Endpoints.Training.SAMPLE_FROM_CHAT, mapOf(
            "session_id" to sessionId,
            "instruction" to instruction,
            "draft" to draft,
            "output" to output,
        ))
}
