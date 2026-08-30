package com.judicialai.desktop.features.chat.model

data class ChatMessage(
    val role: String,
    val content: String,
    val sources: List<String> = emptyList(),
    val attachments: List<ChatAttachment> = emptyList(),
)

data class ChatSession(val id: String, val title: String, val createdAt: String = "")

data class ChatAttachment(val id: String, val name: String, val kind: String = "doc", val failed: Boolean = false)

