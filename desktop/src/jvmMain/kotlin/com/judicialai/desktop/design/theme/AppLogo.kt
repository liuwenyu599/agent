package com.judicialai.desktop.design.theme

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.toComposeImageBitmap
import org.jetbrains.skia.Image
import java.util.Base64

/**
 * 应用 Logo（内嵌 Base64 PNG，192×192，透明底）。
 * 用于启动页、窗口图标；打包安装器图标（icon.ico）单独配置在 build.gradle.kts。
 */
object AppLogo {
    private val PNG_B64: String = """
__B64_PART1__
__B64_PART2__
    """.trimIndent().replace("\n", "")

    val bytes: ByteArray by lazy { Base64.getDecoder().decode(PNG_B64) }

    val imageBitmap: ImageBitmap by lazy {
        Image.makeFromEncoded(bytes).toComposeImageBitmap()
    }
}

@Composable
fun rememberAppLogo(): ImageBitmap = remember { AppLogo.imageBitmap }
