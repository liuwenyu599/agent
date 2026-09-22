package com.judicialai.desktop.core.platform

import androidx.compose.runtime.Composable
import androidx.compose.runtime.produceState
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.toComposeImageBitmap
import com.judicialai.desktop.core.logging.ClientLog
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

/** 选择保存位置。返回 null = 用户取消，或对话框未返回可用目录（后者记日志便于诊断）。 */
fun pickSaveFile(defaultName: String): File? {
    val d = FileDialog(null as Frame?, "保存到", FileDialog.SAVE)
    d.file = defaultName
    d.isVisible = true
    val f = d.file ?: return null
    val dir = d.directory
    if (dir == null) {
        // 与「用户取消」区分开：这里是对话框异常返回，落日志方便定位为什么文件没生成
        ClientLog.error("保存对话框返回 file=$f 但 directory=null，无法定位保存位置")
        return null
    }
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

