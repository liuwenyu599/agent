package com.judicialai.desktop.design.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.TextSecondary

// ---------------------------------------------------------------- 块类型

/**
 * 正文块：由纯文本推断出的版式单元。
 *
 * 知识库文档是从 docx / pdf / ofd 抽取的纯文本，没有任何标记，只能靠行特征
 * 反推层级。推断错了最多是「这一行加粗了」，不会丢内容——所以这里宁可宽松。
 */
private sealed interface DocBlock {
    /** 公文大标题：居中加粗 */
    data class Title(val text: String) : DocBlock

    /** 章节序号行：一、 / （一） / 1. / 第一条 */
    data class Section(val text: String, val level: Int) : DocBlock

    /** 落款 / 成文日期：右对齐 */
    data class SignOff(val text: String) : DocBlock

    /** 普通正文段落：首行缩进两字符 */
    data class Paragraph(val text: String) : DocBlock
}

// 章节序号
private val CnSection = Regex("^[一二三四五六七八九十百]+[、.．]")
private val ParenCnSection = Regex("^[（(][一二三四五六七八九十百]+[）)]")
private val NumSection = Regex("^\\d+[、.．]")
private val ParenNumSection = Regex("^[（(]\\d+[）)]")
private val ArticleSection = Regex("^第[一二三四五六七八九十百\\d]+条")

// 成文日期 / 落款单位
private val DateLine = Regex("^.*\\d{4}\\s*年\\s*\\d{1,2}\\s*月\\s*\\d{1,2}\\s*日.*$")
private val OrgLine = Regex("^[^。；;：:]{2,22}(局|委员会|办公室|科|部|厅|处|室|中心|大队|支队|所|院|组)$")

/** 段落收尾标点：以此判断是不是「一段说完了」，用于把 PDF 拆行还原成段落。 */
private val TerminalPunct = charArrayOf('。', '！', '？', '；', '」', '）', ')')

private fun isSection(line: String): Int = when {
    // 一、 / 第一条 → 一级；（一）/ 1. / （1）→ 二级
    CnSection.containsMatchIn(line) || ArticleSection.containsMatchIn(line) -> 1
    ParenCnSection.containsMatchIn(line) || NumSection.containsMatchIn(line)
        || ParenNumSection.containsMatchIn(line) -> 2
    else -> 0
}

/**
 * 是否含 Markdown 语法。
 *
 * 要求至少 2 处命中：公文正文里出现一次「1.」很常见，单次命中就切到
 * Markdown 渲染会把普通条款当成列表，反而更乱。
 */
private fun looksLikeMarkdown(text: String): Boolean {
    var hits = 0
    var scanned = 0
    for (raw in text.lineSequence()) {
        if (++scanned > 80) break
        val s = raw.trim()
        if (s.startsWith("# ") || s.startsWith("## ") || s.startsWith("### ")) hits++
        else if (s.startsWith("- ") || s.startsWith("* ")) hits++
        else if (s.startsWith("> ")) hits++
        else if (s.count { it == '|' } >= 2) hits++
        else if (Regex("\\*\\*.+?\\*\\*").containsMatchIn(s)) hits++
        if (hits >= 2) return true
    }
    return false
}

/**
 * 纯文本 → 版式块。
 *
 * 关键处理是**还原段落**：PDF 抽取常把一段拆成多行，逐行渲染会变成满屏碎行。
 * 规则是「上行没有以句末标点收尾、且下一行不是章节/落款」就并入同一段。
 */
