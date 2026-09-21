package com.judicialai.desktop.features.approval

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.bool
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/** 待办视图 */
enum class ApprovalView(val label: String, val key: String) {
    TODO("待我审批", "todo"),
    MINE("我发起的", "mine"),
    DONE("已办结", "done"),
}

data class ApprovalItem(
    val id: String = "",
    val documentId: String = "",
    val title: String = "",
    val status: String = "",
    val statusName: String = "",
    val step: String = "",
    val stepName: String = "",
    val submitter: String = "",
    val department: String = "",
    val docNumber: String = "",
    val urgency: String = "normal",
    val submittedAt: String = "",
    val contentExcerpt: String = "",
)

data class ApprovalActionItem(
    val action: String = "",
    val actionName: String = "",
    val fromName: String = "",
    val toName: String = "",
    val comment: String = "",
    val actorName: String = "",
    val actorRole: String = "",
    val createdAt: String = "",
)

/** 可执行的流转动作（由后端 available_actions 下发，前端不做硬编码流程判断） */
data class AvailableAction(
    val action: String,
    val name: String,
    val needComment: Boolean,
)

enum class ApprovalLoadState { LOADING, READY, EMPTY, ERROR }

class ApprovalViewModel {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val repo = ApprovalRepository(AppState.api)

    private var view by mutableStateOf(ApprovalView.TODO)

    var viewState by mutableStateOf(ApprovalLoadState.LOADING)
        private set
    var items by mutableStateOf(listOf<ApprovalItem>())
        private set
    var error by mutableStateOf("")
        private set

    // 详情
    var detailId by mutableStateOf<String?>(null)
        private set
    var detail by mutableStateOf<ApprovalItem?>(null)
        private set
    var actions by mutableStateOf(listOf<ApprovalActionItem>())
        private set
    var availableActions by mutableStateOf(listOf<AvailableAction>())
        private set
    var detailError by mutableStateOf("")
        private set
    var acting by mutableStateOf(false)
        private set
    var actionError by mutableStateOf("")
        private set
    var actionDone by mutableStateOf("")
        private set

    fun currentView() = view

    fun switch(v: ApprovalView) {
        if (v == view && viewState != ApprovalLoadState.LOADING) return
        view = v
        load()
    }

    fun load() {
        viewState = ApprovalLoadState.LOADING
        error = ""
        scope.launch {
            when (val r = repo.list(view.key)) {
                is ApiResult.Ok -> {
                    val list = r.data.obj()?.get("items").arr().mapNotNull { it.obj() }.map { o ->
                        ApprovalItem(
                            id = o["id"].str(),
                            documentId = o["document_id"].str(),
                            title = o["title"].str().ifBlank { "未命名公文" },
                            status = o["current_status"].str(),
                            statusName = o["current_status_name"].str(),
                            step = o["current_step"].str(),
                            stepName = o["current_step_name"].str(),
                            submitter = o["submitter_name"].str(),
                            department = o["department"].str(),
                            docNumber = o["doc_number"].str(),
                            urgency = o["urgency"].str().ifBlank { "normal" },
                            submittedAt = o["submitted_at"].str().take(16).replace("T", " "),
                            contentExcerpt = o["content_excerpt"].str(),
                        )
                    }
                    items = list
                    viewState = if (list.isEmpty()) ApprovalLoadState.EMPTY else ApprovalLoadState.READY
                }
                is ApiResult.Err -> {
                    error = r.message
                    items = emptyList()
                    viewState = ApprovalLoadState.ERROR
                }
            }
        }
    }

    fun openDetail(id: String) {
        detailId = id
        actionDone = ""
        actionError = ""
        scope.launch {
            when (val r = repo.detail(id)) {
                is ApiResult.Ok -> {
                    val o = r.data.obj()
                    if (o == null) {
                        detailError = "详情数据格式异常"
                        return@launch
                    }
                    detail = ApprovalItem(
                        id = o["id"].str(),
                        documentId = o["document_id"].str(),
                        title = o["title"].str().ifBlank { "未命名公文" },
                        status = o["current_status"].str(),
                        statusName = o["current_status_name"].str(),
                        step = o["current_step"].str(),
                        stepName = o["current_step_name"].str(),
                        submitter = o["submitter_name"].str(),
                        department = o["department"].str(),
                        docNumber = o["doc_number"].str(),
                        urgency = o["urgency"].str().ifBlank { "normal" },
                        submittedAt = o["submitted_at"].str().take(16).replace("T", " "),
                        contentExcerpt = o["content_excerpt"].str(),
                    )
                    actions = o["actions"].arr().mapNotNull { it.obj() }.map { a ->
                        ApprovalActionItem(
                            action = a["action"].str(),
                            actionName = a["action_name"].str(),
                            fromName = a["from_status_name"].str(),
                            toName = a["to_status_name"].str(),
                            comment = a["comment"].str(),
                            actorName = a["actor_name"].str(),
                            actorRole = a["actor_role"].str(),
                            createdAt = a["created_at"].str().take(16).replace("T", " "),
                        )
                    }
                    availableActions = o["available_actions"].arr().mapNotNull { it.obj() }.map { a ->
                        AvailableAction(
                            action = a["action"].str(),
                            name = a["name"].str(),
                            needComment = a["need_comment"].bool(false),
                        )
                    }
                    detailError = ""
                }
                is ApiResult.Err -> detailError = r.message
            }
        }
    }

    fun closeDetail() {
        detailId = null
        detail = null
        actions = emptyList()
        availableActions = emptyList()
    }

    /** 执行流转动作。需要意见的动作由调用方保证 comment 已填写，这里做二次校验。 */
    fun act(action: AvailableAction, comment: String) {
        val id = detailId ?: return
        if (action.needComment && comment.trim().length < 5) {
            actionError = "「${action.name}」必须填写不少于 5 个字的意见"
            return
        }
        acting = true
        actionError = ""
        scope.launch {
            when (val r = repo.act(id, action.action, comment.trim())) {
                is ApiResult.Ok -> {
                    actionDone = "已${action.name}"
                    AppState.refreshCounts()
                    closeDetail()
                    load()
                }
                is ApiResult.Err -> actionError = r.message
            }
            acting = false
        }
    }

    /** 提交送审（从我的文档发起） */
    fun submit(documentId: String, onResult: (Boolean, String) -> Unit) {
        scope.launch {
            when (val r = repo.submit(documentId)) {
                is ApiResult.Ok -> {
                    AppState.refreshCounts()
                    load()
                    onResult(true, "已提交送审")
                }
                is ApiResult.Err -> onResult(false, r.message)
            }
        }
    }

    /** 新建草稿计数（供空态引导文案使用） */
    fun total() = items.size
}
