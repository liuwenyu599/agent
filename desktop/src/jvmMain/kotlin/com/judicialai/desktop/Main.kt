package com.judicialai.desktop

import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.painter.BitmapPainter
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState
import com.judicialai.desktop.app.App
import com.judicialai.desktop.app.SplashScreen
import com.judicialai.desktop.design.theme.AppLogo
import kotlinx.coroutines.delay

/** 启动窗口：先展示启动页（Logo + 名称），约 1.6 秒后进入应用主界面 */
fun main() = application {
    val windowIcon = remember { BitmapPainter(AppLogo.imageBitmap) }
    var showSplash by remember { mutableStateOf(true) }

    LaunchedEffect(Unit) {
        delay(1600)
        showSplash = false
    }

    Window(
        onCloseRequest = ::exitApplication,
        title = "司法智能办公辅助平台",
        icon = windowIcon,
        state = rememberWindowState(width = 1280.dp, height = 800.dp),
    ) {
        if (showSplash) SplashScreen() else App()
    }
}
