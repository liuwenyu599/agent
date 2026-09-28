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

    // 参考材料（知识库文档）只读查看：写作工作台不能顺手改动知识源
    if (vm.docDialogId != null) {
        KnowledgeDocDialog(
            title = vm.docDialogTitle,
            content = vm.docDialogContent,
            busy = vm.docDialogBusy,
            editable = false,
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
                textIndent = TextIndent(firstLine = 29.sp, restLine = 0.sp),
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

// ---------------- 零门槛入口 ----------------

@Composable
private fun TaskEntryScreen(vm: WritingViewModel) {
    androidx.compose.runtime.LaunchedEffect(Unit) {
        // 模板中心「使用模板 → 生成」：创建绑定模板的任务并自动起草
        AppState.pendingWritingTemplate?.let { p ->
            AppState.pendingWritingTemplate = null
            // 一次性跳转参数互斥：聊天页残留的写作意图一并作废，
            // 防止它稍后被当成新任务需求再次启动（上下文串话来源之一）
            AppState.pendingWritingIntent = null
            vm.startFromTemplate(p)
            return@LaunchedEffect
        }
        AppState.pendingWritingIntent?.let {
            vm.entryInput = it
            AppState.pendingWritingIntent = null
            vm.planAndStart()
        }
    }

    // 内容整体垂直居中：桌面竖向空间不被浪费成底部空白；
    // 不写死 fillMaxHeight，避免内容不足时全部堆在顶部
    Box(Modifier.fillMaxSize().background(AppBg), contentAlignment = Alignment.Center) {
        Column(
            Modifier.widthInMaxEntry()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = Dimens.space8, vertical = Dimens.space7),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            // 品牌化的写作主视觉：低饱和靛蓝渐变，不做满屏渐变
            EntryHero()

            Spacer(Modifier.height(Dimens.space6))

            // 输入卡
            Column(
                Modifier.fillMaxWidth()
                    .clip(RoundedCornerShape(Dimens.radiusXl))
                    .background(Surface)
                    .border(1.dp, LineSubtle, RoundedCornerShape(Dimens.radiusXl))
                    .padding(Dimens.space5),
            ) {
                OutlinedTextField(
                    value = vm.entryInput,
                    onValueChange = { vm.entryInput = it },
                    placeholder = { Text("用一句话描述这次写作任务，例如：根据本月工作材料撰写报送区政府的工作情况报告",
                        fontSize = 13.5.sp, color = Muted2) },
                    modifier = Modifier.fillMaxWidth().height(110.dp),
                    enabled = !vm.busy,
                    maxLines = 4,
                    shape = RoundedCornerShape(Dimens.radiusControl),
                    textStyle = androidx.compose.ui.text.TextStyle(fontSize = 14.sp, color = Ink),
                    colors = TextFieldDefaults.outlinedTextFieldColors(
                        backgroundColor = SurfaceTonal,
                        focusedBorderColor = Primary,
                        unfocusedBorderColor = Line,
                        cursorColor = Primary,
                    ),
                )
                Spacer(Modifier.height(Dimens.space3))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.AutoAwesome, null, tint = AiIndigo,
                            modifier = Modifier.size(Dimens.iconSm))
                        Spacer(Modifier.width(Dimens.space2))
                        Text("文种、材料、可依据资料与模板由我自动组织",
                            fontSize = 12.sp, color = Muted, lineHeight = 18.sp)
                    }
                    Spacer(Modifier.width(Dimens.space3))
                    AppButton(
                        text = if (vm.planning) "规划中…" else "开始写作",
                        onClick = { vm.planAndStart() },
                        kind = AppButtonKind.AI,
                        size = AppButtonSize.LG,
                        enabled = !vm.busy && vm.entryInput.isNotBlank(),
                        loading = vm.planning,
                        icon = Icons.Default.AutoAwesome,
                    )
                }
            }

            if (vm.planning) {
                Spacer(Modifier.height(Dimens.space5))
                Column(
                    Modifier.fillMaxWidth()
                        .clip(RoundedCornerShape(Dimens.radiusLg))
                        .background(AiSoft)
                        .border(1.dp, AiSoftStrong, RoundedCornerShape(Dimens.radiusLg))
                        .padding(Dimens.space5),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.AutoAwesome, null, tint = AiIndigo,
                            modifier = Modifier.size(Dimens.iconMd))
                        Spacer(Modifier.width(Dimens.space2))
                        Text("我正在准备本次写作", fontSize = 13.5.sp,
                            fontWeight = FontWeight.SemiBold, color = Ink)
                    }
                    Spacer(Modifier.height(Dimens.space3))
                    listOf(
                        "理解任务语义与写作目标",
                        "识别文种、报送对象与使用场景",
                        "匹配可参考材料与知识来源（受科室权限约束）",
                        "确定模板并组织左栏任务上下文",
                    ).forEachIndexed { i, s ->
                        Row(Modifier.padding(vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Box(
                                Modifier.size(18.dp).clip(RoundedCornerShape(Dimens.radiusXs))
                                    .background(Surface),
                                contentAlignment = Alignment.Center,
                            ) {
                                Text("${i + 1}", fontSize = 10.5.sp, color = AiIndigo,
                                    fontWeight = FontWeight.SemiBold)
                            }
                            Spacer(Modifier.width(Dimens.space2))
                            Text(s, fontSize = 12.5.sp, color = Ink2)
                        }
                    }
                    Spacer(Modifier.height(Dimens.space2))
                    AppLinkButton("取消本次生成", onClick = { vm.cancelGeneration() })
                }
            }

            vm.planError?.let {
                Spacer(Modifier.height(Dimens.space4))
                Column(
                    Modifier.fillMaxWidth()
                        .clip(RoundedCornerShape(Dimens.radiusMd))
                        .background(WarnSoft)
                        .padding(Dimens.space4),
                ) {
                    Text("任务规划不可用：$it", fontSize = 12.5.sp, color = Warn)
                    Spacer(Modifier.height(Dimens.space2))
                    AppLinkButton("不规划，直接开始写作", onClick = { vm.startWithoutPlan() })
                }
            }

            // 还没拿到 task_id 就切回来了（任务仍在创建中）：明确说明仍在处理，
            // 不要呈现一个空白入口让人以为任务丢了
            if (AppState.writingGenerating && !vm.planning) {
                Spacer(Modifier.height(Dimens.space4))
                Column(
                    Modifier.fillMaxWidth()
                        .clip(RoundedCornerShape(Dimens.radiusMd))
                        .background(AiSoft)
                        .padding(Dimens.space4),
                ) {
                    Text("上一次启动的写作任务仍在准备中，完成后会自动回到工作台。",
                        fontSize = 12.5.sp, color = Ink2, lineHeight = 18.sp)
                }
            }

            // 恢复中的中性提示由外层统一渲染（工作台与入口页都要看到），这里只出结果
            WritingStatusLine(vm.status)
            Spacer(Modifier.height(Dimens.space6))
        }
    }
}

