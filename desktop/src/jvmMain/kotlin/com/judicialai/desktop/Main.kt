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
import java.awt.event.WindowAdapter
import java.awt.event.WindowEvent

/** 窗口标题：对外显示的正式品牌名 */
private const val APP_TITLE = "白云司法局智慧办公平台"

/**
 * 启动窗口：先展示启动页（Logo + 名称），约 1.6 秒后进入应用主界面。
 *
 * 多开独立窗口：
 * - WindowManager.sessions 里每个会话对应一个操作系统级独立窗口，
 *   各自导航互不干扰（页面状态见 WindowSession）；
 * - 登录态 / 生成任务等全局状态共享 AppState：一个窗口跑公文/PPT 生成时，
 *   另一个窗口正常办公，切回仍能看进度，不会因界面重建而报错；
 * - 关闭主窗口 = 退出应用；关闭其他窗口只关自己；
 * - 「新开窗口」入口在右上角用户菜单。
 *
 * 所有窗口均为无边框 + 透明底（undecorated + transparent），系统标题栏不再渲染，
 * 由 [WindowChrome] 裁圆角并提供拖拽带，窗口控制按钮画在 Header 右侧。
 */
fun main() = application {
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
