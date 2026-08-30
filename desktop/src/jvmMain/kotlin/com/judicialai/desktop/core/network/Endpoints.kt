package com.judicialai.desktop.core.network

/**
 * 后端 API 端点清单（全部来自 Web 端真实调用与后端 api 目录源码，不臆造）。
 */
object Endpoints {

    object Auth {
        const val LOGIN = "/auth/login"
        const val REGISTER = "/auth/register"
        const val REGISTER_FIRST = "/auth/register-first"
        const val CHECK_FIRST_USER = "/auth/check-first-user"
        const val ME = "/auth/me"
    }

    object Users {
        const val LIST = "/users/"
        const val CREATE = "/users/"
        fun item(id: String) = "/users/$id"
        fun resetPassword(id: String) = "/users/$id/reset-password"
    }

    object Chat {
        const val SEND = "/chat/send"
        const val SESSIONS = "/chat/sessions"
        fun session(id: String) = "/chat/sessions/$id"
        fun sessionMessages(id: String) = "/chat/sessions/$id/messages"
        const val ATTACHMENTS_UPLOAD = "/chat/attachments/upload"
        fun attachmentDelete(id: String) = "/chat/attachments/$id"
        const val EXPORT_DOCX = "/chat/export/docx"
        const val EXPORT_OFFICIAL = "/chat/export/official"
        // 管理后台
        const val ADMIN_SESSIONS = "/chat/admin/sessions"
        fun adminSessionDelete(id: String) = "/chat/admin/sessions/$id"
    }

    object Knowledge {
        const val LIST = "/knowledge/list"
        const val CREATE = "/knowledge/create"
        const val STATS = "/knowledge/stats"
        const val DOCUMENTS = "/knowledge/documents"
        const val PENDING = "/knowledge/pending"
        const val REVIEW = "/knowledge/review"
        fun kb(id: String) = "/knowledge/$id"
        fun documents(kbId: String) = "/knowledge/$kbId/documents"
        const val UPLOAD = "/knowledge/upload"
        const val BATCH_UPLOAD = "/knowledge/batch-upload"
        fun document(docId: String) = "/knowledge/documents/$docId"
        fun documentArchive(docId: String) = "/knowledge/documents/$docId/archive"
    }

    object Templates {
        const val LIST = "/templates/"
        const val CREATE = "/templates/"
        const val CATEGORIES = "/templates/categories"
        const val INIT = "/templates/init"
        fun item(id: String) = "/templates/$id"
        fun use(id: String) = "/templates/$id/use"
    }

    object FormatCheck {
        const val CHECK = "/format-check/check"
        const val RECORDS = "/format-check/records"
        fun record(id: String) = "/format-check/records/$id"
        fun paragraphs(recordId: String) = "/format-check/records/$recordId/paragraphs"
        const val PREVIEW_FIX = "/format-check/preview-fix"
        const val FIX = "/format-check/fix"
        const val RULES = "/format-check/rules"
        fun rule(id: String) = "/format-check/rules/$id"
    }

    object Ppt {
        const val TEMPLATES = "/ppt/templates"
        const val TEMPLATE_UPLOAD = "/ppt/templates/upload"
        fun templateDelete(id: String) = "/ppt/templates/$id"
        const val OUTLINE = "/ppt/outline"
        const val GENERATE = "/ppt/generate"
        const val DOCUMENTS = "/ppt/documents"
        fun document(id: String) = "/ppt/documents/$id"
        fun documentDraft(id: String) = "/ppt/documents/$id/draft"
        fun documentExport(id: String) = "/ppt/documents/$id/export"
        fun documentDownload(id: String) = "/ppt/documents/$id/download"
        fun documentDelete(id: String) = "/ppt/documents/$id"
    }

    object Workflow {
        const val TEMPLATES = "/workflow/templates"
        const val INSTANCES = "/workflow/instances"
        fun instance(id: String) = "/workflow/instances/$id"
        fun nodeGenerate(nodeInstId: String) = "/workflow/nodes/$nodeInstId/generate"
        fun nodeUpdate(nodeInstId: String) = "/workflow/nodes/$nodeInstId"
    }
}

