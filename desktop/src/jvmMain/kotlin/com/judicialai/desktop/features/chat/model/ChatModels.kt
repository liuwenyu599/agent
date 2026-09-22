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

/**
 * 历史记录分类（只展示当前登录用户自己生成的内容）。
 *
 * 分类依据（后端现状，前端不臆造类型）：
 * 后端**没有**统一的历史接口，也没有跨类型的 type/kind 字段
 * （`chat_sessions` 仅 id/title/created_at，`GET /chat/sessions` 由后端按
 * `list_by_user(user.id)` 强制过滤）。三类分别来自三个**已按当前用户过滤**的既有端点：
 * - [CHAT] → `GET /chat/sessions`（后端 list_by_user(user.id)）
 * - [DOC]  → `GET /documents`（后端 `MyDocumentModel.user_id == user_id` 过滤）
 * - [PPT]  → `GET /ppt/documents`（后端 documents.list_by_user(user.id)）
 */
enum class HistoryCategory(val label: String) {
    CHAT("对话"),
    DOC("文档"),
    PPT("PPT"),
}

/** 历史记录条目：id + 标题 + 分类 + 时间 + 一行补充信息（状态 / 页数等） */
data class HistoryItem(
    val id: String,
    val title: String,
    val category: HistoryCategory,
    val time: String = "",
    val sub: String = "",
)

