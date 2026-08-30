package com.judicialai.desktop.data

import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.features.admin.AdminRepository
import com.judicialai.desktop.features.chat.ChatRepository
import com.judicialai.desktop.features.formatcheck.FormatCheckRepository
import com.judicialai.desktop.features.knowledge.KnowledgeRepository
import com.judicialai.desktop.features.ppt.PptRepository
import com.judicialai.desktop.features.templates.TemplatesRepository
import com.judicialai.desktop.features.workflow.WorkflowRepository

/**
 * 数据层入口：统一管理各业务 Repository 的单例。
 * Repository 具体实现归各 feature 所有，这里只做装配。
 */
object Repositories {
    val chat: ChatRepository by lazy { ChatRepository(AppState.api) }
    val knowledge: KnowledgeRepository by lazy { KnowledgeRepository(AppState.api) }
    val templates: TemplatesRepository by lazy { TemplatesRepository(AppState.api) }
    val formatCheck: FormatCheckRepository by lazy { FormatCheckRepository(AppState.api) }
    val ppt: PptRepository by lazy { PptRepository(AppState.api) }
    val workflow: WorkflowRepository by lazy { WorkflowRepository(AppState.api) }
    val admin: AdminRepository by lazy { AdminRepository(AppState.api) }
}