private fun parseBlocks(text: String): List<DocBlock> {
    val lines = text.replace("\r\n", "\n").replace('\r', '\n').split('\n')
    val blocks = mutableListOf<DocBlock>()
    var buf = StringBuilder()
    var titleDone = false

    fun flush() {
        val p = buf.toString().trim()
        buf = StringBuilder()
        if (p.isNotEmpty()) blocks += DocBlock.Paragraph(p)
    }

    for (raw in lines) {
        val line = raw.trim()
        if (line.isEmpty()) {
            flush()
            continue
        }
        val level = isSection(line)
        when {
            level > 0 -> {
                flush()
                blocks += DocBlock.Section(line, level)
                titleDone = true
            }
            DateLine.matches(line) || OrgLine.matches(line) -> {
                flush()
                blocks += DocBlock.SignOff(line)
            }
            // 首行：短且没有句末标点，按公文大标题处理（仅一次）
            !titleDone && line.length <= 40 && line.last() !in TerminalPunct -> {
                flush()
                blocks += DocBlock.Title(line)
                titleDone = true
            }
            else -> {
                if (buf.isNotEmpty()) buf.append(' ')
                buf.append(line)
                // 说完了就断段：否则 PDF 的换行会一路粘到底
                if (line.last() in TerminalPunct) flush()
            }
        }
    }
    flush()
    return blocks
}

/**
 * 文档正文渲染（共享组件）：自动按内容形态选择渲染方式。
 *
 * 背景：知识库文档是从 docx / pdf / ofd 抽取的**纯文本**，不含任何 Markdown 标记。
 * 此前一律交给 [MarkdownView]，等于原样铺一屏纯文本——大标题、条款层级、落款日期
 * 全无区分，用户读起来很费劲。这里先判形态：
 * - 含 Markdown 语法（AI 生成稿、导入的 md）→ 交给 [MarkdownView]；
 * - 纯文本 → 按公文版式推断结构后渲染（章节加粗、落款右对齐、段落首行缩进）。
 *
 * 凡是「给用户看成稿/看原文」的位置都应改用它而不是直接 MarkdownView。
 */
@Composable
fun DocumentBodyView(text: String, modifier: Modifier = Modifier) {
    if (looksLikeMarkdown(text)) {
        MarkdownView(text, modifier)
        return
    }

    val blocks = parseBlocks(text)
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        blocks.forEach { block ->
            when (block) {
                is DocBlock.Title -> Text(
                    block.text,
                    modifier = Modifier.fillMaxWidth().padding(top = 2.dp, bottom = 10.dp),
                    fontSize = 17.sp, fontWeight = FontWeight.Bold, color = Ink,
                    lineHeight = 26.sp, textAlign = TextAlign.Center,
                )

                is DocBlock.Section -> {
                    Spacer(Modifier.height(if (block.level == 1) 10.dp else 6.dp))
                    Text(
                        block.text,
                        modifier = Modifier.fillMaxWidth()
                            // 二级序号缩进两字符，与正文首行对齐
                            .padding(start = if (block.level == 1) 0.dp else 28.dp),
                        fontSize = if (block.level == 1) 15.5.sp else 14.5.sp,
                        fontWeight = FontWeight.SemiBold, color = Ink,
                        lineHeight = 25.sp,
                    )
                }

                is DocBlock.SignOff -> Text(
                    block.text,
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp, end = 4.dp),
                    fontSize = 13.5.sp, color = Ink2, lineHeight = 21.sp,
                    textAlign = TextAlign.End,
                )

                is DocBlock.Paragraph -> Text(
                    block.text,
                    modifier = Modifier.fillMaxWidth().padding(start = 28.dp),
                    fontSize = 14.5.sp, color = Ink, lineHeight = 26.sp,
                )
            }
        }
    }
}

/**
 * 文档正文的「页宽」副本：纯文本行极长时给出一行水平滚动的兜底说明。
 * 正常公文不会触发；抽取异常（整篇挤成一行）时给个可见提示而不是静默截断。
 */
@Composable
fun DocumentBodyOverflowHint(text: String) {
    val longest = text.lineSequence().maxOfOrNull { it.length } ?: 0
    if (longest > 200) {
        Text(
            "该文档正文未识别出段落（最长一行 $longest 字），可能是扫描件或抽取异常",
            fontSize = 11.sp, color = TextSecondary, modifier = Modifier.padding(top = 4.dp),
        )
    }
}
