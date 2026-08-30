package com.judicialai.desktop

import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState
import com.judicialai.desktop.app.App

/** 仅负责启动窗口，不含任何业务逻辑 */
fun main() = application {
    Window(
        onCloseRequest = ::exitApplication,
        title = "司法智能办公辅助平台",
        state = rememberWindowState(width = 1280.dp, height = 800.dp),
    ) {
        App()
    }
}

