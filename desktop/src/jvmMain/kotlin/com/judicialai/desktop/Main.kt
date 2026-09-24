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
import com.judicialai.desktop.design.theme.AppLogo
import kotlinx.coroutines.delay
import java.awt.event.WindowAdapter
import java.awt.event.WindowEvent

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
            title = "司法智能办公辅助平台",
            icon = windowIcon,
            state = rememberWindowState(width = 1280.dp, height = 800.dp),
        ) { SplashScreen() }
        return@application
    }

    WindowManager.sessions.forEach { session ->
        key(session.id) {
            Window(
                onCloseRequest = {
                    if (session === mainSession || WindowManager.sessions.size <= 1) {
                        exitApplication()
                    } else {
                        WindowManager.close(session)
                    }
                },
                title = "司法智能办公辅助平台",
                icon = windowIcon,
                state = rememberWindowState(width = 1280.dp, height = 800.dp),
            ) {
                LaunchedEffect(session.id) { WindowManager.activate(session) }
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
                    App()
                }
            }
        }
    }
}
