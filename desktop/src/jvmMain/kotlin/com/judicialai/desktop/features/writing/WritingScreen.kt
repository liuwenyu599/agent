package com.judicialai.desktop.features.writing

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Checkbox
import androidx.compose.material.Icon
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Switch
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.material.TextFieldDefaults
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.UploadFile
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.ParagraphStyle
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextIndent
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.platform.pickFiles
import com.judicialai.desktop.core.platform.pickSaveFile
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.components.AiActionChip
import com.judicialai.desktop.design.components.AiBubble
import com.judicialai.desktop.design.components.AiWorkingRow
import com.judicialai.desktop.design.components.AppButton
import com.judicialai.desktop.design.components.AppButtonKind
import com.judicialai.desktop.design.components.AppButtonSize
import com.judicialai.desktop.design.components.AppDialog
import com.judicialai.desktop.design.components.AppIconButton
import com.judicialai.desktop.design.components.AppLinkButton
import com.judicialai.desktop.design.components.AppSegmentedTabs
import com.judicialai.desktop.design.components.ContextBlock
import com.judicialai.desktop.design.components.ContextSources
import com.judicialai.desktop.design.components.DocumentStatusBar
import com.judicialai.desktop.design.components.DocumentSurface
import com.judicialai.desktop.design.components.EmptyState
import com.judicialai.desktop.design.components.Eyebrow
import com.judicialai.desktop.design.components.FieldError
import com.judicialai.desktop.design.components.Hairline
import com.judicialai.desktop.design.components.SectionTitle
import com.judicialai.desktop.design.components.TagChip
import com.judicialai.desktop.design.theme.AiIndigo
import com.judicialai.desktop.design.theme.AiSoft
import com.judicialai.desktop.design.theme.AiSoftStrong
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.EmeraldInk
import com.judicialai.desktop.design.theme.EmeraldSoft
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.LineSubtle
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Muted2
import com.judicialai.desktop.design.theme.OnPrimaryText
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.PrimarySoft
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.SurfaceTonal
import com.judicialai.desktop.design.theme.Warn
import com.judicialai.desktop.design.theme.WarnSoft
import com.judicialai.desktop.design.theme.FeatureWriteEnd
import com.judicialai.desktop.design.theme.FeatureWriteStart
import com.judicialai.desktop.features.knowledge.KnowledgeDocDialog
import kotlinx.serialization.json.JsonObject

private const val Pending = "待补充"

/**
 * 智能写作（v4.0）
 *
 * 三段式：一句话入口 → AI 规划本次写作环境 → 三栏工作台。
 * 左栏是「任务上下文」（任务卡可人工修订 + 材料 + 可依据资料 + 模板），不是只读参数表；
 * 中栏是真正的文档工作台；右栏是 AI 助手（正在做什么 / 建议操作 / 对话 / 引用资料）。
 * 界面不出现「全局公共知识库」「本科室知识库」这类系统实现语言。
 *
 * 模板中心「使用模板 → 生成」也会进入本工作台：
 * 携带模板绑定与已填要素，创建任务后自动起草。
 */