private fun Modifier.widthInMaxEntry(): Modifier = this.widthIn(max = 900.dp)

@Composable
private fun EntryHero() {
    val shape = RoundedCornerShape(Dimens.radiusXl)
    Box(
        Modifier.fillMaxWidth().clip(shape)
            .background(Brush.linearGradient(listOf(FeatureWriteStart, FeatureWriteEnd))),
    ) {
        Column(Modifier.fillMaxWidth().padding(Dimens.space6)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier.size(34.dp).clip(RoundedCornerShape(Dimens.radiusMd))
                        .background(Color.White.copy(alpha = 0.14f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(Icons.Default.AutoAwesome, null, tint = OnPrimaryText,
                        modifier = Modifier.size(Dimens.iconMd))
                }
                Spacer(Modifier.width(Dimens.space3))
                Column {
                    Text("智能写作", fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
                        color = OnPrimaryText)
                    Text("${AppState.displayName}，今天你想完成什么写作任务？",
                        fontSize = 12.5.sp, color = Color.White.copy(alpha = 0.72f))
                }
            }
        }
    }
}

// ---------------- 左栏：任务上下文 ----------------

@Composable
private fun SpecPanel(vm: WritingViewModel, modifier: Modifier) {
    val spec = vm.spec ?: return
    val deptName = AppState.departmentName
    Column(
        modifier.fillMaxHeight()
            .clip(RoundedCornerShape(Dimens.radiusLg))
            .background(Surface)
            .border(1.dp, LineSubtle, RoundedCornerShape(Dimens.radiusLg))
            .padding(Dimens.space4)
            .verticalScroll(rememberScrollState()),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Eyebrow("任务上下文")
                Text("本次写作", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                if (spec.agent.isNotBlank()) {
                    Spacer(Modifier.height(2.dp))
                    Text(spec.agent, fontSize = 11.5.sp, color = Muted,
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            AppLinkButton("重新描述", onClick = { vm.backToEntry() })
        }

        Spacer(Modifier.height(Dimens.space4))

        // 任务卡：AI 规划结果可人工修订（改后点 ✓ 同步后端，对下次「继续生成」生效）
        ContextBlock(title = "任务要点（可修改）", icon = Icons.Default.Description, tint = Primary) {
            TaskField("文种", spec.docType) { v -> vm.patchSpecField("文种", v) }
            TaskField("报送对象", spec.audience) { v -> vm.patchSpecField("报送对象", v) }
            TaskField("写作目标", spec.target) { v -> vm.patchSpecField("写作目标", v) }
            spec.fields.filter { it.label !in setOf("文种", "报送对象", "写作目标") }
                .forEach { f -> TaskField(f.label, f.value) { v -> vm.patchSpecField(f.label, v) } }
        }

        // 参考材料：可勾选，也可直接查看/编辑知识库原文
        if (spec.materials.isNotEmpty()) {
            Spacer(Modifier.height(Dimens.space3))
            ContextBlock(title = "参考材料（${spec.materials.count { it.selected }}）") {
                spec.materials.forEach { opt ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clickable(enabled = opt.note.isBlank()) { vm.toggleMaterial(opt) }
                            .padding(vertical = 3.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Checkbox(checked = opt.selected,
                            onCheckedChange = { if (opt.note.isBlank()) vm.toggleMaterial(opt) },
                            modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(Dimens.space2))
                        Text(opt.label, fontSize = 12.5.sp, color = Ink,
                            modifier = Modifier.weight(1f), maxLines = 1,
                            overflow = TextOverflow.Ellipsis)
                        if (opt.note.isNotBlank()) {
                            TagChip(opt.note, fg = Warn, bg = WarnSoft)
                        } else if (opt.id.isNotBlank()) {
                            Spacer(Modifier.width(Dimens.space1))
                            Text("查看", fontSize = 11.5.sp, color = Primary,
                                modifier = Modifier
                                    .clip(RoundedCornerShape(Dimens.radiusXs))
                                    .clickable { vm.openDocument(opt.id) }
                                    .padding(horizontal = 4.dp, vertical = 1.dp))
                        }
                    }
                }
            }
        }

        // 可依据资料：用「已参考 N 项相关资料 / 来自本科室业务知识」表达
        if (spec.knowledge.isNotEmpty()) {
            Spacer(Modifier.height(Dimens.space3))
            val selected = spec.knowledge.filter { it.selected }
            ContextSources(
                summary = if (selected.isEmpty()) "未选择可依据资料"
                else "本次写作已参考 ${selected.size} 项相关资料",
                sources = spec.knowledge.map {
                    it.label + friendlySource(it.note, deptName).let { s ->
                        if (s.isBlank()) "" else " · $s"
                    }
                },
            )
        }

        // 模板
        if (spec.templateName.isNotBlank()) {
            Spacer(Modifier.height(Dimens.space3))
            ContextBlock(title = "使用模板") {
                Row(
                    Modifier.fillMaxWidth()
                        .clip(RoundedCornerShape(Dimens.radiusSm))
                        .background(SurfaceTonal)
                        .clickable { AppState.navigate(AppScreen.TEMPLATES) }
                        .padding(horizontal = 10.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(spec.templateName, fontSize = 12.5.sp, color = Ink,
                        modifier = Modifier.weight(1f), maxLines = 1,
                        overflow = TextOverflow.Ellipsis)
                    Text("切换", fontSize = 11.5.sp, color = Primary)
                }
                if (spec.source == "template") {
                    Spacer(Modifier.height(Dimens.space1))
                    AppLinkButton("返回模板重新填写要素", onClick = { vm.returnToTemplate() })
                }
            }
        }

        if (spec.source == "rule") {
            Spacer(Modifier.height(Dimens.space3))
            FieldError("智能规划暂时不可用，已为你生成基础结构；可继续编辑或稍后重试")
        }

        Spacer(Modifier.height(Dimens.space4))
        AppButton("上传材料", onClick = {
            vm.uploadMaterials(pickFiles("选择写作材料", multi = true))
        }, kind = AppButtonKind.SECONDARY, icon = Icons.Default.UploadFile, fill = true)
        Spacer(Modifier.height(Dimens.space2))
        UploadImageRecognizeButton(vm)
        if (vm.materials.isNotEmpty()) {
            Spacer(Modifier.height(Dimens.space2))
            vm.materials.forEach { a ->
                Text("· ${a.name}", fontSize = 11.5.sp, color = Muted, maxLines = 1,
                    overflow = TextOverflow.Ellipsis)
            }
        }
        if (!vm.hasDraft) {
            Spacer(Modifier.height(Dimens.space2))
            AppButton("生成初稿", onClick = { vm.draft() }, kind = AppButtonKind.AI,
                enabled = !vm.busy, loading = vm.busy, fill = true)
        } else {
            Spacer(Modifier.height(Dimens.space2))
            AppButton("继续生成（按当前参数再出一版）", onClick = { vm.draft() },
                kind = AppButtonKind.AI, enabled = !vm.busy, loading = vm.busy,
                icon = Icons.Default.Refresh, fill = true)
            Spacer(Modifier.height(Dimens.space1))
            Text("每次生成自动保存为新版本，旧版本可在右侧「依据 → 历史版本」查看/回退",
                fontSize = 11.sp, color = Muted, lineHeight = 16.sp)
        }
        if (vm.busy) {
            Spacer(Modifier.height(Dimens.space2))
            AppButton("取消生成", onClick = { vm.cancelGeneration() },
                kind = AppButtonKind.DANGER, fill = true)
        }
    }
}

@Composable
private fun SpecFact(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.Top) {
        Text(label, fontSize = 11.5.sp, color = Muted, modifier = Modifier.width(72.dp))
        Text(value, fontSize = 12.5.sp, color = if (value == Pending) Muted2 else Ink,
            modifier = Modifier.weight(1f), maxLines = 2, overflow = TextOverflow.Ellipsis,
            lineHeight = 18.sp)
    }
}

/** 把系统实现语言翻译成用户语言：全局公共知识库 → 公共资料，本科室知识库 → 本科室业务知识 */
private fun friendlySource(note: String, deptName: String): String = when {
    note.contains("个人") -> "我的资料"
    note.contains("本科室") || note.contains("科室") ->
        "${deptName.ifBlank { "本科室" }}业务知识"
    note.contains("公共") || note.contains("全局") -> "公共资料"
    else -> note
}

@Composable
private fun TaskPanel(vm: WritingViewModel, modifier: Modifier) {
    Column(
        modifier.fillMaxHeight()
            .clip(RoundedCornerShape(Dimens.radiusLg))
            .background(Surface)
            .border(1.dp, LineSubtle, RoundedCornerShape(Dimens.radiusLg))
            .padding(Dimens.space4)
            .verticalScroll(rememberScrollState()),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Eyebrow("任务上下文")
                Text("写作任务", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Ink)
            }
            AppLinkButton("新建任务", onClick = { vm.newTask() })
        }
        Spacer(Modifier.height(Dimens.space4))

        ContextBlock(title = "任务要点", icon = Icons.Default.Description) {
            TaskField("文种", vm.task.documentType) { v -> vm.patchContext(mapOf("document_type" to v)) }
            TaskField("标题", vm.task.title) { v -> vm.patchContext(mapOf("title" to v)) }
            TaskField("主题", vm.task.topic) { v -> vm.patchContext(mapOf("topic" to v)) }
            TaskField("时间", vm.task.timeRange) { v -> vm.patchContext(mapOf("time_range" to v)) }
            TaskField("主送机关", vm.task.recipient) { v -> vm.patchContext(mapOf("recipient" to v)) }
            TaskField("发文机关", vm.task.authority) { v -> vm.patchContext(mapOf("authority" to v)) }
            if (vm.task.keyFacts.isNotEmpty()) {
                SpecFact("主要工作", vm.task.keyFacts.joinToString("、"))
            }
        }

        Spacer(Modifier.height(Dimens.space3))
        ContextBlock(title = "文号") {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(checked = vm.task.documentNumberEnabled,
                    onCheckedChange = { vm.toggleDocNumber(it) })
                Spacer(Modifier.width(Dimens.space2))
                Text(if (vm.task.documentNumberEnabled) "启用（手工填写，系统不编造）" else "不使用",
                    fontSize = 12.sp, color = Ink2)
            }
            if (vm.task.documentNumberEnabled) {
                Spacer(Modifier.height(Dimens.space2))
                OutlinedTextField(
                    vm.task.documentNumber, { vm.setDocNumber(it) },
                    modifier = Modifier.fillMaxWidth().heightIn(min = Dimens.hControl),
                    singleLine = true,
                    shape = RoundedCornerShape(Dimens.radiusControl),
                    textStyle = androidx.compose.ui.text.TextStyle(fontSize = 13.sp, color = Ink),
                    colors = TextFieldDefaults.outlinedTextFieldColors(
                        backgroundColor = SurfaceTonal, focusedBorderColor = Primary,
                        unfocusedBorderColor = Line, cursorColor = Primary),
                )
            }
            if (vm.task.documentDate.isNotBlank()) {
                Spacer(Modifier.height(Dimens.space2))
                SpecFact("成文日期", vm.task.documentDate)
            }
        }

        if (vm.task.missingFields.isNotEmpty()) {
            Spacer(Modifier.height(Dimens.space3))
            ContextBlock(title = "还需要的信息", tint = Warn) {
                vm.task.missingFields.forEach {
                    Text("· $it", fontSize = 12.sp, color = Warn, lineHeight = 18.sp)
                }
            }
        }

        Spacer(Modifier.height(Dimens.space3))
        AppButton("上传材料", onClick = {
            vm.uploadMaterials(pickFiles("选择写作材料", multi = true))
        }, kind = AppButtonKind.SECONDARY, icon = Icons.Default.UploadFile, fill = true)
        Spacer(Modifier.height(Dimens.space2))
        UploadImageRecognizeButton(vm)
        if (vm.materials.isEmpty()) {
            Spacer(Modifier.height(Dimens.space1))
            Text("未上传材料（可先起草，随时补充）", fontSize = 11.5.sp, color = Muted)
        } else {
            Spacer(Modifier.height(Dimens.space2))
            vm.materials.forEach { a ->
                Text("· ${a.name}", fontSize = 11.5.sp, color = Muted, maxLines = 1,
                    overflow = TextOverflow.Ellipsis)
            }
        }

        if (!vm.hasDraft) {
            Spacer(Modifier.height(Dimens.space2))
            AppButton("生成初稿", onClick = { vm.draft() }, kind = AppButtonKind.AI,
                enabled = !vm.busy, loading = vm.busy, fill = true)
            Spacer(Modifier.height(Dimens.space2))
            AppButton("先搭框架", onClick = { vm.draft(outlineOnly = true) },
                kind = AppButtonKind.SECONDARY, enabled = !vm.busy, fill = true)
        } else {
            Spacer(Modifier.height(Dimens.space2))
            AppButton("继续生成（按当前参数再出一版）", onClick = { vm.draft() },
                kind = AppButtonKind.AI, enabled = !vm.busy, loading = vm.busy,
                icon = Icons.Default.Refresh, fill = true)
            Spacer(Modifier.height(Dimens.space1))
            Text("每次生成自动保存为新版本，旧版本可在右侧「依据 → 历史版本」查看/回退",
                fontSize = 11.sp, color = Muted, lineHeight = 16.sp)
        }
        if (vm.busy) {
            Spacer(Modifier.height(Dimens.space2))
            AppButton("取消生成", onClick = { vm.cancelGeneration() },
                kind = AppButtonKind.DANGER, fill = true)
        }
        Spacer(Modifier.height(Dimens.space4))
    }
}

