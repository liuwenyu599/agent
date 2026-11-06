package com.judicialai.desktop.features.ppt

import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.bool
import com.judicialai.desktop.core.utils.items
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import java.io.File

/** PPT 助手数据访问（对应 Web PptView / PptTemplateLib + 工作台重设计新接口） */
class PptRepository(private val api: ApiClient) {

    /**
     * PPTAgent 一次生成要 5–15 分钟，远超全局默认 120 秒，
     * 所以这类长任务的超时在这里显式放宽（**不动全局默认**，那是用户在设置页可调的）。
     */
    companion object {
        /** 提交任务：只提交、不等结果 */
        const val TIMEOUT_SUBMIT_MS = 30_000L
        /** 轮询任务状态：普通 GET，快速失败后按退避重试 */
        const val TIMEOUT_STATUS_MS = 60_000L
        /** 导出 pptx：渲染完成后的文件下载，按长任务放宽到 20 分钟 */
        const val TIMEOUT_EXPORT_MS = 1_200_000L
        /** 同步生成接口（异步不可用时的回退路径）同样按长任务放宽 */
        const val TIMEOUT_GENERATE_MS = 1_200_000L
    }

    suspend fun templates(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Ppt.TEMPLATES)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    suspend fun themes(): ApiResult<List<JsonObject>> =
        when (val r = api.get("/ppt/themes")) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    /** PPT 可选知识库（服务端已按可见范围过滤）→ [{id, name, description, doc_count}] */
    suspend fun kbs(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Ppt.KBS)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    suspend fun uploadTemplate(file: File, shared: Boolean = false,
                               licenseNote: String = "") =
        api.upload(Endpoints.Ppt.TEMPLATE_UPLOAD, "file", listOf(file),
            formFields = mapOf("shared" to shared.toString(),
                "license_note" to licenseNote), timeoutMs = 300_000)

    suspend fun deleteTemplate(id: String) = api.del(Endpoints.Ppt.templateDelete(id))

    suspend fun templateDetail(id: String): ApiResult<JsonObject> =
        when (val r = api.get(Endpoints.Ppt.template(id))) {
            is ApiResult.Ok -> {
                val obj = r.data.obj()
                if (obj != null) ApiResult.Ok(obj)
                else ApiResult.Err(null, "模板详情格式错误")
            }
            is ApiResult.Err -> r
        }

    suspend fun updateTemplate(
        id: String,
        name: String,
        category: String,
        description: String,
        font: String,
        layouts: Map<String, String>,
    ) = api.put(
        Endpoints.Ppt.template(id),
        mapOf(
            "name" to name,
            "category" to category,
            "description" to description,
            "font" to font,
            "layouts" to layouts,
        ),
    )


    /** 返回 (docId, outlineJson) */
    suspend fun outline(
        sourceType: String, topic: String, content: String,
        slideCount: Int?, audience: String, scene: String,
        kbIds: List<String> = emptyList(),
        materialNames: List<String> = emptyList(),
        materialIds: List<String> = emptyList(),
        autoImages: Boolean = true,
        themeId: String? = null,
    ): ApiResult<Pair<String?, String>> {
        val body = mutableMapOf<String, Any?>(
            "source_type" to sourceType, "topic" to topic, "content" to content,
            "audience" to audience, "scene" to scene,
            "kb_ids" to kbIds,
            "material_names" to materialNames,
            "material_ids" to materialIds,
            "auto_images" to autoImages,
            "theme_id" to themeId,
        ).apply {
            slideCount?.let { put("slide_count", it) }
        }
        return when (val r = api.post(Endpoints.Ppt.OUTLINE, body, timeoutMs = 180_000)) {
            is ApiResult.Ok -> {
                val d = r.data.obj()
                ApiResult.Ok(
                    (d?.get("doc_id")?.str()?.ifBlank { null }) to
                        (d?.get("outline")?.toString() ?: ""))
            }
            is ApiResult.Err -> r
        }
    }