@Composable
fun WritingScreen() {
    val vm = remember { WritingViewModel(Repositories.writing, Repositories.knowledge) }

    // ---- 跨页面恢复 ----
    // 切走再切回时 remember 会重建 ViewModel（状态清零），但生成协程不会被取消，
    // 任务仍在服务端。这里读取全局任务 id：本地还没有任务就按 id 从服务端取回。
    // 读取发生在组合内，id 一旦写入（可能是离开页面之后才创建成功）就会触发重组并自动恢复。
    val pendingTaskId = AppState.pendingWritingTaskId
    LaunchedEffect(pendingTaskId) {
        // 模板中心「使用模板」/ 聊天跳转写作带来的一次性参数优先：
        // 此时不恢复旧任务，否则本恢复请求先占用 busy，会把这次新任务挤掉。
        val jumping = AppState.pendingWritingTemplate != null || AppState.pendingWritingIntent != null
        if (!jumping && pendingTaskId != null && !vm.hasTask) vm.openTask(pendingTaskId)
    }
    // 页面未被销毁（ViewModel 还活着、任务还开着）时，模板中心再次「生成」：
    // 入口页不会重新组合，无法消费这次跳转参数，由这里直接按「开新任务」处理——
    // startFromTemplate 内部会先清理旧任务，杜绝上一个任务的内容串进新任务。
    val pendingTemplate = AppState.pendingWritingTemplate
    LaunchedEffect(pendingTemplate) {
        if (pendingTemplate != null && vm.hasTask) {
            AppState.pendingWritingTemplate = null
            AppState.pendingWritingIntent = null
            vm.startFromTemplate(pendingTemplate)
        }
    }
    // 生成由「进行中」变为「结束」时刷新一次：起草可能是在离开页面之后才跑完的，
    // 那时恢复到的还是生成前的内容。用状态流转触发，不用定时器，离开组合即取消。
    LaunchedEffect(vm) {
        var wasGenerating = AppState.writingGenerating
        snapshotFlow { AppState.writingGenerating }.collect { now ->
            if (wasGenerating && !now) vm.refreshTask()
            wasGenerating = now
        }
    }

    // 上次生成失败提示（失败可能发生在切到别的页面期间，那时本地 status 已随 ViewModel 一起丢失）。
    // 入口页与已恢复的工作台都要显示：工作台靠 openTask 恢复出来的是生成前状态（可能空正文），
    // 不说明的话用户只看到「还没有正文」，同样以为生成丢了。
    val lastError = AppState.writingLastError
    val generating = AppState.writingGenerating

    Column(Modifier.fillMaxSize().background(AppBg)) {
        if (lastError != null && !generating) {
            WritingFailedBanner(lastError) { AppState.writingLastError = null }
        }
        // 切回页面后正在从服务端取回任务：明确说明在做什么，别让人以为卡住/报错
        if (vm.restoring) {
            WritingProgressLine("正在取回上次未完成的写作任务…")
        }
        Box(Modifier.weight(1f).fillMaxWidth()) {
            if (!vm.hasTask) {
                TaskEntryScreen(vm)
            } else {
                Row(
                    Modifier.fillMaxSize().padding(Dimens.space4),
                    horizontalArrangement = Arrangement.spacedBy(Dimens.space4),
                ) {
                    if (vm.spec != null) {
                        SpecPanel(vm, Modifier.width(300.dp).fillMaxHeight())
                    } else {
                        TaskPanel(vm, Modifier.width(300.dp).fillMaxHeight())
                    }
                    EditorPanel(vm, Modifier.weight(1f).fillMaxHeight())
                    AssistantPanel(vm, Modifier.width(330.dp).fillMaxHeight())
                }
            }
        }
    }

    // 历史版本预览 / 回退弹窗
    vm.versionPreview?.let { v -> VersionPreviewDialog(vm, v) }

    // 参考材料（知识库文档）查看 / 编辑弹窗
    if (vm.docDialogId != null) {
        KnowledgeDocDialog(
            title = vm.docDialogTitle,
            content = vm.docDialogContent,
            busy = vm.docDialogBusy,
            onTitleChange = { vm.docDialogTitle = it },
            onContentChange = { vm.docDialogContent = it },
            onSave = { vm.saveDocument() },
            onClose = { vm.closeDocument() },
        )
    }

    // 图片识别结果弹窗（视觉模型识别文本，可查看 / 一键插入正文）
    if (vm.imageResults.isNotEmpty()) {
        ImageRecognizeDialog(vm)
    }
}

/**
 * 上次生成失败提示条：失败发生在切到别的页面期间时，本地 ViewModel 已被重建、
 * status 丢失，只有全局记录还在。给一个关闭按钮，用户确认后不必一直挂着。
 */
@Composable
private fun WritingFailedBanner(message: String, onDismiss: () -> Unit) {
    Row(
        Modifier.fillMaxWidth()
            .background(WarnSoft)
            .padding(horizontal = Dimens.space5, vertical = Dimens.space3),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("上次生成未完成：$message", fontSize = 12.5.sp, color = Warn,
            lineHeight = 18.sp, modifier = Modifier.weight(1f))
        Spacer(Modifier.width(Dimens.space2))
        TextButton(onClick = onDismiss) { Text("知道了", fontSize = 12.sp, color = Warn) }
    }
}

