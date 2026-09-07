package com.judicialai.desktop.features.chat.model

data class ChatMessage(
    val role: String,
    val content: String,
    val sources: List<String> = emptyList(),
    val attachments: List<ChatAttachment> = emptyList(),
    /** 智能写作流水线结果（仅写作类回复非空） */
    val documentId: String? = null,
    val qualityLevel: String? = null,
    val qualityIssues: List<String> = emptyList(),
    val unverifiedCitations: List<String> = emptyList(),
)

data class ChatSession(val id: String, val title: String, val createdAt: String = "")

data class ChatAttachment(val id: String, val name: String, val kind: String = "doc", val failed: Boolean = false)