    /** 流式大纲（SSE）：onEvent 回调 {type: stage|done|error} 事件 */
    suspend fun outlineStream(body: Map<String, Any?>, onEvent: (JsonObject) -> Unit) =
        api.postStream(Endpoints.Ppt.OUTLINE_STREAM, body,
            timeoutMs = 300_000, onEvent = onEvent)

    /** 生成前预检 → {sufficient, questions: [{question, default}]}（失败时调用方直接放行） */
    suspend fun precheck(body: Map<String, Any?>) =
        api.post(Endpoints.Ppt.OUTLINE_PRECHECK, body, timeoutMs = 60_000)

    /** 材料分析：多文件上传，逐份返回 {filename, chars, summary, key_points, tables, text} + totals */
    suspend fun analyzeMaterials(files: List<File>) =
        api.upload(Endpoints.Ppt.MATERIALS_ANALYZE, "files", files, timeoutMs = 300_000)

    suspend fun libraryMaterials(): ApiResult<List<JsonObject>> =
        when (val result = api.get(Endpoints.Ppt.MATERIALS)) {
            is ApiResult.Ok -> ApiResult.Ok(result.data.items())
            is ApiResult.Err -> result
        }

    suspend fun uploadLibraryMaterial(file: File) =
        api.upload(Endpoints.Ppt.MATERIALS, "file", listOf(file),
            formFields = mapOf("name" to file.nameWithoutExtension, "caption" to ""))

    suspend fun uploadPublicImage(file: File, category: String, caption: String,
                                  source: String, licenseNote: String) =
        api.upload(Endpoints.Ppt.LIBRARY_IMAGES, "file", listOf(file),
            formFields = mapOf("name" to file.nameWithoutExtension,
                "category" to category, "caption" to caption,
                "source" to source, "license_note" to licenseNote))

    suspend fun updateImageCaption(id: String, source: String, caption: String) =
        api.patch(
            if (source == "library") "${Endpoints.Ppt.LIBRARY_IMAGES}/$id/caption"
            else "${Endpoints.Ppt.MATERIALS}/$id/caption",
            mapOf("caption" to caption),
        )

    /** 上传已有 .pptx 继续修改 → {doc_id, outline, message} */
    suspend fun importPptx(file: File) =
        api.upload(Endpoints.Ppt.DOCUMENT_IMPORT, "file", listOf(file), timeoutMs = 300_000)

    suspend fun document(id: String) = api.get(Endpoints.Ppt.document(id))

    /** 保存草稿（大纲编辑结果写回服务端，不改变文档状态） */
    suspend fun saveDraft(id: String, title: String, outline: JsonObject, templateId: String?) =
        api.put(Endpoints.Ppt.documentDraft(id),
            mapOf("title" to title, "outline" to outline, "template_id" to templateId))

    /** 渲染当前草稿为逐页 PNG 预览 → {pages: [url...], count} */
    suspend fun preview(id: String) =
        api.post(Endpoints.Ppt.documentPreview(id), emptyMap<String, Any?>(), timeoutMs = 300_000)

    suspend fun visualReview(id: String) =
        api.post(Endpoints.Ppt.documentVisualReview(id), emptyMap<String, Any?>(), timeoutMs = 300_000)

    /** 单页局部修改：action = rewrite / expand / condense / custom */
    suspend fun aiSlideAction(action: String, slide: JsonObject, instruction: String) =
        api.post(Endpoints.Ppt.AI_SLIDE_ACTION,
            mapOf("action" to action, "slide" to slide, "instruction" to instruction),
            timeoutMs = 180_000)

    suspend fun aiVisual(kind: String, slide: JsonObject, instruction: String,
                         templateId: String?) =
        api.post(Endpoints.Ppt.AI_VISUAL,
            mapOf("kind" to kind, "slide" to slide, "instruction" to instruction,
                "template_id" to templateId), timeoutMs = 180_000)

    /** 结构调整：action = add / split / merge */
    suspend fun aiStructure(action: String, slides: List<JsonObject>, index: Int) =
        api.post(Endpoints.Ppt.AI_STRUCTURE,
            mapOf("action" to action, "slides" to slides, "index" to index, "instruction" to ""),
            timeoutMs = 180_000)