/** 历史版本预览：带格式渲染全文，可回退（回退前当前内容由后端自动保存为新版本） */
@Composable
private fun VersionPreviewDialog(vm: WritingViewModel, v: JsonObject) {
    val no = v["version_no"].int()
    val note = v["note"].str().ifBlank { "自动保存" }
    val body = v["content"].str()
    AppDialog(
        onDismissRequest = { vm.closeVersionPreview() },
        title = "历史版本 v$no",
        subtitle = "$note · 约 ${body.length} 字 · 回退不会丢失当前内容（自动保存为新版本）",
        width = 640.dp,
        actions = {
            AppButton("关闭", onClick = { vm.closeVersionPreview() },
                kind = AppButtonKind.SECONDARY)
            Spacer(Modifier.width(Dimens.space2))
            AppButton(if (vm.busy) "回退中…" else "回退到此版本",
                onClick = { vm.restoreVersion(no) },
                enabled = !vm.busy && body.isNotBlank())
        },
    ) {
        if (body.isBlank()) {
            Text("（该版本无正文内容）", fontSize = 13.sp, color = Muted)
        } else {
            MarkdownText(body)
        }
    }
}

/** 图片识别结果弹窗：逐张展示视觉模型识别出的文字，可一键插入正文末尾 */
@Composable
private fun ImageRecognizeDialog(vm: WritingViewModel) {
    AppDialog(
        onDismissRequest = { vm.dismissImageResults() },
        title = "图片识别结果",
        subtitle = "识别文本已作为材料绑定本次写作，起草/修改时自动参考；也可插入正文",
        width = 640.dp,
        actions = {
            AppButton("关闭", onClick = { vm.dismissImageResults() },
                kind = AppButtonKind.SECONDARY)
        },
    ) {
        // AppDialog 内容区本身可滚动，这里直接平铺，不再嵌套 verticalScroll
        vm.imageResults.forEach { item ->
            Column(
                Modifier.fillMaxWidth()
                    .clip(RoundedCornerShape(Dimens.radiusMd))
                    .background(SurfaceTonal)
                    .padding(Dimens.space3),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(item.filename, fontSize = 12.5.sp, fontWeight = FontWeight.SemiBold,
                        color = Ink, modifier = Modifier.weight(1f), maxLines = 1,
                        overflow = TextOverflow.Ellipsis)
                    if (item.text.isNotBlank()) {
                        // 必须用命名参数：AppLinkButton 的最后一个位置参数是 icon: ImageVector?，
                        // 尾随 lambda 会被分配给它而不是 onClick，导致编译失败
                        AppLinkButton("插入正文末尾", onClick = { vm.insertImageText(item) })
                    }
                }
                if (item.note.isNotBlank()) {
                    Text(item.note, fontSize = 11.sp, color = Muted)
                }
                Spacer(Modifier.height(Dimens.space1))
                if (item.text.isBlank()) {
                    Text("（未识别到文字内容）", fontSize = 12.sp, color = Muted)
                } else {
                    Text(item.text, fontSize = 12.5.sp, color = Ink2, lineHeight = 19.sp)
                }
            }
        }
    }
}

/** 左栏「上传图片识别」按钮（SpecPanel / TaskPanel 共用） */
@Composable
private fun UploadImageRecognizeButton(vm: WritingViewModel) {
    AppButton(
        if (vm.recognizingImages) "识别中…" else "上传图片识别",
        onClick = { vm.recognizeImages(pickFiles("选择要识别的图片", multi = true)) },
        kind = AppButtonKind.SECONDARY, icon = Icons.Default.UploadFile, fill = true,
        enabled = !vm.busy && !vm.recognizingImages,
    )
}

// ---------------- 公文格式渲染与分块编辑 ----------------

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

private val OrderedListRegex = Regex("^\\d+\\.\\s+.*")

/**
 * 公文结构行识别：AI 输出经常是纯文本（不带 # 标记），
 * 「一、」「（一）」这类公文层级标题也要按标题样式渲染，
 * 否则整篇都是同一种字重，格式变化完全看不出来。
 */
private val GwHeading1Regex = Regex("^[一二三四五六七八九十百]+、[^。；，]{2,60}$")
private val GwHeading2Regex = Regex("^（[一二三四五六七八九十]+）[^。；，]{2,60}$")

/** 正文段首缩进两字符（14.5sp 正文 ≈ 29sp），即「段前空格」的视觉效果 */
private val BodyParagraphStyle = ParagraphStyle(
    textIndent = TextIndent(firstLine = 29.sp, restLine = 0.sp),
)

/**
 * 单行公文格式渲染：markdown 标题 / 公文层级标题 / 列表 / 分割线 / 表格行 /
 * 普通段落（段首缩进两字符 + 行内粗体）。预览与分块编辑共用这一套。
 */
