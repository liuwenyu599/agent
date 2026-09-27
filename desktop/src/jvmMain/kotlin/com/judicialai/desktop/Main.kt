package com.judicialai.desktop

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.painter.BitmapPainter
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState
import com.judicialai.desktop.app.App
import com.judicialai.desktop.app.LocalWindowSession
import com.judicialai.desktop.app.SplashScreen
import com.judicialai.desktop.app.WindowManager
import com.judicialai.desktop.design.layout.LocalWindowChrome
import com.judicialai.desktop.design.layout.WindowChrome
import com.judicialai.desktop.design.layout.trackWindowMaximized
import com.judicialai.desktop.design.layout.windowChromeActions
import com.judicialai.desktop.design.theme.AppLogo
import kotlinx.coroutines.delay
import java.awt.EventQueue
import java.awt.event.WindowAdapter
import java.awt.event.WindowEvent
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread

/** 窗口标题：对外显示的正式品牌名 */
private const val APP_TITLE = "白云司法局智慧办公平台"

/**
 * 单实例握手端口（仅监听 127.0.0.1，不对外）。
 * 作用：实现「再点一次图标 / 任务栏右键新开窗口」——第二个进程不另起一套应用，
 * 而是通知已在运行的进程新开一个窗口后自己退出，登录态与生成任务全部共享，不丢进度。
 */
private const val SINGLE_INSTANCE_PORT = 47632

/**
 * 尝试把「新开窗口」请求转发给已在运行的实例。
 * @return true = 已有实例接管，本进程应当直接退出
 */
private fun forwardToRunningInstance(): Boolean = try {
    Socket().use { s ->
        s.connect(InetSocketAddress("127.0.0.1", SINGLE_INSTANCE_PORT), 800)
        s.getOutputStream().write("NEW_WINDOW\n".toByteArray())
        s.getOutputStream().flush()
    }
    true
} catch (_: Exception) {
    false
}

/** 作为第一个实例：监听后续启动请求，每收到一次就在本进程内新开一个窗口 */
private fun startInstanceServer() {
    thread(isDaemon = true, name = "single-instance") {
        try {
            val server = ServerSocket(SINGLE_INSTANCE_PORT, 8,
                InetAddress.getByName("127.0.0.1"))
            while (true) {
                try {
                    server.accept().close()
                    // 窗口状态改动回到 UI 线程执行
                    EventQueue.invokeLater { WindowManager.openNew() }
                } catch (_: Exception) {
                    // 单次请求失败不影响后续监听
                }
            }
        } catch (_: Exception) {
            // 端口被占等极端情况：静默放弃转发能力，应用照常可用
        }
    }
}

/**
 * 启动窗口：先展示启动页（Logo + 名称），约 1.6 秒后进入应用主界面。
 *
 * 多开独立窗口：
 * - 再点一次桌面/任务栏图标（或任务栏右键新开窗口）= 在已运行的实例里新开窗口，
 *   第二个进程只做转发然后退出（见 [forwardToRunningInstance]）；
 * - WindowManager.sessions 里每个会话对应一个操作系统级独立窗口，
 *   各自导航互不干扰（页面状态见 WindowSession）；
 * - 登录态 / 生成任务等全局状态共享 AppState：一个窗口跑公文/PPT 生成时，
 *   另一个窗口正常办公，切回仍能看进度，不会因界面重建而报错；
 * - 关闭主窗口 = 退出应用；关闭其他窗口只关自己；
 * - 「新开窗口」入口也在右上角用户菜单。
 *
 * 所有窗口均为无边框 + 透明底（undecorated + transparent），系统标题栏不再渲染，
 * 由 [WindowChrome] 裁圆角并提供拖拽带，窗口控制按钮画在 Header 右侧。
 */
fun main() {
    // 已有实例在跑：把「新开窗口」转发过去，本进程退出（任务栏图标/快捷方式再点的行为）
    if (forwardToRunningInstance()) return
    startInstanceServer()
    application {
    val windowIcon = remember { BitmapPainter(AppLogo.imageBitmap) }
    var showSplash by remember { mutableStateOf(true) }
    val mainSession = remember { WindowManager.ensureMain() }

    LaunchedEffect(Unit) {
        delay(1600)
        showSplash = false
    }

    if (showSplash) {
        Window(
            onCloseRequest = ::exitApplication,
            title = APP_TITLE,
            icon = windowIcon,
            state = rememberWindowState(width = 1280.dp, height = 800.dp),
            undecorated = true,
            transparent = true,
        ) {
            // 启动页只有 1.6 秒，不放窗口控制按钮，仅需圆角 + 拖拽带
            WindowChrome(maximized = false, minimumSize = java.awt.Dimension(560, 420)) {
                SplashScreen()
            }
        }
        return@application
    }

    WindowManager.sessions.forEach { session ->
        key(session.id) {
            // 关闭逻辑集中定义：窗口控制按钮与 onCloseRequest 行为完全一致
            val onCloseRequest: () -> Unit = {
                if (session === mainSession || WindowManager.sessions.size <= 1) {
                    exitApplication()
                } else {
                    WindowManager.close(session)
                }
            }
            var maximized by remember { mutableStateOf(false) }

            Window(
                onCloseRequest = onCloseRequest,
                title = APP_TITLE,
                icon = windowIcon,
                state = rememberWindowState(width = 1280.dp, height = 800.dp),
                undecorated = true,
                transparent = true,
            ) {
                LaunchedEffect(session.id) { WindowManager.activate(session) }
                // 最大化状态：决定窗口圆角与 Header 上的最大化/还原图标
                trackWindowMaximized { maximized = it }
                // 焦点跟踪：全局导航调用（AppState.navigate 等）落在焦点窗口
                DisposableEffect(session.id) {
                    val listener = object : WindowAdapter() {
                        override fun windowGainedFocus(e: WindowEvent?) {
                            WindowManager.activate(session)
                        }
                    }
                    window.addWindowFocusListener(listener)
                    onDispose { window.removeWindowFocusListener(listener) }
                }
                CompositionLocalProvider(LocalWindowSession provides session) {
                    val chromeActions = windowChromeActions(
                        maximized = maximized,
                        close = onCloseRequest,
                    )
                    CompositionLocalProvider(LocalWindowChrome provides chromeActions) {
                        // 顶部拖拽带双击 = 与 Header 最大化按钮同一套逻辑
                        WindowChrome(
                            maximized = maximized,
                            onToggleMaximize = chromeActions.toggleMaximize,
                        ) {
                            App()
                        }
                    }
                }
            }
        }
    }
    }
}