    /** 大纲确认页：一句自然语言整体调整当前大纲。 */
    suspend fun aiOutlineAdjust(outline: JsonObject, instruction: String) =
        api.post(
            Endpoints.Ppt.AI_OUTLINE_ADJUST,
            mapOf("outline" to outline, "instruction" to instruction),
            timeoutMs = 180_000,
        )

    /**
     * 同步生成（PPTAgent 渲染）。PPTAgent 跑满要 15 分钟，
     * 300 秒必然先断，这里放宽到 20 分钟。新流程走 [submitJob] 异步，这是回退路径。
     */
    suspend fun generate(docId: String, outline: JsonElement, templateId: String?) =
        api.post(Endpoints.Ppt.GENERATE,
            mapOf("doc_id" to docId, "outline" to outline, "template_id" to templateId),
            timeoutMs = TIMEOUT_GENERATE_MS)

    suspend fun documents(): ApiResult<List<JsonObject>> =
        when (val r = api.get(Endpoints.Ppt.DOCUMENTS)) {
            is ApiResult.Ok -> ApiResult.Ok(r.data.items())
            is ApiResult.Err -> r
        }

    /**
     * 导出已生成的 pptx。
     * 默认 5 分钟（对已经渲染好的文件足够，列表页「下载」走这个）；
     * 生成流程里紧接 PPTAgent 渲染的那次下载显式传 [TIMEOUT_EXPORT_MS]。
     */
    suspend fun downloadDocument(id: String, target: File, timeoutMs: Long = 300_000) =
        api.downloadPost(Endpoints.Ppt.documentExport(id), emptyMap(), target, timeoutMs)

    suspend fun downloadDrawio(id: String, target: File) =
        api.downloadGet(Endpoints.Ppt.documentDrawio(id), target)

    suspend fun deleteDocument(id: String) = api.del(Endpoints.Ppt.documentDelete(id))

    /** PATCH /ppt/documents/{id} {title} → 重命名演示文稿 */
    suspend fun renameDocument(id: String, title: String) =
        api.patch(Endpoints.Ppt.document(id), mapOf("title" to title))

    // ================= 异步生成任务（/ppt/jobs） =================

    /**
     * POST /ppt/jobs：提交生成任务，**立即返回**（后台线程接管，不阻塞）。
     * 请求体是 {doc_id, message}：doc_id 同时就是 job_id（一个文档同时只有一个进行中的任务），
     * message 是用户补充需求（追加到给 PPTAgent 的需求末尾）。
     * 大纲走服务端已存的 doc.outline，所以**调用前必须先 saveDraft**。
     *
     * 注意：「已有任务在跑」时返回 status=running；无 PPTAgent 时后端改走本地渲染，
     * 仍返回 pending。失败（如缺大纲）则以 status=failed + 说明回传（HTTP 仍是 200）。
     */
    suspend fun submitJob(docId: String, message: String): ApiResult<PptJobSubmit> =
        postJob(Endpoints.Ppt.Jobs.CREATE, docId, message)

    /** POST /ppt/jobs/{id}/clarify：回答 PPTAgent 的追问，带上下文续跑同一任务 */
    suspend fun clarifyJob(id: String, answer: String): ApiResult<PptJobSubmit> =
        postJob(Endpoints.Ppt.Jobs.clarify(id), id, answer)

    private suspend fun postJob(path: String, id: String, text: String): ApiResult<PptJobSubmit> {
        val body = if (path.endsWith("/clarify")) mapOf("answer" to text)
        else mapOf("doc_id" to id, "message" to text)
        return when (val r = api.post(path, body, timeoutMs = TIMEOUT_SUBMIT_MS)) {
            is ApiResult.Ok -> {
                val d = r.data.obj()
                if (d == null) ApiResult.Err(null, "服务端返回内容无法解析")
                else {
                    val jobId = d["job_id"].str().ifBlank { null }
                        ?: d["id"].str().ifBlank { null } ?: id
                    ApiResult.Ok(PptJobSubmit(
                        jobId = jobId,
                        status = d["status"].str().ifBlank { "pending" },
                        hint = d["message"].str(),
                    ))
                }
            }
            is ApiResult.Err -> r
        }
    }

