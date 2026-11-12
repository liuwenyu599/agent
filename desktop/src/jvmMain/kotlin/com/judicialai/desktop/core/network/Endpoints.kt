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
        /** 当前登录用户修改自己的密码（旧密码 + 新密码二次确认） */
        const val CHANGE_PASSWORD = "/auth/change-password"
    }

    object Users {
        const val LIST = "/users/"
        const val CREATE = "/users/"
        fun item(id: String) = "/users/$id"
        fun resetPassword(id: String) = "/users/$id/reset-password"
        /** 批量导入用户（.xlsx / .csv，multipart 字段名 file） */
        const val BATCH_IMPORT = "/users/batch-import"
    }

    object Chat {
        const val SEND = "/chat/send"
        const val SEND_STREAM = "/chat/send/stream"
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
        /** 科室空间知识问答：服务端固定检索公共 + 本科室 + 本人知识库 */
        const val ASK = "/knowledge/ask"
        const val ASK_SESSIONS = "/knowledge/ask/sessions"
        fun document(docId: String) = "/knowledge/documents/$docId"
        fun documentArchive(docId: String) = "/knowledge/documents/$docId/archive"
        fun documentUnarchive(docId: String) = "/knowledge/documents/$docId/unarchive"
    }

    object WritingTasks {
        const val LIST = "/writing/tasks"
        /** 一句话任务 → AI 规划出本次写作工作台配置（WorkspaceSpec） */
        const val PLAN = "/writing/tasks/plan"
        fun item(id: String) = "/writing/tasks/$id"
        fun chat(id: String) = "/writing/tasks/$id/chat"
        fun chatStream(id: String) = "/writing/tasks/$id/chat/stream"
        fun draft(id: String) = "/writing/tasks/$id/draft"
        /** 流式起草（SSE）：正文边生成边推，最后推 done 携带权威结果 */
        fun draftStream(id: String) = "/writing/tasks/$id/draft/stream"
        fun renderProfile(id: String) = "/writing/tasks/$id/render-profile"
        fun agentRun(id: String, runId: String) = "/writing/tasks/$id/agent-runs/$runId"
        fun agentRunResume(id: String, runId: String) =
            "/writing/tasks/$id/agent-runs/$runId/resume"
        fun agentRunCancel(id: String, runId: String) =
            "/writing/tasks/$id/agent-runs/$runId/cancel"
        fun revise(id: String) = "/writing/tasks/$id/revise"
        fun paragraphs(id: String) = "/writing/tasks/$id/paragraphs"
        fun paragraphSuggest(id: String, paragraphId: String) =
            "/writing/tasks/$id/paragraphs/$paragraphId/suggest"
        fun suggestionAccept(id: String, suggestionId: String) =
            "/writing/tasks/$id/suggestions/$suggestionId/accept"
        fun suggestionReject(id: String, suggestionId: String) =
            "/writing/tasks/$id/suggestions/$suggestionId/reject"
        /** 上传图片并由视觉模型（Qwen2.5-VL 等）识别为文本，绑定到任务会话 */
        fun images(id: String) = "/writing/tasks/$id/images"
        fun materials(id: String) = "/writing/tasks/$id/materials"
        fun versions(id: String) = "/writing/tasks/$id/versions"
        fun formatCheck(id: String) = "/writing/tasks/$id/format-check"
        fun contentCheck(id: String) = "/writing/tasks/$id/content-check"
        fun version(id: String, no: Int) = "/writing/tasks/$id/versions/$no"
        /** 回退到指定历史版本（回退前当前内容自动保存为新版本） */
        fun versionRestore(id: String, no: Int) = "/writing/tasks/$id/versions/$no/restore"
        fun versionExport(id: String, no: Int, redHeader: Boolean) =
            "/writing/tasks/$id/versions/$no/export?red_header=$redHeader"
        fun export(id: String, redHeader: Boolean) = "/writing/tasks/$id/export?red_header=$redHeader"
        fun trainingSample(id: String) = "/writing/tasks/$id/training-sample"
    }

    object Documents {
        const val LIST = "/documents"
        fun item(id: String) = "/documents/$id"
        fun version(id: String, no: Int) = "/documents/$id/versions/$no"
        fun exportDocx(id: String) = "/documents/$id/export/docx"
    }

    object Templates {
        const val LIST = "/templates/"
        const val CREATE = "/templates/"
        const val CATEGORIES = "/templates/categories"
        const val INIT = "/templates/init"
        fun item(id: String) = "/templates/$id"
        fun use(id: String) = "/templates/$id/use"
        /** 系统模板 → 本科室模板草案（AI 按本科室写作习惯调整，不落库） */
        fun adapt(id: String) = "/templates/$id/adapt"
        /** 人工确认后保存为本科室模板 */
        const val DEPARTMENT_SAVE = "/templates/department"
    }

    object FormatCheck {
        const val CHECK = "/format-check/check"
        const val RECORDS = "/format-check/records"
        fun record(id: String) = "/format-check/records/$id"
        /** version=original|current，分别取源文档与已应用修改后的段落 */
        fun paragraphs(recordId: String, version: String = "original") =
            "/format-check/records/$recordId/paragraphs?version=$version"
        /** 保存中栏人工正文修改（写回服务端成为新基线，应用/解决状态重置） */
        fun updateContent(recordId: String) = "/format-check/records/$recordId/content"
        /** 应用单条修改；响应回传 applied_ids / resolved_ids 与最新 current 段落 */
        fun apply(recordId: String) = "/format-check/records/$recordId/apply"
        /** 撤销单条修改；响应同上 */
        fun undo(recordId: String) = "/format-check/records/$recordId/undo"
        /** 重新校验：返回与 check 相同的结构（含 id） */
        fun recheck(recordId: String) = "/format-check/records/$recordId/recheck"
        const val PREVIEW_FIX = "/format-check/preview-fix"
        const val FIX = "/format-check/fix"
        const val RULES = "/format-check/rules"
        /** 白话描述 → AI 生成校验项（不落库，预览确认后再保存） */
        const val RULES_COMPILE = "/format-check/rules/compile"
        fun rule(id: String) = "/format-check/rules/$id"
        fun ruleActive(id: String) = "/format-check/rules/$id/active"
    }

    object Ppt {
        const val TEMPLATES = "/ppt/templates"
        /** 可选知识库列表（服务端已按可见范围过滤）：PPT 结合知识库生成的选择入口 */
        const val KBS = "/ppt/kbs"
        const val TEMPLATE_UPLOAD = "/ppt/templates/upload"
        fun template(id: String) = "/ppt/templates/$id"
        fun templatePublish(id: String) = "/ppt/templates/$id/publish"
        fun templateRefreshPreview(id: String) = "/ppt/templates/$id/refresh-preview"
        fun templateRecheck(id: String) = "/ppt/templates/$id/recheck"
        fun templateDelete(id: String) = "/ppt/templates/$id"
        const val OUTLINE = "/ppt/outline"
        /** 流式大纲（SSE）：stage 阶段事件 + done 携带权威大纲 */
        const val OUTLINE_STREAM = "/ppt/outline/stream"
        /** 生成前预检：信息不足时返回待确认问题（附默认方案），防止瞎编 */
        const val OUTLINE_PRECHECK = "/ppt/outline/precheck"
        /** 材料分析：多文件上传，逐份返回 AI 摘要与提取文本 */
        const val MATERIALS_ANALYZE = "/ppt/materials/analyze"
        /** 个人图片素材库：生成时只使用本次勾选的图片 */
        const val MATERIALS = "/ppt/materials"
        const val LIBRARY_IMAGES = "/ppt/library/images"
        const val GENERATE = "/ppt/generate"
        const val DOCUMENTS = "/ppt/documents"
        /** 上传已有 .pptx 继续修改：解析为可编辑大纲 */
        const val DOCUMENT_IMPORT = "/ppt/documents/import"
        fun document(id: String) = "/ppt/documents/$id"
        fun documentDraft(id: String) = "/ppt/documents/$id/draft"
        /** 渲染当前草稿为逐页 PNG 预览（工作台中栏真实版式） */
        fun documentPreview(id: String) = "/ppt/documents/$id/preview"
        fun documentVisualReview(id: String) = "/ppt/documents/$id/visual-review"
        fun documentExport(id: String) = "/ppt/documents/$id/export"
        fun documentDownload(id: String) = "/ppt/documents/$id/download"
        fun documentDrawio(id: String) = "/ppt/documents/$id/drawio"
        fun documentDelete(id: String) = "/ppt/documents/$id"
        /** 预览图（GET，name 为 pg-N.png） */
        fun previewImage(docId: String, name: String) = "/ppt/preview/$docId/$name"
        /** 单页局部修改（润色/扩写/精简/重写/自定义） */
        const val AI_SLIDE_ACTION = "/ppt/ai/slide-action"
        const val AI_VISUAL = "/ppt/ai/visual"
        /** 结构调整（新增/拆分/合并页） */
        const val AI_STRUCTURE = "/ppt/ai/structure"
        const val AI_OUTLINE_ADJUST = "/ppt/ai/outline-adjust"

        /**
         * 异步生成任务（PPTAgent 一次生成要 5–15 分钟，必须「提交即返回 + 轮询 + 逐页预览」）。
         *
         * 注意：这里只写 `/ppt/...` 段——服务端 router 前缀是 `/ppt`，
         * 而 `/api/v1` 由 [com.judicialai.desktop.core.storage.ServerConfig.apiBase] 统一补上
         * （见 server/app/main.py 的 `include_router(r, prefix="/api/v1")`）。
         * 但 preview 返回的 `png_url` 是**服务器根相对路径**（不带 /api/v1），
         * 图片加载走 ApiClient.imageBytes（baseUrl），两边不要混用。
         */
        object Jobs {
            /** POST：提交任务，立即返回 {job_id, status, phase, message} */
            const val CREATE = "/ppt/jobs"
            fun status(id: String) = "/ppt/jobs/$id/status"
            fun preview(id: String) = "/ppt/jobs/$id/preview"
            /**
             * 单页预览图（index 从 0 开始，与 GET preview 里的 index 一致）。
             * 不带扩展名：PPTAgent 实际产出是 jpg（`slide_01.jpg`），路由已改为
             * `/preview/{page}`（`0` / `0.jpg` / `0.png` 都能取到）。
             * 客户端一律优先用 `/preview` 返回的 url，这里只是兜底。
             */
            fun previewPage(id: String, index: Int) = "/ppt/jobs/$id/preview/$index"
            fun cancel(id: String) = "/ppt/jobs/$id/cancel"
            /** POST：回答 PPTAgent 的追问 {answer}，带着上下文续跑同一任务 */
            fun clarify(id: String) = "/ppt/jobs/$id/clarify"
            /** GET：下载 pptx */
            fun export(id: String) = "/ppt/jobs/$id/export"
        }
    }

    object Workflow {
        const val TEMPLATES = "/workflow/templates"
        const val INSTANCES = "/workflow/instances"
        fun instance(id: String) = "/workflow/instances/$id"
        fun nodeGenerate(nodeInstId: String) = "/workflow/nodes/$nodeInstId/generate"
        fun nodeUpdate(nodeInstId: String) = "/workflow/nodes/$nodeInstId"
    }

    object Training {
        const val OVERVIEW = "/training/overview"
        const val ASSETS = "/training/assets"
        fun asset(id: String) = "/training/assets/$id"
        const val IMPORT_DIR = "/training/assets/import-dir"
        const val IMPORT_FILE = "/training/assets/import-file"
        fun assetGenerateSample(id: String) = "/training/assets/$id/generate-sample"
        const val SAMPLES = "/training/samples"
        const val SAMPLE_FROM_CHAT = "/training/samples/from-chat"
        fun sample(id: String) = "/training/samples/$id"
        fun sampleReview(id: String) = "/training/samples/$id/review"
        const val DATASETS = "/training/datasets"
        // 参数名是 datasetId（后端 /training/datasets/{dataset_id}/versions），
        // 写成 $id 会解析到不存在的标识符，编译不过
        fun datasetVersions(datasetId: String) = "/training/datasets/$datasetId/versions"
        const val JOBS = "/training/jobs"
        fun job(id: String) = "/training/jobs/$id"
        fun jobCancel(id: String) = "/training/jobs/$id/cancel"
        const val MODELS = "/training/models"
        fun modelPublish(id: String) = "/training/models/$id/publish"
        fun modelArchive(id: String) = "/training/models/$id/archive"
    }

    object Approvals {
        const val CREATE = "/approvals"          // POST 提交审核
        const val LIST = "/approvals"            // GET 列表
        const val COUNTS = "/approvals/counts"
        fun item(id: String) = "/approvals/$id"
        fun actions(id: String) = "/approvals/$id/actions"
        fun action(id: String) = "/approvals/$id/action"
        fun number(id: String) = "/approvals/$id/number"
    }

    object System {
        const val APPROVAL_CONFIG = "/system/approval-config"
    }

    /** 组织与科室 Agent：后端强隔离，前端只展示后端下发内容，不自行推导权限 */
    object Organization {
        const val LIST = "/organization/departments"
        const val ME = "/organization/me"
        /** 本科室空间：助手 + 常用业务 + 知识资源 + 本科室模板（服务端按登录用户解析） */
        const val SPACE = "/organization/space"
        fun agent(code: String) = "/organization/agents/$code"
        fun agentVersions(code: String) = "/organization/agents/$code/versions"
    }

    /** 首页聚合（v3.0 后端已实现，客户端 v3.1 起使用） */
    object Dashboard {
        const val SUMMARY = "/dashboard/summary"
    }

    /**
     * 个人偏好（v3.3）：只影响 AI 的表达方式、写作习惯与称呼，
     * 不含任何科室 / 权限 / 角色语义，且只能读写当前登录用户本人。
     */
    object Preferences {
        const val ME = "/preferences/me"
    }

    object WritingMemories {
        const val LIST = "/writing/memories"
        fun item(id: String) = "$LIST/$id"
    }
}
