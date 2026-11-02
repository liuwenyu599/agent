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

/**
 * 从服务器加载图片为 Compose ImageBitmap（模板预览、PPT 逐页预览等）。
 *
 * [refreshKey] 变化会强制重新请求：用于「URL 没变但上次请求失败」的场景——
 * produceState 只认 key，URL 不变就永远不会重发，缩略图会一直空白。
 *
 * 请求失败在内部就地重试：PPT 生成中缩略图常在 png_ready 刚置位时打过去，
 * 服务端忙或连接抖动都会失败，失败即放弃会让该页永久空白。
 */
@Composable
fun rememberServerImage(api: ApiClient, pathOrUrl: String?, refreshKey: Any? = null): ImageBitmap? {
    return produceState<ImageBitmap?>(null, pathOrUrl, refreshKey) {
        if (pathOrUrl.isNullOrBlank()) return@produceState
        // 重试 3 次（1.5s / 3s / 4.5s 退避）；解码失败同样视为失败（坏图不值得缓存）
        for (attempt in 0..2) {
            val bytes = api.imageBytes(pathOrUrl)
            if (bytes != null) {
                value = runCatching {
                    Image.makeFromEncoded(bytes).toComposeImageBitmap()
                }.getOrNull()
                if (value != null) return@produceState
            }
            kotlinx.coroutines.delay(1500L * (attempt + 1))
        }
    }.value
}

