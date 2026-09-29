package com.judicialai.desktop.design.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.SurfaceTonal

private val OrderedListRegex = Regex("^\\d+\\.\\s+.*")

/** 行内格式：解析 **粗体**，其余原样输出 */
private fun inlineMd(text: String): AnnotatedString = buildAnnotatedString {
    val regex = Regex("\\*\\*(.+?)\\*\\*")
    var last = 0
    for (m in regex.findAll(text)) {
        append(text.substring(last, m.range.first))
        withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(m.groupValues[1]) }
        last = m.range.last + 1
    }
    append(text.substring(last))
}

/**
 * 公文 Markdown 轻量渲染（共享组件）：标题（# / ## / ###）、无序/有序列表、分割线、粗体。
 *
 * 凡是「给用户看成稿」的位置都用它而不是裸 Text：
 * 智能写作预览、我的文档编辑台、历史记录文档预览、版本预览。
 * 与导出 docx 的 GB/T 9704 排版对应——屏上先看到带层级的版式，不再是满屏无格式 txt。
 */
@Composable
fun MarkdownView(text: String, modifier: Modifier = Modifier) {
    val lines = text.split('\n')

    fun tableCells(line: String): List<String> {
        val raw = line.trim()
        val parts = raw.split('|').toMutableList()
        if (raw.startsWith("|") && parts.isNotEmpty()) parts.removeAt(0)
        if (raw.endsWith("|") && parts.isNotEmpty()) parts.removeAt(parts.lastIndex)
        return parts.map { it.trim() }
    }

    fun isSeparator(line: String): Boolean {
        val cells = tableCells(line)
        return cells.isNotEmpty() && cells.all {
            it.replace(":", "").trim().matches(Regex("-{3,}"))
        }
    }

    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        var i = 0
        while (i < lines.size) {
            val line = lines[i]
            val t = line.trimEnd()
            val s = t.trim()

            if (s.contains("|") && i + 1 < lines.size && isSeparator(lines[i + 1])) {
                val rows = mutableListOf<List<String>>()
                rows += tableCells(s)
                i += 2 // 跳过 Markdown 表头分隔行
                while (i < lines.size && lines[i].contains("|") && lines[i].isNotBlank()) {
                    rows += tableCells(lines[i])
                    i += 1
                }
                val cols = rows.maxOfOrNull { it.size } ?: 0
                if (cols > 0) {
                    Column(
                        Modifier.fillMaxWidth()
                            .border(1.dp, Line, RoundedCornerShape(6.dp))
                    ) {
                        rows.forEachIndexed { rowIndex, row ->
                            Row(
                                Modifier.fillMaxWidth()
                                    .background(if (rowIndex == 0) SurfaceTonal else androidx.compose.ui.graphics.Color.Transparent)
                            ) {
                                repeat(cols) { col ->
                                    Text(
                                        inlineMd(row.getOrElse(col) { "" }),
                                        modifier = Modifier.weight(1f)
                                            .padding(horizontal = 8.dp, vertical = 6.dp),
                                        fontSize = 12.5.sp,
                                        fontWeight = if (rowIndex == 0) FontWeight.SemiBold else FontWeight.Normal,
                                        color = Ink2,
                                        lineHeight = 19.sp,
                                    )
                                }
                            }
                        }
                    }
                }
                continue
            }

            when {
                s.isBlank() -> Spacer(Modifier.height(4.dp))
                s == "---" || s == "***" || s == "___" -> {
                    Spacer(Modifier.height(4.dp)); Hairline(); Spacer(Modifier.height(4.dp))
                }
                s.startsWith("### ") -> Text(
                    inlineMd(s.removePrefix("### ")), fontSize = 15.sp,
                    fontWeight = FontWeight.SemiBold, color = Ink, lineHeight = 22.sp)
                s.startsWith("## ") -> Text(
                    inlineMd(s.removePrefix("## ")), fontSize = 16.5.sp,
                    fontWeight = FontWeight.Bold, color = Ink, lineHeight = 24.sp)
                s.startsWith("# ") -> Text(
                    inlineMd(s.removePrefix("# ")), fontSize = 18.sp,
                    fontWeight = FontWeight.Bold, color = Ink, lineHeight = 26.sp,
                    modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center)
                s.startsWith("- ") || s.startsWith("* ") -> Row {
                    Text("•  ", fontSize = 14.5.sp, color = Ink)
                    Text(inlineMd(s.substring(2)), fontSize = 14.5.sp, color = Ink,
                        lineHeight = 26.sp)
                }
                OrderedListRegex.matches(s) -> {
                    val idx = s.indexOf('.')
                    Row {
                        Text(s.substring(0, idx + 1) + "  ", fontSize = 14.5.sp, color = Ink)
                        Text(inlineMd(s.substring(idx + 1).trim()), fontSize = 14.5.sp,
                            color = Ink, lineHeight = 26.sp)
                    }
                }
                else -> Text(inlineMd(s), fontSize = 14.5.sp, color = Ink, lineHeight = 26.sp)
            }
            i += 1
        }
    }
}
