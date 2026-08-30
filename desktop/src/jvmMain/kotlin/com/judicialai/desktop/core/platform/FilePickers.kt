package com.judicialai.desktop.core.platform

import androidx.compose.runtime.Composable
import androidx.compose.runtime.produceState
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.toComposeImageBitmap
import com.judicialai.desktop.core.network.ApiClient
import org.jetbrains.skia.Image
import java.awt.FileDialog
import java.awt.Frame
import java.io.File

/** 桌面原生文件选择（AWT FileDialog，支持中文文件名） */
fun pickFiles(title: String = "选择文件", multi: Boolean = false): List<File> {
    val d = FileDialog(null as Frame?, title, FileDialog.LOAD)
    d.isMultipleMode = multi
    d.isVisible = true
    return d.files?.toList() ?: emptyList()
}

/** 选择保存位置 */
fun pickSaveFile(defaultName: String): File? {
    val d = FileDialog(null as Frame?, "保存到", FileDialog.SAVE)
    d.file = defaultName
    d.isVisible = true
    val f = d.file ?: return null
    val dir = d.directory ?: return null
    return File(dir, f)
}

/** 从服务器加载图片为 Compose ImageBitmap（模板预览等） */
@Composable
fun rememberServerImage(api: ApiClient, pathOrUrl: String?): ImageBitmap? {
    return produceState<ImageBitmap?>(null, pathOrUrl) {
        if (pathOrUrl.isNullOrBlank()) return@produceState
        val bytes = api.imageBytes(pathOrUrl) ?: return@produceState
        value = runCatching { Image.makeFromEncoded(bytes).toComposeImageBitmap() }.getOrNull()
    }.value
}

