package com.judicialai.desktop.app

import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue

/**
 * 全局通知中心。
 *
 * 与 [androidx.compose.runtime.mutableStateListOf] 一样是 Compose 可观察状态，
 * 但**挂在全局单例**而不是某个 WindowSession：一个窗口里跑完的生成任务，
 * 其它窗口（多开工作窗口）也能看到「已完成」提示，且不会因页面切换而丢。
 *
 * 设计原则（对应产品诉求「完成后不自动切页，只在右上角喇叭通知 + 弹窗」）：
 * - 任务完成**绝不**自动切换用户当前所在的页面；
 * - 完成事件通过 [push] 落到这里，顶栏喇叭出现未读角标，并可选地弹出一次完成弹窗；
 * - 用户点通知 / 弹窗的「查看」才跳转到对应页面（[navigateFromNotification]）。
 *
 * `pendingTarget` 是可选的「跳转前需预设的全局句柄」，例如 PPT 完成要带 docId，
 * 让目标页打开对应内容而不是停在入口页。
 */
data class AppNotification(
    val id: String,
    /** 类型：writing / ppt / format / system，决定喇叭列表里的图标与归类 */
    val kind: String,
    val title: String,
    val body: String,
    val createdAt: Long = System.currentTimeMillis(),
    /** 点击通知要跳转的页面；null 表示只关闭、不跳转 */
    val screen: AppScreen? = null,
    /**
     * 跳转前需预设的全局句柄（字段名 → 值）。
     * 目前支持：("pendingPptDocId" → docId)、("pendingWritingTaskId" → taskId)。
     */
    val pendingTarget: Pair<String, String>? = null,
    val read: Boolean = false,
)

object NotificationCenter {
    private var seq = 0L

    val items = mutableStateListOf<AppNotification>()

    var unreadCount by mutableStateOf(0)
        private set

    /**
     * 完成弹窗：最近一次要求弹出的通知。
     * 由全局宿主（[com.judicialai.desktop.app.App] 内的完成弹窗）消费——
     * 渲染后自动倒计时消失；用户点「查看」也调用 [consumePopup] 清除。
     */
    var popup by mutableStateOf<AppNotification?>(null)
        private set

    /**
     * 推送一条通知。
     * @param popup true 时同时作为完成弹窗弹出（会自动消失，不强制跳转）。
     */
    fun push(
        kind: String,
        title: String,
        body: String,
        screen: AppScreen? = null,
        pendingTarget: Pair<String, String>? = null,
        popup: Boolean = false,
    ) {
        val n = AppNotification(
            id = "ntf-${System.currentTimeMillis()}-${(++seq)}",
            kind = kind,
            title = title,
            body = body,
            screen = screen,
            pendingTarget = pendingTarget,
        )
        items.add(0, n)
        // 列表只保留最近 50 条，避免无限增长
        while (items.size > 50) items.removeAt(items.lastIndex)
        unreadCount = items.count { !it.read }
        if (popup) this.popup = n
    }

    fun markAllRead() {
        val copy = items.toList().map { it.copy(read = true) }
        items.clear()
        items.addAll(copy)
        unreadCount = 0
    }

    fun dismiss(id: String) {
        items.removeAll { it.id == id }
        unreadCount = items.count { !it.read }
        if (popup?.id == id) popup = null
    }

    fun clear() {
        items.clear()
        unreadCount = 0
        popup = null
    }

    /** 消费完成弹窗（用户已查看 / 倒计时结束） */
    fun consumePopup() {
        popup = null
    }
}

/**
 * 从一条通知跳转到对应页面：先预设全局句柄（如有），再 [AppState.navigate]。
 * 不在此处清未读——调用方（UI）在弹窗/列表里处理读标记。
 */
fun navigateFromNotification(n: AppNotification) {
    when (n.pendingTarget?.first) {
        "pendingPptDocId" -> AppState.pendingPptDocId = n.pendingTarget.second
        "pendingWritingTaskId" -> AppState.pendingWritingTaskId = n.pendingTarget.second
    }
    n.screen?.let { AppState.navigate(it) }
}