@Composable
private fun FormattedLine(raw: String) {
    val s = raw.trim()
    when {
        s.isBlank() -> Spacer(Modifier.height(6.dp))
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
        GwHeading1Regex.matches(s) -> Text(
            inlineMd(s), fontSize = 15.5.sp, fontWeight = FontWeight.Bold,
            color = Ink, lineHeight = 26.sp)
        GwHeading2Regex.matches(s) -> Text(
            inlineMd(s), fontSize = 14.5.sp, fontWeight = FontWeight.SemiBold,
            color = Ink, lineHeight = 25.sp)
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
        s.startsWith("|") -> Text(s, fontSize = 12.5.sp, color = Ink2,
            lineHeight = 20.sp)
        else -> Text(
            inlineMd(s),
            style = androidx.compose.ui.text.TextStyle(
                fontSize = 14.5.sp, color = Ink, lineHeight = 26.sp,
                paragraphStyle = BodyParagraphStyle,
            ),
        )
    }
}

/**
 * 公文 Markdown 轻量渲染：标题（# / ## / ###）、公文层级行（一、/（一））、
 * 无序/有序列表、分割线、粗体、正文段首缩进。
 * 用于历史版本预览，让正文以带格式的方式呈现而不是裸 txt。
 */
@Composable
private fun MarkdownText(text: String) {
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        text.split('\n').forEach { line -> FormattedLine(line) }
    }
}

/**
 * 所见即所得正文编辑：
 * 每行一个块，按公文格式渲染（标题居中/加粗、正文段首缩进两字符、**粗体** 生效）；
 * 点击任意段落就地进入编辑（框内支持多行，一次可拆成多段），点「完成」写回正文，
 * 格式变化立刻可见，不再需要切到「预览」才能看到加粗/缩进效果。
 * 清空段落内容再点「完成」= 删除该段。
 */
@Composable
private fun FormattedBodyEditor(vm: WritingViewModel) {
    var editIdx by remember { mutableStateOf<Int?>(null) }
    var editText by remember { mutableStateOf("") }

    fun commit() {
        val i = editIdx ?: return
        val cur = vm.content.split('\n').toMutableList()
        if (i < cur.size) {
            cur.removeAt(i)
            if (editText.isNotBlank()) {
                cur.addAll(i.coerceAtMost(cur.size), editText.split('\n'))
            }
            vm.content = cur.joinToString("\n")
        }
        editIdx = null
    }

    Column(Modifier.fillMaxWidth()) {
        val lines = vm.content.split('\n')
        lines.forEachIndexed { i, raw ->
            if (editIdx == i) {
                Column(
                    Modifier.fillMaxWidth()
                        .clip(RoundedCornerShape(Dimens.radiusSm))
                        .border(1.dp, Primary, RoundedCornerShape(Dimens.radiusSm))
                        .padding(Dimens.space2),
                ) {
                    OutlinedTextField(
                        value = editText,
                        onValueChange = { editText = it },
                        modifier = Modifier.fillMaxWidth(),
                        textStyle = androidx.compose.ui.text.TextStyle(
                            fontSize = 14.5.sp, color = Ink, lineHeight = 24.sp),
                        shape = RoundedCornerShape(Dimens.radiusXs),
                        colors = TextFieldDefaults.outlinedTextFieldColors(
                            backgroundColor = SurfaceTonal,
                            focusedBorderColor = Color.Transparent,
                            unfocusedBorderColor = Color.Transparent,
                            cursorColor = Primary),
                    )
                    Row(
                        Modifier.fillMaxWidth().padding(top = 2.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("清空后点完成 = 删除此段；用 **文字** 可加粗",
                            fontSize = 10.5.sp, color = Muted2)
                        Spacer(Modifier.weight(1f))
                        AppLinkButton("取消", onClick = { editIdx = null })
                        Spacer(Modifier.width(Dimens.space3))
                        AppLinkButton("完成", onClick = { commit() })
                    }
                }
            } else {
                Box(
                    Modifier.fillMaxWidth()
                        .clip(RoundedCornerShape(Dimens.radiusXs))
                        .clickable(enabled = !vm.busy) {
                            editIdx = i
                            editText = raw
                        }
                        .padding(horizontal = 4.dp, vertical = 1.dp),
                ) {
                    FormattedLine(raw)
                }
            }
        }
        if (vm.content.isBlank()) {
            Text("（正文为空，生成初稿后可在此直接修改）", fontSize = 13.sp, color = Muted)
        }
    }
}
