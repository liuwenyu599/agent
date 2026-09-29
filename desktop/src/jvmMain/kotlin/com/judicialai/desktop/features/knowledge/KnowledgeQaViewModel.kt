package com.judicialai.desktop.features.knowledge

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.features.chat.ChatRepository
import com.judicialai.desktop.features.chat.model.ChatAttachment
import com.judicialai.desktop.features.chat.model.ChatMessage
import com.judicialai.desktop.features.chat.model.ChatSession
import com.judicialai.desktop.features.chat.model.KnowledgeCitation
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import java.io.File

class KnowledgeQaViewModel(
    private val knowledge: KnowledgeRepository,
    private val chat: ChatRepository,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var sessions by mutableStateOf(listOf<ChatSession>())
        private set
    var currentSessionId by mutableStateOf<String?>(null)
        private set
    var messages by mutableStateOf(listOf<ChatMessage>())
        private set
    var attachments by mutableStateOf(listOf<ChatAttachment>())
        private set
    var sending by mutableStateOf(false)
        private set
    var uploading by mutableStateOf(false)
        private set
    var status by mutableStateOf<String?>(null)
        private set

    var openedCitation by mutableStateOf<KnowledgeCitation?>(null)
        private set
    var openedDocument by mutableStateOf<JsonObject?>(null)
        private set
    var documentLoading by mutableStateOf(false)
        private set

    fun loadSessions() {
        scope.launch {
            when (val r = knowledge.listQaSessions()) {
                is ApiResult.Ok -> sessions = r.data
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun newSession() {
        currentSessionId = null
        messages = emptyList()
        attachments = emptyList()
        status = null
    }

    fun openSession(id: String) {
        currentSessionId = id
        status = null
        scope.launch {
            when (val r = chat.listMessages(id)) {
                is ApiResult.Ok -> messages = r.data
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun send(text: String) {
        val q = text.trim()
        if (q.isBlank() || sending) return
        val uploaded = attachments
        messages = messages + ChatMessage(role = "user", content = q, attachments = uploaded)
        sending = true
        status = null
        scope.launch {
            when (val r = knowledge.ask(q, currentSessionId, uploaded.map { it.id })) {
                is ApiResult.Ok -> {
                    messages = messages + ChatMessage(
                        role = "assistant",
                        content = r.data.reply,
                        sources = r.data.citations.map { it.source },
                        citations = r.data.citations,
                    )
                    currentSessionId = r.data.sessionId ?: currentSessionId
                    attachments = emptyList()
                    loadSessions()
                }
                is ApiResult.Err -> status = r.message
            }
            sending = false
        }
    }

    fun upload(files: List<File>) {
        val accepted = files.filter(::supported)
        if (accepted.isEmpty()) {
            status = "仅支持 png/jpg、doc/docx、pdf、xlsx"
            return
        }
        uploading = true
        status = "正在上传附件…"
        scope.launch {
            when (val r = chat.uploadAttachments(accepted)) {
                is ApiResult.Ok -> {
                    attachments = (attachments + r.data).distinctBy { it.id }
                    status = r.data.firstOrNull { it.failed }?.let { "部分附件解析失败，请移除后重试" }
                }
                is ApiResult.Err -> status = r.message
            }
            uploading = false
        }
    }

    fun removeAttachment(item: ChatAttachment) {
        attachments = attachments.filterNot { it.id == item.id }
        scope.launch { chat.deleteAttachment(item.id) }
    }

    fun openCitation(citation: KnowledgeCitation) {
        if (citation.docId.isBlank()) return
        openedCitation = citation
        openedDocument = null
        documentLoading = true
        scope.launch {
            when (val r = knowledge.getDocument(citation.docId)) {
                is ApiResult.Ok -> openedDocument = r.data
                is ApiResult.Err -> status = r.message
            }
            documentLoading = false
        }
    }

    fun closeCitation() {
        openedCitation = null
        openedDocument = null
        documentLoading = false
    }

    companion object {
        private val allowed = setOf("png", "jpg", "jpeg", "doc", "docx", "pdf", "xlsx")
        fun supported(file: File): Boolean =
            file.isFile && file.extension.lowercase() in allowed
    }
}