/**
 * 可编辑任务字段：改动后点右侧 ✓ 同步后端。
 * 多行展示（最多 3 行），避免长参数（如写作目标、主要工作）被单行裁剪看不全。
 */
@Composable
private fun TaskField(label: String, value: String, onSync: (String) -> Unit) {
    var editing by remember(value) { androidx.compose.runtime.mutableStateOf<String?>(null) }
    val shown = editing ?: value
    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(label, fontSize = 11.5.sp, color = Muted, modifier = Modifier.width(72.dp))
        OutlinedTextField(
            value = shown,
            onValueChange = { editing = it },
            placeholder = { Text(Pending, fontSize = 12.sp, color = Muted2) },
            modifier = Modifier.weight(1f).heightIn(min = 40.dp, max = 96.dp),
            singleLine = false,
            maxLines = 3,
            shape = RoundedCornerShape(Dimens.radiusSm),
            textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.5.sp, color = Ink),
            colors = TextFieldDefaults.outlinedTextFieldColors(
                backgroundColor = SurfaceTonal, focusedBorderColor = Primary,
                unfocusedBorderColor = Line, cursorColor = Primary),
        )
        if (editing != null && editing != value) {
            Spacer(Modifier.width(Dimens.space1))
            Box(
                Modifier.size(26.dp).clip(RoundedCornerShape(Dimens.radiusXs))
                    .background(PrimarySoft)
                    .clickable { onSync(editing ?: ""); editing = null },
                contentAlignment = Alignment.Center,
            ) { Text("✓", fontSize = 13.sp, color = Primary) }
        }
    }
}

