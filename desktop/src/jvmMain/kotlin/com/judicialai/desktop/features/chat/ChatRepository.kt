package com.judicialai.desktop.features.chat

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.features.chat.model.ChatAttachment
import com.judicialai.desktop.features.chat.model.ChatMessage
import com.judicialai.desktop.features.chat.model.ChatSession
import java.io.File

/** /chat/send 完整结果（含智能写作流水线字段） */
data class SendOutcome(
    val reply: String,
    val sources: List<String>,
    val sessionId: String?,
    val documentId: String? = null,
    val documentNumber: String? = null,
    val documentDate: String? = null,
    val qualityLevel: String? = null,
    val qualityIssues: List<String> = emptyList(),
    val unverifiedCitations: List<String> = emptyList(),
)

/** 智能写作数据访问（端点与返回结构对应 backend/api/chat.py 与 Web api/knowledge.js） */
class ChatRepository(private val api: ApiClient) {

    /** GET /chat/sessions → 纯数组 [{id,title,created_at}] */
    /** Chat「加入训练集」：用户真实需求 + AI 初稿 + 人工最终稿 → 候选样本（不触发训练） */
    suspend fun addToTraining(sessionId: String, instruction: String, draft: String, output: String) =
        api.post(Endpoints.Training.SAMPLE_FROM_CHAT, buildMap<String, Any?> {
            put("session_id", sessionId)
            put("instruction", instruction)
            put("draft", draft)
            put("output", output)
        })

    suspend fun listSessions(): ApiResult<List<ChatSession>> = when (val r = api.get(Endpoints.Chat.SESSIONS)) {
        is ApiResult.Ok -> ApiResult.Ok(r.data.items().map {
            ChatSession(it["id"].str(), it["title"].str().ifBlank { "未命名会话" }, it["created_at"].str())
        })
        is ApiResult.Err -> r
    }

    /** GET /chat/sessions/{id}/messages → 纯数组 */
    suspend fun listMessages(sessionId: String): ApiResult<List<ChatMessage>> =
        when (val r = api.get(Endpoints.Chat.sessionMessages(sessionId))) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items().map { m ->
                ChatMessage(
                    role = m["role"].str().ifBlank { "assistant" },
                    content = m["content"].str(),
                    sources = m["sources"].arr().map { it.str() }.filter { it.isNotBlank() },
                    attachments = m["attachments"].arr().mapNotNull { a ->
                        a.obj()?.let {
                            ChatAttachment(it["id"].str(), it["filename"].str(),
                                it["kind"].str().ifBlank { "doc" },
                                it["parse_status"].str() == "failed")
                        }
                    },
                )
            })
            is ApiResult.Err -> r
        }

    /**
     * POST /chat/send {message, session_id, use_rag, attachment_ids, reference_template_id}
     * 响应 {reply, sources, attachments, session_id}
     */
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
        return when (val r = api.post(Endpoints.Chat.SEND, body, timeoutMs = 180_000)) {
            is ApiResult.Ok -> {
                val d = r.data.obj()
                val reply = d?.get("reply")?.str()?.ifBlank { null }
                    ?: d?.get("message")?.str()?.ifBlank { null }
                    ?: d?.get("content")?.str()?.ifBlank { null } ?: ""
                val sources = d?.get("sources")?.arr()?.map { it.str() }
                    ?.filter { it.isNotBlank() } ?: emptyList()
                val quality = d?.get("quality")?.obj()
                val issues = quality?.get("issues")?.arr()
                    ?.mapNotNull { it.obj()?.get("message")?.str() }
                    ?.filter { it.isNotBlank() } ?: emptyList()
                val unverified = d?.get("content_check")?.obj()?.get("unverified")?.arr()
                    ?.map { it.str() }?.filter { it.isNotBlank() } ?: emptyList()
                ApiResult.Ok(SendOutcome(
                    reply = reply,
                    sources = sources,
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

    /** POST /chat/attachments/upload → {"attachments": [...]} */
    suspend fun uploadAttachments(files: List<File>): ApiResult<List<ChatAttachment>> =
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

    /** DELETE /chat/sessions/{id} */
    suspend fun deleteSession(id: String) = api.del(Endpoints.Chat.session(id))

    suspend fun exportDocx(payload: Map<String, Any?>, redHeader: Boolean, target: File): ApiResult<String> {
        val path = if (redHeader) Endpoints.Chat.EXPORT_OFFICIAL else Endpoints.Chat.EXPORT_DOCX
        return api.downloadPost(path, payload, target)
    }
}

