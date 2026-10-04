package com.judicialai.desktop.app

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import java.awt.Window
import com.judicialai.desktop.design.components.ToastState

/**
 * 窗口会话：每个独立窗口一份。
 *
 * 「多开几个独立窗口」的导航隔离方案：
 * - 每个窗口有自己的当前页面 / 导航抽屉 / 个人中心开合状态，互不干扰；
 * - 登录态、服务器配置、跨页面生成任务标记（pptOutlineGenerating 等）仍在 AppState
 *   全局共享 —— 一个窗口里公文/PPT 正在生成时，另一个窗口可以正常办公，
 *   切回去还能看到任务进度，不会报错也不会丢任务；
 * - 全局导航调用（AppState.navigate 等）路由到「当前获得焦点的窗口」，
 *   因为用户交互必然发生在焦点窗口。
 */
class WindowSession(val id: String) {
    val toastState = ToastState()
    /** 本窗口当前页面 */
    var screen by mutableStateOf(AppScreen.HOME)

    /** 本窗口的全局导航抽屉是否打开 */
    var navDrawerOpen by mutableStateOf(false)

    /** 本窗口的个人中心抽屉是否打开 */
    var personalCenterOpen by mutableStateOf(false)
}

/** 窗口注册表：Main 按 sessions 渲染窗口列表；openNew 新增窗口，close 关闭非主窗口 */
object WindowManager {
    private var seq = 0

    /** 全部窗口会话（快照态列表，增减会触发 Main 重组从而开/关窗口） */
    val sessions = mutableStateListOf<WindowSession>()

    /** 当前焦点窗口：navigate / navDrawerOpen 等全局写操作的路由目标 */
    var active by mutableStateOf<WindowSession?>(null)

    /** 主窗口（关主窗口 = 退出应用） */
    fun ensureMain(): WindowSession {
        if (sessions.isEmpty()) sessions.add(WindowSession("main"))
        val main = sessions.first()
        if (active == null) active = main
        return main
    }

    /** 新开一个独立窗口（落在工作台页，用户可自行导航到任意功能） */
    fun openNew(): WindowSession {
        val s = WindowSession("win${++seq}")
        sessions.add(s)
        active = s
        return s
    }

    /** 关闭一个非主窗口 */
    fun close(s: WindowSession) {
        sessions.remove(s)
        if (active == s) active = sessions.lastOrNull()
    }

    /** 窗口获得焦点时登记（焦点窗口决定全局导航调用的落点） */
    fun activate(s: WindowSession) {
        active = s
    }
}

/** 当前组合所在的窗口会话；App / AppShell 据此渲染本窗口自己的页面与抽屉 */
val LocalWindowSession = staticCompositionLocalOf<WindowSession> { WindowManager.ensureMain() }


/** 当前 Compose Window 对应的 AWT Window；桌面原生拖拽等平台能力使用。 */
val LocalAwtWindow = staticCompositionLocalOf<Window?> { null }