// ---------------- 中栏：文档工作台 ----------------

@Composable
private fun EditorPanel(vm: WritingViewModel, modifier: Modifier) {
    Column(modifier) {
        // 文档工具条
        Row(
            Modifier.fillMaxWidth()
                .clip(RoundedCornerShape(Dimens.radiusLg))
                .background(Surface)
                .border(1.dp, LineSubtle, RoundedCornerShape(Dimens.radiusLg))
                .padding(horizontal = Dimens.space4, vertical = Dimens.space3),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(vm.task.title.ifBlank { "未命名文档" }, fontSize = 14.5.sp,
                    fontWeight = FontWeight.SemiBold, color = Ink, maxLines = 1,
                    overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(2.dp))
                Text(
                    buildString {
                        append(vm.task.documentType.ifBlank { "未识别文种" })
                        if (vm.task.recipient.isNotBlank()) append(" · 报送 ${vm.task.recipient}")
                    },
                    fontSize = 11.5.sp, color = Muted, maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Spacer(Modifier.width(Dimens.space3))
            if (vm.busy) {
                AppButton("取消生成", onClick = { vm.cancelGeneration() },
                    kind = AppButtonKind.DANGER)
                Spacer(Modifier.width(Dimens.space2))
            }
            if (vm.hasDraft) {
                AppButton("继续生成", onClick = { vm.draft() },
                    kind = AppButtonKind.AI, enabled = !vm.busy,
                    icon = Icons.Default.Refresh)
                Spacer(Modifier.width(Dimens.space2))
                AppButton("保存版本", onClick = { vm.saveVersion() },
                    kind = AppButtonKind.SECONDARY, enabled = !vm.busy)
                Spacer(Modifier.width(Dimens.space2))
                AppButton("导出 Word", onClick = {
                    pickSaveFile("${vm.task.title.ifBlank { "公文" }}.docx")
                        ?.let { vm.export(true, it) }
                }, kind = AppButtonKind.PRIMARY, enabled = !vm.busy)
            }
        }

        Spacer(Modifier.height(Dimens.space3))

        if (!vm.hasDraft) {
            // 空状态：文档图形 + 当前任务 + 明确主操作
            Column(
                Modifier.fillMaxWidth().weight(1f)
                    .clip(RoundedCornerShape(Dimens.radiusLg))
                    .background(Surface)
                    .border(1.dp, LineSubtle, RoundedCornerShape(Dimens.radiusLg)),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                EmptyState(
                    text = "还没有正文",
                    hint = "左栏确认任务上下文后生成初稿，或在右栏告诉助手你想要的写法",
                    icon = Icons.Default.Description,
                ) {
                    AppButton("生成初稿", onClick = { vm.draft() }, kind = AppButtonKind.AI,
                        enabled = !vm.busy, loading = vm.busy, size = AppButtonSize.LG)
                }
            }
            return
        }

        // 文档纸张
        DocumentSurface(modifier = Modifier.weight(1f), padding = Dimens.space6) {
            // 正文默认就是「所见即所得」：按公文格式渲染（标题居中/加粗、
            // 一、（一）层级行加粗、正文段首缩进两字符、**粗体** 生效），
            // 点击任意段落就地修改，格式变化立刻可见；
            // 「源码模式」回到 Markdown 原文整篇编辑（高级用法，兼容旧习惯）。
            var sourceMode by remember { mutableStateOf(false) }
            Row(verticalAlignment = Alignment.CenterVertically) {
                TagChip("V${maxOf(vm.versionNo, 1)}", fg = Warn, bg = WarnSoft)
                Spacer(Modifier.width(Dimens.space2))
                Text("待完善", fontSize = 11.5.sp, color = Muted)
                Spacer(Modifier.weight(1f))
                if (vm.task.documentNumberEnabled && vm.task.documentNumber.isNotBlank()) {
                    Text(vm.task.documentNumber, fontSize = 11.5.sp, color = Muted)
                    Spacer(Modifier.width(Dimens.space3))
                }
                if (!sourceMode) {
                    Text("点击段落即可修改", fontSize = 11.sp, color = Muted2)
                    Spacer(Modifier.width(Dimens.space3))
                }
                AppLinkButton(if (sourceMode) "退出源码" else "源码模式",
                    onClick = { sourceMode = !sourceMode })
            }
            Spacer(Modifier.height(Dimens.space4))
            if (vm.task.title.isNotBlank()) {
                Text(vm.task.title, fontSize = 20.sp, fontWeight = FontWeight.Bold,
                    modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center,
                    color = Ink, lineHeight = 30.sp)
                Spacer(Modifier.height(Dimens.space4))
            }
            Hairline()
            Spacer(Modifier.height(Dimens.space3))
            if (sourceMode) {
                OutlinedTextField(
                    value = vm.content,
                    onValueChange = { vm.content = it },
                    modifier = Modifier.fillMaxWidth().weight(1f),
                    textStyle = androidx.compose.ui.text.TextStyle(
                        fontSize = 14.5.sp, color = Ink, lineHeight = 26.sp),
                    shape = RoundedCornerShape(Dimens.radiusMd),
                    colors = TextFieldDefaults.outlinedTextFieldColors(
                        backgroundColor = Surface,
                        focusedBorderColor = LineSubtle,
                        unfocusedBorderColor = Color.Transparent,
                        cursorColor = Primary),
                )
            } else {
                Column(
                    Modifier.fillMaxWidth().weight(1f)
                        .verticalScroll(rememberScrollState()),
                ) {
                    FormattedBodyEditor(vm)
                }
            }
            Spacer(Modifier.height(Dimens.space3))
            val versionText = if (vm.versionNo > 0) "版本 v${vm.versionNo}" else "未保存版本"
            val stateText = if (vm.busy) "助手处理中" else "已就绪"
            val stateColor: Color = if (vm.busy) Primary else Muted
            DocumentStatusBar(
                left = "字数：约 ${vm.content.length} 字",
                items = listOf(versionText to Muted, stateText to stateColor),
            )
        }
    }
}

// ---------------- 右栏：AI 助手 ----------------

private val QUICK_ACTIONS = listOf(
    Triple("扩写", "expand", "扩写当前内容"),
    Triple("润色", "polish", "润色当前内容"),
    Triple("精简", "condense", "精简当前内容"),
    Triple("规范化", "normalize", "调整为司法行政机关正式材料语言"),
    Triple("补充结构", "complete", "判断当前文档缺少哪些必要部分并补充"),
    Triple("检查问题", "revise", "检查当前文档存在的问题并列出"),
)

@Composable
private fun AssistantPanel(vm: WritingViewModel, modifier: Modifier) {
    var tab by remember { androidx.compose.runtime.mutableStateOf(0) }
    Column(
        modifier.fillMaxHeight()
            .clip(RoundedCornerShape(Dimens.radiusLg))
            .background(Surface)
            .border(1.dp, LineSubtle, RoundedCornerShape(Dimens.radiusLg))
            .padding(Dimens.space4),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(26.dp).clip(RoundedCornerShape(Dimens.radiusSm))
                    .background(Brush.linearGradient(listOf(AiIndigo, Primary))),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Default.AutoAwesome, null, tint = OnPrimaryText,
                    modifier = Modifier.size(Dimens.iconXs))
            }
            Spacer(Modifier.width(Dimens.space2))
            Column(Modifier.weight(1f)) {
                Text("助手", fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                Text(vm.spec?.agent?.ifBlank { AppState.agentName.ifBlank { "智能助手" } }
                    ?: AppState.agentName.ifBlank { "智能助手" },
                    fontSize = 11.sp, color = Muted, maxLines = 1,
                    overflow = TextOverflow.Ellipsis)
            }
        }

        Spacer(Modifier.height(Dimens.space3))
        if (vm.busy) {
            AiWorkingRow(if (vm.planning) "正在准备写作环境…" else "正在处理当前文档…")
            Spacer(Modifier.height(Dimens.space3))
        }

        AppSegmentedTabs(
            tabs = listOf("对话", "建议", "依据"),
            selectedIndex = tab,
            onSelect = { tab = it },
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(Dimens.space3))

        when (tab) {
            0 -> {
                LazyColumn(
                    Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(Dimens.space3),
                ) {
                    items(vm.messages) { m ->
                        AiBubble(text = m.content, isUser = m.role == "user",
                            label = vm.spec?.agent?.ifBlank { "助手" } ?: "助手")
                    }
                }
            }
            1 -> {
                Column(
                    Modifier.weight(1f).verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(Dimens.space2),
                ) {
                    val actions = vm.spec?.aiActions.orEmpty()
                    if (actions.isNotEmpty()) {
                        SectionTitle("针对本次任务")
                        Spacer(Modifier.height(Dimens.space1))
                        Column(verticalArrangement = Arrangement.spacedBy(Dimens.space2)) {
                            actions.chunked(2).forEach { row ->
                                Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space2)) {
                                    row.forEach { a ->
                                        Box(Modifier.weight(1f)) {
                                            AiActionChip(a, onClick = { vm.revise(a, "revise") },
                                                enabled = !vm.busy && vm.hasDraft,
                                                icon = Icons.Default.AutoAwesome)
                                        }
                                    }
                                    if (row.size == 1) Spacer(Modifier.weight(1f))
                                }
                            }
                        }
                        Spacer(Modifier.height(Dimens.space4))
                    }
                    SectionTitle("对当前文档")
                    Spacer(Modifier.height(Dimens.space1))
                    Column(verticalArrangement = Arrangement.spacedBy(Dimens.space2)) {
                        QUICK_ACTIONS.chunked(2).forEach { row ->
                            Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space2)) {
                                row.forEach { (label, mode, hint) ->
                                    Box(Modifier.weight(1f)) {
                                        AiActionChip(label,
                                            onClick = { vm.revise(hint, mode) },
                                            enabled = !vm.busy && vm.hasDraft)
                                    }
                                }
                                if (row.size == 1) Spacer(Modifier.weight(1f))
                            }
                        }
                    }
                    if (!vm.hasDraft) {
                        Spacer(Modifier.height(Dimens.space3))
                        Text("生成正文后可用这些操作继续打磨", fontSize = 11.5.sp, color = Muted)
                    }
                }
            }
            else -> {
                Column(
                    Modifier.weight(1f).verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(Dimens.space3),
                ) {
                    if (vm.references.isEmpty()) {
                        EmptyState("本次写作暂无引用记录",
                            hint = "生成或改写正文后，这里会列出助手实际参考的资料",
                            icon = Icons.Default.Description)
                    } else {
                        ContextSources(
                            summary = "已参考 ${vm.references.size} 项相关资料",
                            sources = vm.references,
                            tint = EmeraldInk,
                            container = EmeraldSoft,
                        )
                    }
                    val selectedKb = vm.spec?.knowledge?.filter { it.selected }.orEmpty()
                    if (selectedKb.isNotEmpty()) {
                        ContextSources(
                            summary = "来自${AppState.departmentName.ifBlank { "本科室" }}业务知识与公共资料",
                            sources = selectedKb.map { it.label },
                            tint = EmeraldInk,
                            container = EmeraldSoft,
                        )
                    }
                    if (vm.versions.isNotEmpty()) {
                        Spacer(Modifier.height(Dimens.space2))
                        SectionTitle("历史版本")
                        Text("点击查看全文，可回退（当前内容会自动保存）",
                            fontSize = 11.sp, color = Muted)
                        vm.versions.take(6).forEach { v ->
                            Row(
                                Modifier.fillMaxWidth()
                                    .clip(RoundedCornerShape(Dimens.radiusXs))
                                    .clickable { vm.openVersion(v["version_no"].int()) }
                                    .padding(vertical = 4.dp, horizontal = 2.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text("v${v["version_no"].int()}", fontSize = 12.sp,
                                    color = Primary, modifier = Modifier.width(40.dp))
                                Text(v["note"].str().ifBlank { "自动保存" },
                                    fontSize = 12.sp, color = Ink2, maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f))
                                Text("查看/回退", fontSize = 11.sp, color = Primary)
                            }
                        }
                    }
                }
            }
        }

        Spacer(Modifier.height(Dimens.space3))
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = vm.chatInput,
                onValueChange = { vm.chatInput = it },
                placeholder = { Text("继续说：把第二部分写详细一点…", fontSize = 12.sp,
                    color = Muted2) },
                modifier = Modifier.weight(1f).heightIn(min = Dimens.hControl, max = 72.dp),
                maxLines = 3,
                enabled = !vm.busy,
                shape = RoundedCornerShape(Dimens.radiusControl),
                textStyle = androidx.compose.ui.text.TextStyle(fontSize = 13.sp, color = Ink),
                colors = TextFieldDefaults.outlinedTextFieldColors(
                    backgroundColor = SurfaceTonal, focusedBorderColor = Primary,
                    unfocusedBorderColor = Line, cursorColor = Primary),
            )
            Spacer(Modifier.width(Dimens.space2))
            AppIconButton(
                icon = Icons.Default.Send,
                contentDescription = "发送",
                onClick = { vm.sendChat() },
                size = 38.dp,
                tint = if (vm.chatInput.isBlank() || vm.busy) Muted2 else Primary,
                active = vm.chatInput.isNotBlank() && !vm.busy,
            )
        }
        if (vm.hasDraft) {
            Spacer(Modifier.height(Dimens.space2))
            AppLinkButton("加入训练数据", onClick = { vm.addToTraining() }, enabled = !vm.busy)
        }
        WritingStatusLine(vm.status)
    }
}

