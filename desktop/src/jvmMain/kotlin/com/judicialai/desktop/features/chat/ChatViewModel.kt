package com.judicialai.desktop.features.chat

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.features.chat.model.ChatAttachment
import com.judicialai.desktop.features.chat.model.ChatMessage
import com.judicialai.desktop.features.chat.model.ChatSession
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.io.File

class ChatViewModel(private val repo: ChatRepository) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var sessions by mutableStateOf(listOf<ChatSession>())
        private set
    var currentSessionId by mutableStateOf<String?>(null)
        private set
    var messages by mutableStateOf(listOf<ChatMessage>())
        private set
    var attachments by mutableStateOf(listOf<ChatAttachment>())
        private set
    var popularTemplates by mutableStateOf(listOf<Pair<String, String>>())
        private set
    var referenceTemplate by mutableStateOf<Pair<String, String>?>(null)
        private set
    var useRag by mutableStateOf(true)
    var sending by mutableStateOf(false)
        private set
    var status by mutableStateOf<String?>(null)

    fun loadSessions() {
        scope.launch {
            when (val r = repo.listSessions()) {
                is ApiResult.Ok -> sessions = r.data
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun loadPopularTemplates(templates: List<Pair<String, String>>) {
        popularTemplates = templates
    }

    fun selectReferenceTemplate(t: Pair<String, String>) {
        referenceTemplate = t
    }

    fun clearReferenceTemplate() {
        referenceTemplate = null
    }

    fun newSession() {
        currentSessionId = null
        messages = emptyList()
        attachments = emptyList()
        referenceTemplate = null
    }

    fun openSession(id: String) {
        currentSessionId = id
        scope.launch {
            when (val r = repo.listMessages(id)) {
                is ApiResult.Ok -> messages = r.data
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun deleteSession(s: ChatSession) {
        scope.launch {
            repo.deleteSession(s.id)
            if (currentSessionId == s.id) newSession()
            loadSessions()
        }
    }

    fun send(text: String) {
        if (text.isBlank() || sending) return
        messages = messages + ChatMessage("user", text, attachments = attachments)
        sending = true
        status = null
        scope.launch {
            when (val r = repo.send(text, currentSessionId, useRag,
                attachments.map { it.id }, referenceTemplate?.first)) {
                is ApiResult.Ok -> {
                    messages = messages + ChatMessage("assistant", r.data.first, sources = r.data.second)
                    if (currentSessionId == null && r.data.third != null) {
                        currentSessionId = r.data.third
                        loadSessions()
                    }
                    attachments = emptyList()
                }
                is ApiResult.Err -> status = r.message
            }
            sending = false
        }
    }

    fun upload(files: List<File>) {
        if (files.isEmpty()) return
        status = "上传附件中…"
        scope.launch {
            when (val r = repo.uploadAttachments(files)) {
                is ApiResult.Ok -> {
                    attachments = attachments + r.data
                    status = null
                }
                is ApiResult.Err -> status = r.message
            }
        }
    }

    fun removeAttachment(a: ChatAttachment) {
        scope.launch {
            repo.deleteAttachment(a.id)
            attachments = attachments.filter { it.id != a.id }
        }
    }

    fun export(payload: Map<String, Any?>, redHeader: Boolean, target: File) {
        scope.launch {
            status = when (val r = repo.exportDocx(payload, redHeader, target)) {
                is ApiResult.Ok -> r.data
                is ApiResult.Err -> r.message
            }
        }
    }

    fun lastAssistantMessage(): String =
        messages.lastOrNull { it.role == "assistant" }?.content ?: ""
}