    /**
     * GET /ppt/jobs/{id}/status：轮询任务进度。
     * elapsed_seconds / estimated_remaining 后端给的是**浮点**（如 320.4），
     * 按 Int 解析会恒为 0，这里先按字符串转 Double 再取整。
     */
    suspend fun jobStatus(id: String): ApiResult<PptJobStatusSnapshot> =
        when (val r = api.get(Endpoints.Ppt.Jobs.status(id), timeoutMs = TIMEOUT_STATUS_MS)) {
            is ApiResult.Ok -> {
                val d = r.data.obj()
                if (d == null) ApiResult.Err(null, "任务状态解析失败")
                else ApiResult.Ok(PptJobStatusSnapshot(
                    status = d["status"].str().ifBlank { "running" },
                    totalPages = d["total_pages"].int(),
                    currentPage = d["current_page"].int(),
                    phase = d["phase"].str(),
                    elapsedSeconds = d["elapsed_seconds"].str().toDoubleOrNull()?.toInt() ?: 0,
                    // 未完成时后端给 null；这里必须保持 null，否则会显示"预计还需 0 秒"
                    estimatedRemaining = d["estimated_remaining"].str().toDoubleOrNull()?.toInt(),
                    errorMsg = d["error_msg"].str().ifBlank { null },
                    // PPTAgent 信息不足时的追问文本，非空即等待用户回答
                    question = d["question"].str().ifBlank { null },
                    // 产物来源：pptagent（PPTAgent 产物）/ local（已回退本地渲染）
                    renderer = d["renderer"].str().ifBlank { null },
                ))
            }
            is ApiResult.Err -> r
        }

    /**
     * GET /ppt/jobs/{id}/preview：已生成页清单（PNG 本身按需单页拉取）。
     * 后端返回 {job_id, count, pages:[{index, url}]}：index 从 0 开始、url 带 /api/v1 前缀；
     * 目录结构未确认时 count 会是 0、pages 为空（后端刻意降级不报错），这里照常返回空列表。
     * 只列已存在的文件，所以列出的页一律视为「已出图」。
     */
    suspend fun jobPreview(id: String): ApiResult<List<PptJobPage>> =
        when (val r = api.get(Endpoints.Ppt.Jobs.preview(id), timeoutMs = TIMEOUT_STATUS_MS)) {
            is ApiResult.Ok -> ApiResult.Ok(
                r.data.obj()?.get("pages").arr().mapNotNull { it.obj() }.mapIndexed { pos, o ->
                    // 后端给 index（0 开始）；老规格给 n（1 开始）。两者都兼容，位置兜底。
                    val idx = (o["index"] as? JsonPrimitive)?.intOrNull
                    val nRaw = (o["n"] as? JsonPrimitive)?.intOrNull
                    val n = nRaw ?: ((idx ?: pos) + 1)
                    val url = o["url"].str().ifBlank { o["png_url"].str() }
                    PptJobPage(
                        n = n,
                        index = idx ?: (n - 1),
                        // 没有 png_ready 字段时：列出来就说明文件已存在
                        pngReady = o["png_ready"].bool(url.isNotBlank()),
                        pngUrl = url,
                    )
                }.sortedBy { it.n })
            is ApiResult.Err -> r
        }

    /** POST /ppt/jobs/{id}/cancel：取消任务（结果不阻塞，本地先回到已取消态） */
    suspend fun cancelJob(id: String) =
        api.post(Endpoints.Ppt.Jobs.cancel(id), emptyMap<String, Any?>(),
            timeoutMs = TIMEOUT_SUBMIT_MS)

    /** GET /ppt/jobs/{id}/export：下载 pptx（渲染完成后的落盘，20 分钟超时） */
    suspend fun exportJob(id: String, target: File) =
        api.downloadGet(Endpoints.Ppt.Jobs.export(id), target, timeoutMs = TIMEOUT_EXPORT_MS)
}
