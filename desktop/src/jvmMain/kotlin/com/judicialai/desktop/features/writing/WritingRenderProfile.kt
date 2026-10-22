package com.judicialai.desktop.features.writing

import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.font.FontFamily
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.serialization.json.JsonObject
import java.awt.GraphicsEnvironment
import java.util.concurrent.ConcurrentHashMap

internal data class PreviewTextStyle(
    val fontName: String,
    val size: Float,
    val lineHeight: Float,
    val firstLineChars: Float = 0f,
    val rightIndentChars: Float = 0f,
    val alignment: String = "left",
    val bold: Boolean = false,
)

private fun JsonObject?.number(key: String, fallback: Float): Float =
    this?.get(key)?.str()?.toFloatOrNull() ?: fallback

internal fun JsonObject?.previewStyle(role: String): PreviewTextStyle {
    val defaults = when (role) {
        "title" -> PreviewTextStyle("方正小标宋简体", 22f, 34f, alignment = "center")
        "heading1" -> PreviewTextStyle("黑体", 16f, 28.8f)
        "heading2" -> PreviewTextStyle("楷体_GB2312", 16f, 28.8f)
        "document_number" -> PreviewTextStyle("仿宋_GB2312", 14f, 22f, alignment = "center")
        "signature", "date" -> PreviewTextStyle("仿宋_GB2312", 16f, 28.8f,
            rightIndentChars = 4f, alignment = "right")
        "recipient" -> PreviewTextStyle("仿宋_GB2312", 16f, 28.8f)
        else -> PreviewTextStyle("仿宋_GB2312", 16f, 28.8f, firstLineChars = 2f)
    }
    val checks = this?.get("styles")?.obj()?.get(role)?.obj()
    return defaults.copy(
        fontName = checks?.get("font_name")?.str()?.ifBlank { defaults.fontName }
            ?: defaults.fontName,
        size = checks.number("font_size_pt", defaults.size),
        lineHeight = checks.number("line_spacing_pt", defaults.lineHeight),
        firstLineChars = checks.number("first_line_indent_chars", defaults.firstLineChars),
        rightIndentChars = checks.number("right_indent_chars", defaults.rightIndentChars),
        alignment = checks?.get("alignment")?.str()?.ifBlank { defaults.alignment }
            ?: defaults.alignment,
        bold = checks?.get("bold")?.str()?.toBooleanStrictOrNull() ?: defaults.bold,
    )
}

internal fun JsonObject?.pageCm(key: String, fallback: Float): Float =
    this?.get("page")?.obj().number(key, fallback)

internal object PreviewFonts {
    private val families = ConcurrentHashMap<String, FontFamily>()
    private val available by lazy {
        GraphicsEnvironment.getLocalGraphicsEnvironment().availableFontFamilyNames
            .associateBy { it.lowercase() }
    }

    internal fun resolvedName(requested: String): String? {
        val candidates = when (requested) {
            "方正小标宋简体" -> listOf(requested, "小标宋", "Noto Serif CJK SC", "Noto Serif SC", "宋体")
            "仿宋_GB2312" -> listOf(requested, "仿宋", "FangSong", "Noto Serif CJK SC", "Noto Serif SC", "宋体")
            "楷体_GB2312" -> listOf(requested, "楷体", "KaiTi", "Noto Serif CJK SC", "Noto Serif SC")
            "黑体" -> listOf(requested, "SimHei", "Noto Sans CJK SC", "Noto Sans SC", "微软雅黑")
            else -> listOf(requested, "Noto Serif CJK SC", "Noto Serif SC")
        }
        return candidates.firstNotNullOfOrNull { available[it.lowercase()] }
    }

    @OptIn(ExperimentalTextApi::class)
    internal fun family(requested: String): FontFamily =
        families.computeIfAbsent(requested) {
            resolvedName(it)?.let { name -> FontFamily(name) } ?: FontFamily.Serif
        }
}