/**
 * 状态提示条：只有真正的失败才用红色错误框。
 *
 * 写作台的 `status` 同时承载三类文案——失败原因（"导出失败：…"）、进行中提示
 * （"上传材料中…"、"正在保存…"）和成功提示（"已保存版本 v3"、"已导出：xxx"）。
 * 之前一律走 [FieldError]（恒为红色危险框，见 AppControls.kt:338），用户每切一次
 * 页面就被红字迎面打一次，误以为"切换就会报错"。这里按语义分流。
 */
@Composable
private fun WritingStatusLine(status: String?) {
    val text = status?.takeIf { it.isNotBlank() } ?: return
    Spacer(Modifier.height(Dimens.space3))
    if (isWritingFailureText(text)) {
        FieldError(text)
    } else {
        Row(
            Modifier.fillMaxWidth()
                .clip(RoundedCornerShape(Dimens.radiusSm))
                .background(AiSoft)
                .border(1.dp, AiSoftStrong, RoundedCornerShape(Dimens.radiusSm))
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(text, fontSize = 12.sp, color = Ink, lineHeight = 18.sp)
        }
    }
}

/** 进行中 / 成功提示：中性浅蓝条，不吓人 */
@Composable
private fun WritingProgressLine(text: String) {
    Spacer(Modifier.height(Dimens.space3))
    Row(
        Modifier.fillMaxWidth()
            .clip(RoundedCornerShape(Dimens.radiusSm))
            .background(AiSoft)
            .border(1.dp, AiSoftStrong, RoundedCornerShape(Dimens.radiusSm))
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text, fontSize = 12.sp, color = Ink, lineHeight = 18.sp)
    }
}

/**
 * 判定一条 status 是否为「失败」语义。
 * 命中失败关键词 → 红色；其余（"已…"、"正在…"、普通说明）→ 中性提示。
 */
private fun isWritingFailureText(text: String): Boolean {
    val failureHints = listOf(
        "失败", "错误", "中断", "不存在", "已删除", "不可达", "超时",
        "无法", "不能", "缺少", "请先", "仅支持", "已过期", "不合法", "异常",
    )
    return failureHints.any { text.contains(it) }
}
