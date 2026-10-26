package com.judicialai.desktop.features.writing

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Checkbox
import androidx.compose.material.DropdownMenu
import androidx.compose.material.DropdownMenuItem
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
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
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
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextIndent
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.Dp
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
import com.judicialai.desktop.design.components.FilterChip
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
 * 三段式：一句话入口 → AI 规划本次写作环境 → 四栏工作台。
 * 左栏是「任务上下文」（任务卡可人工修订 + 材料 + 可依据资料 + 模板），不是只读参数表；
 * 中栏是真正的文档工作台；右侧分别为选中段落建议与 AI 助手。
 * 界面不出现「全局公共知识库」「本科室知识库」这类系统实现语言。
 *
 * 模板中心「使用模板 → 生成」也会进入本工作台：
 * 携带模板绑定与已填要素，创建任务后自动起草。
 */
@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
fun WritingScreen() {
    val vm = remember {
        WritingViewModel(Repositories.writing, Repositories.knowledge, Repositories.templates)
    }

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

    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().background(AppBg)) {
            if (lastError != null && !generating) {
                WritingFailedBanner(lastError) { AppState.writingLastError = null }
            }
            // 切回页面后正在从服务端取回任务：明确说明在做什么，别让人以为卡住/报错
            if (vm.restoring) {
                WritingProgressLine("正在取回上次未完成的写作任务…")
            }
            vm.agentProgress?.takeIf { it.isNotBlank() }?.let {
                WritingProgressLine(it)
            }
            Box(Modifier.weight(1f).fillMaxWidth()) {
                if (!vm.hasTask) {
                    TaskEntryScreen(vm)
                } else {
                    BoxWithConstraints(Modifier.fillMaxSize()) {
                        val roomy = maxWidth >= 1320.dp
                        val medium = maxWidth >= 980.dp
                        val contextWidth = if (roomy) 240.dp else 210.dp
                        val assistantWidth = if (roomy) 350.dp else 300.dp
                        var showContext by remember { mutableStateOf(medium) }
                        var showDocument by remember { mutableStateOf(true) }
                        var showAssistant by remember { mutableStateOf(maxWidth >= 1180.dp) }
                        var assistantTab by remember { mutableStateOf(0) }
                        val widthBucket = when {
                            maxWidth < 980.dp -> 0
                            maxWidth < 1180.dp -> 1
                            else -> 2
                        }

                        // 只在跨过宽度档位时收拢栏目，避免用户拖动窗口的每个像素都重置选择。
                        // 缩到最窄档时始终保留正文，防止栏目全部收起后留下空白工作区。
                        LaunchedEffect(widthBucket) {
                            when (widthBucket) {
                                0 -> {
                                    showContext = false
                                    showAssistant = false
                                    showDocument = true
                                }
                                1 -> showAssistant = false
                            }
                        }

                        fun openContext() {
                            showContext = true
                            if (maxWidth < 980.dp) {
                                showAssistant = false
                            }
                        }
                        fun openSuggestions() {
                            assistantTab = 1
                            showAssistant = true
                            if (maxWidth < 1180.dp) showContext = false
                        }
                        fun openAssistant() {
                            showAssistant = true
                            if (maxWidth < 1180.dp) showContext = false
                        }

                        Column(Modifier.fillMaxSize().padding(Dimens.space4)) {
                            FlowRow(
                                Modifier.fillMaxWidth().padding(bottom = Dimens.space2),
                                horizontalArrangement = Arrangement.spacedBy(Dimens.space2),
                                verticalArrangement = Arrangement.spacedBy(Dimens.space1),
                            ) {
                                FilterChip("任务上下文", selected = showContext, onClick = {
                                    if (showContext) showContext = false else openContext()
                                })
                                FilterChip("文档正文", selected = showDocument, onClick = {
                                    showDocument = !showDocument
                                })
                                FilterChip("助手", selected = showAssistant, onClick = {
                                    if (showAssistant) showAssistant = false else openAssistant()
                                })
                            }
                            Row(
                                Modifier.weight(1f).fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(Dimens.space2),
                            ) {
                                if (showContext) {
                                    Column(Modifier.width(contextWidth).fillMaxHeight()) {
                                        WritingColumnHeader("任务上下文") { showContext = false }
                                        if (vm.spec != null) SpecPanel(vm, Modifier.weight(1f))
                                        else TaskPanel(vm, Modifier.weight(1f))
                                    }
                                }
                                if (showDocument) {
                                    Column(Modifier.weight(1f).fillMaxHeight()) {
                                        WritingColumnHeader("文档正文") { showDocument = false }
                                        EditorPanel(vm, Modifier.weight(1f), onOpenSuggestions = {
                                            openSuggestions()
                                        })
                                    }
                                }
                                if (showAssistant) {
                                    Column(Modifier.width(assistantWidth).fillMaxHeight()) {
                                        WritingColumnHeader("助手") { showAssistant = false }
                                        AssistantPanel(vm, Modifier.weight(1f), assistantTab) {
                                            assistantTab = it
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // 轻提示浮层（如「取消生成成功」）：居中短暂展示，约 0.5 秒由 ViewModel 自动清除。
        // 取消是用户主动操作，不走 status 提示条，更不走红色错误框。
        vm.toast?.let { msg ->
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(
                    msg, fontSize = 13.sp, color = OnPrimaryText,
                    modifier = Modifier
                        .clip(RoundedCornerShape(Dimens.radiusLg))
                        .background(Ink.copy(alpha = 0.92f))
                        .padding(horizontal = Dimens.space5, vertical = Dimens.space3),
                )
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

@Composable
private fun WritingColumnHeader(title: String, onCollapse: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(bottom = Dimens.space1),
        verticalAlignment = Alignment.CenterVertically) {
        Text(title, fontSize = 11.sp, color = Muted, modifier = Modifier.weight(1f))
        AppLinkButton("收起", onClick = onCollapse)
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
            MarkdownText(body, vm.renderProfile)
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

/**
 * 公文结构行识别：AI 输出经常是纯文本（不带 # 标记），
 * 「一、」「（一）」这类公文层级标题也要按标题样式渲染，
 * 否则整篇都是同一种字重，格式变化完全看不出来。
 */
private val GwHeading1Regex = Regex("^[一二三四五六七八九十百]+、[^。；，]{2,60}$")
private val GwHeading2Regex = Regex("^（[一二三四五六七八九十]+）[^。；，]{2,60}$")
private val SignoffDateRegex = Regex("20\\d{2}\\s*年\\s*\\d{1,2}\\s*月\\s*\\d{1,2}\\s*日")
private val SignoffAuthorityRegex = Regex("[\\u4e00-\\u9fa5（）()]{2,25}(政府|办公厅|办公室|委员会|局|厅|部|署|所|处|院|中心)")

/**
 * 单行公文格式渲染：markdown 标题 / 公文层级标题 / 列表 / 分割线 / 表格行 /
 * 普通段落（段首缩进两字符 + 行内粗体）。预览与分块编辑共用这一套。
 */
@Composable
private fun FormattedLine(raw: String, profile: kotlinx.serialization.json.JsonObject? = null,
                          override: WritingTextStyle = WritingTextStyle()) {
    val s = raw.trim()
    val role = when {
        s.startsWith("# ") -> "title"
        s.startsWith("## ") || GwHeading1Regex.matches(s) -> "heading1"
        s.startsWith("### ") || GwHeading2Regex.matches(s) -> "heading2"
        else -> "body"
    }
    val spec = profile.previewStyle(role)
    val displayedSize = override.fontSizePt ?: spec.size
    val lineStyle = TextStyle(
        fontSize = displayedSize.sp,
        fontFamily = PreviewFonts.family(override.fontName ?: spec.fontName),
        fontWeight = if (override.bold ?: spec.bold) FontWeight.Bold else FontWeight.Normal,
        color = Ink,
        lineHeight = maxOf(spec.lineHeight, displayedSize * 1.25f).sp,
        textIndent = TextIndent(firstLine = (spec.size * spec.firstLineChars).sp),
    )
    when {
        s.isBlank() -> Spacer(Modifier.height(6.dp))
        s == "---" || s == "***" || s == "___" -> {
            Spacer(Modifier.height(4.dp)); Hairline(); Spacer(Modifier.height(4.dp))
        }
        else -> {
            val shown = when {
                s.startsWith("### ") -> s.removePrefix("### ")
                s.startsWith("## ") -> s.removePrefix("## ")
                s.startsWith("# ") -> s.removePrefix("# ")
                s.startsWith("- ") || s.startsWith("* ") -> "•  " + s.substring(2)
                else -> s
            }
            Text(inlineMd(shown), modifier = Modifier.fillMaxWidth(), style = lineStyle,
                textAlign = when (override.alignment) {
                    "center" -> TextAlign.Center
                    "right" -> TextAlign.Right
                    "justify" -> TextAlign.Justify
                    "left" -> TextAlign.Start
                    else -> if (role == "title") TextAlign.Center else TextAlign.Start
                })
        }
    }
}

/**
 * 公文 Markdown 轻量渲染：标题（# / ## / ###）、公文层级行（一、/（一））、
 * 无序/有序列表、分割线、粗体、正文段首缩进。
 * 用于历史版本预览，让正文以带格式的方式呈现而不是裸 txt。
 */
@Composable
private fun MarkdownText(text: String, profile: kotlinx.serialization.json.JsonObject? = null) {
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        text.split('\n').forEach { line -> FormattedLine(line, profile) }
    }
}

private val EDITOR_FONTS = listOf("仿宋_GB2312", "方正小标宋简体", "黑体", "楷体_GB2312",
    "宋体", "微软雅黑", "思源宋体", "思源黑体", "Arial")
private val EDITOR_SIZES = listOf(12f, 14f, 16f, 18f, 20f, 22f, 24f)

@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
internal fun FormatToolbar(style: WritingTextStyle, onChange: (WritingTextStyle) -> Unit,
                           defaultSize: Int = 16, defaultFont: String = "仿宋_GB2312") {
    var fontOpen by remember { mutableStateOf(false) }
    var sizeOpen by remember { mutableStateOf(false) }
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Box {
            AppLinkButton(style.fontName ?: defaultFont, onClick = { fontOpen = true })
            DropdownMenu(expanded = fontOpen, onDismissRequest = { fontOpen = false }) {
                EDITOR_FONTS.forEach { font -> DropdownMenuItem(onClick = {
                    onChange(style.copy(fontName = font)); fontOpen = false
                }) { Text(font) } }
            }
        }
        Box {
            AppLinkButton("${style.fontSizePt?.toInt() ?: defaultSize} 磅", onClick = { sizeOpen = true })
            DropdownMenu(expanded = sizeOpen, onDismissRequest = { sizeOpen = false }) {
                EDITOR_SIZES.forEach { size -> DropdownMenuItem(onClick = {
                    onChange(style.copy(fontSizePt = size)); sizeOpen = false
                }) { Text("${size.toInt()} 磅") } }
            }
        }
        AppLinkButton(if (style.bold == true) "加粗 ✓" else "加粗",
            onClick = { onChange(style.copy(bold = style.bold != true)) })
        listOf("left" to "居左", "center" to "居中", "right" to "居右", "justify" to "两端对齐")
            .forEach { (alignment, label) ->
                AppLinkButton(if (style.alignment == alignment) "$label ✓" else label,
                    onClick = { onChange(style.copy(alignment = alignment)) })
            }
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
private fun FormattedBodyEditor(
    vm: WritingViewModel,
    modifier: Modifier = Modifier,
    onOpenSuggestions: () -> Unit = {},
    topInset: Dp = 0.dp,
    bottomInset: Dp = 0.dp,
    header: @Composable () -> Unit = {},
) {
    var editIdx by remember { mutableStateOf<Int?>(null) }
    var editText by remember { mutableStateOf(TextFieldValue("")) }
    DisposableEffect(Unit) { onDispose { vm.markParagraphEditing(false) } }
    val lines = remember(vm.content) { vm.content.split('\n') }
    val profile = vm.renderProfile
    val bodySpec = profile.previewStyle("body")
    val paragraphStates = remember(vm.paragraphs) {
        vm.paragraphs.associateBy { it["line_index"].int() }
    }
    // 尾部独立落款按结构排版；正文内的同名引用仍保留原段落。
    val (signatureIndex, dateIndex) = remember(lines, vm.task.authority) {
        val nonBlankIndices = lines.indices.filter { lines[it].isNotBlank() }
        var signatureIndex: Int? = null
        var dateIndex: Int? = null
        var tailPosition = nonBlankIndices.lastIndex
        if (tailPosition >= 0 && SignoffDateRegex
                .matches(lines[nonBlankIndices[tailPosition]].trim())) {
            dateIndex = nonBlankIndices[tailPosition--]
        }
        if (tailPosition >= 0) {
            val tail = lines[nonBlankIndices[tailPosition]].trim()
            if ((vm.task.authority.isNotBlank() && tail == vm.task.authority.trim()) ||
                SignoffAuthorityRegex.matches(tail)) {
                signatureIndex = nonBlankIndices[tailPosition]
            }
        }
        signatureIndex to dateIndex
    }
    val displaySignature = signatureIndex?.let { lines[it].trim() } ?: vm.task.authority
    val displayDate = dateIndex?.let { lines[it].trim() } ?: vm.task.documentDate


    fun commit() {
        val i = editIdx ?: return
        vm.replaceParagraphContent(i, editText.text)
        editIdx = null
        vm.markParagraphEditing(false)
    }

    LazyColumn(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        item {
            Spacer(Modifier.height(topInset))
            header()
        }
        itemsIndexed(lines, key = { index, _ -> index }) { i, raw ->
            if (i == signatureIndex || i == dateIndex) return@itemsIndexed
            if (editIdx == i) {
                Column(
                    Modifier.fillMaxWidth()
                        .clip(RoundedCornerShape(Dimens.radiusSm))
                        .border(1.dp, Primary, RoundedCornerShape(Dimens.radiusSm))
                        .padding(Dimens.space2),
                ) {
                    val style = vm.paragraphFormatting[i] ?: WritingTextStyle()
                    if (!vm.busy) FormatToolbar(style, { vm.setParagraphFormatting(i, it) },
                        defaultSize = bodySpec.size.toInt(), defaultFont = bodySpec.fontName)
                    OutlinedTextField(
                        value = editText,
                        onValueChange = { editText = it },
                        enabled = !vm.suggestionBusy && !vm.busy,
                        modifier = Modifier.fillMaxWidth(),
                        textStyle = androidx.compose.ui.text.TextStyle(
                            fontSize = bodySpec.size.sp,
                            fontFamily = PreviewFonts.family(bodySpec.fontName),
                            color = Ink, lineHeight = bodySpec.lineHeight.sp),
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
                        Text("选中文字后点 B 可局部加粗；清空后点完成可删除此段",
                            fontSize = 10.5.sp, color = Muted2)
                        AppLinkButton("B", onClick = {
                            val selection = editText.selection
                            if (!selection.collapsed) {
                                val start = selection.min
                                val end = selection.max
                                val updated = editText.text.substring(0, start) + "**" +
                                    editText.text.substring(start, end) + "**" +
                                    editText.text.substring(end)
                                editText = TextFieldValue(updated)
                            }
                        })
                        Spacer(Modifier.weight(1f))
                        AppLinkButton("取消", onClick = {
                            editIdx = null
                            vm.markParagraphEditing(false)
                        })
                        Spacer(Modifier.width(Dimens.space3))
                        AppLinkButton("完成", onClick = { commit() })
                    }
                }
            } else {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
                    Box(
                        Modifier.weight(1f)
                            .clip(RoundedCornerShape(Dimens.radiusXs))
                            .clickable(enabled = !vm.busy && !vm.suggestionBusy) {
                                editIdx = i
                                editText = TextFieldValue(raw)
                                vm.markParagraphEditing(true)
                            }
                            .padding(horizontal = 4.dp, vertical = 1.dp),
                    ) {
                        FormattedLine(raw, profile, vm.paragraphFormatting[i] ?: WritingTextStyle())
                    }
                    if (raw.isNotBlank()) {
                        val state = paragraphStates[i]?.get("status").str()
                        val marker = when (state) {
                            "pending" -> "⚡"
                            "accepted" -> "✓"
                            "rejected" -> "✗"
                            else -> "✎"
                        }
                        val markerColor = when (state) {
                            "pending" -> Warn
                            "accepted" -> EmeraldInk
                            else -> Muted
                        }
                        TextButton(onClick = {
                            onOpenSuggestions()
                            vm.selectParagraph(i)
                        }, enabled = !vm.busy && !vm.suggestionBusy,
                            modifier = Modifier.width(32.dp)) {
                            Text(marker, color = markerColor, fontSize = 14.sp)
                        }
                    }
                }
            }
        }
        if (displaySignature.isNotBlank() || displayDate.isNotBlank()) {
            item {
                val signoff = profile.previewStyle("signature")
                Column(Modifier.fillMaxWidth().padding(top = 24.dp,
                    end = (signoff.size * signoff.rightIndentChars).dp),
                    horizontalAlignment = Alignment.End) {
                    if (displaySignature.isNotBlank()) Text(displaySignature,
                        fontSize = profile.previewStyle("signature").size.sp,
                        fontFamily = PreviewFonts.family(profile.previewStyle("signature").fontName),
                        color = Ink, lineHeight = profile.previewStyle("signature").lineHeight.sp,
                        textAlign = TextAlign.Right)
                    if (displayDate.isNotBlank()) Text(displayDate,
                        fontSize = profile.previewStyle("date").size.sp,
                        fontFamily = PreviewFonts.family(profile.previewStyle("date").fontName),
                        color = Ink, lineHeight = profile.previewStyle("date").lineHeight.sp,
                        textAlign = TextAlign.Right)
                }
            }
        }
        if (vm.content.isBlank()) {
            item {
                Text("（正文为空，生成初稿后可在此直接修改）",
                    fontSize = 13.sp, color = Muted)
            }
        }
        item { Spacer(Modifier.height(bottomInset)) }
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

            // 初始格式设计入口：复用现有模板中心，不另造一套格式系统。
            Row(
                Modifier.fillMaxWidth()
                    .clip(RoundedCornerShape(Dimens.radiusLg))
                    .background(SurfaceTonal)
                    .border(1.dp, LineSubtle, RoundedCornerShape(Dimens.radiusLg))
                    .clickable(enabled = !vm.busy) { AppState.navigate(AppScreen.TEMPLATES) }
                    .padding(horizontal = Dimens.space4, vertical = Dimens.space3),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Default.Description, null, tint = Primary,
                    modifier = Modifier.size(Dimens.iconMd))
                Spacer(Modifier.width(Dimens.space3))
                Column(Modifier.weight(1f)) {
                    Text("格式方案（可选）", fontSize = 13.5.sp,
                        fontWeight = FontWeight.SemiBold, color = Ink)
                    Text("只有主动选择后才套用模板；直接写作由系统按需求组织内容。",
                        fontSize = 11.5.sp, color = Muted, lineHeight = 17.sp)
                }
                Text("选择 / 设计 →", fontSize = 12.sp, color = Primary)
            }

            Spacer(Modifier.height(Dimens.space3))

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
                        Text("说一句需求即可，文种、结构和参考资料由我组织",
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
                        "组织写作结构与任务上下文",
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
                    AppLinkButton("取消本次生成", onClick = { vm.cancelAndReset() })
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
    Box(Modifier.fillMaxWidth().clip(shape)
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

@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
private fun SpecPanel(vm: WritingViewModel, modifier: Modifier) {
    val spec = vm.spec ?: return
    val deptName = AppState.departmentName
    // 拉取模板中心的启用模板供「文种模板（可选）」下拉使用；失败时静默降级为无选项。
    LaunchedEffect(Unit) { vm.loadTemplateOptions() }
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

        // 文种模板（可选增强）
        // 默认「不使用」——此时后端不注入任何模板要求，模型按自身判断组织文种与结构。
        // 刻意做成可选而非强制：强套模板会把模型锁死（曾把讲话稿套成报告四段式）。
        val tplOptions by vm.templateOptions.collectAsState()
        val chosenTpl by vm.chosenTemplateId.collectAsState()
        if (tplOptions.isNotEmpty()) {
            Spacer(Modifier.height(Dimens.space3))
            ContextBlock(title = "文种模板（可选）") {
                Text(
                    "不选则由模型自行判断文种与结构；选中后附加该文种的专门写作要求。",
                    fontSize = 11.sp, color = Muted,
                    modifier = Modifier.padding(bottom = 6.dp),
                )
                FlowRow(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(Dimens.space1),
                    verticalArrangement = Arrangement.spacedBy(Dimens.space1),
                ) {                    FilterChip("不使用", selected = chosenTpl.isBlank(),
                        onClick = { vm.chooseTemplate("") })
                    tplOptions.forEach { opt ->
                        FilterChip(opt.label, selected = chosenTpl == opt.id,
                            onClick = { vm.chooseTemplate(opt.id) })
                    }
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
            AppButton("基于当前稿继续生成", onClick = { vm.draft() },
                kind = AppButtonKind.AI, enabled = !vm.busy, loading = vm.busy,
                icon = Icons.Default.Refresh, fill = true)
            Spacer(Modifier.height(Dimens.space1))
            Text("会以当前稿为基础生成新版本；差异过大时保留原稿",
                fontSize = 11.sp, color = Muted, lineHeight = 16.sp)
        }
        if (vm.busy) {
            Spacer(Modifier.height(Dimens.space2))
            AppButton("取消生成", onClick = { vm.cancelAndReset() },
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
            ContextBlock(title = "可补充的信息（不影响起草）", tint = Warn) {
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
            AppButton("基于当前稿继续生成", onClick = { vm.draft() },
                kind = AppButtonKind.AI, enabled = !vm.busy, loading = vm.busy,
                icon = Icons.Default.Refresh, fill = true)
            Spacer(Modifier.height(Dimens.space1))
            Text("会以当前稿为基础生成新版本；差异过大时保留原稿",
                fontSize = 11.sp, color = Muted, lineHeight = 16.sp)
        }
        if (vm.busy) {
            Spacer(Modifier.height(Dimens.space2))
            AppButton("取消生成", onClick = { vm.cancelAndReset() },
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

@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
private fun EditorPanel(
    vm: WritingViewModel,
    modifier: Modifier,
    onOpenSuggestions: () -> Unit = {},
) {
    Column(modifier) {
        // 文档工具条
        Column(
            Modifier.fillMaxWidth()
                .clip(RoundedCornerShape(Dimens.radiusLg))
                .background(Surface)
                .border(1.dp, LineSubtle, RoundedCornerShape(Dimens.radiusLg))
                .padding(horizontal = Dimens.space4, vertical = Dimens.space3),
        ) {
            Column(Modifier.fillMaxWidth()) {
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
            if (vm.busy || vm.hasDraft) {
                Spacer(Modifier.height(Dimens.space2))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(Dimens.space2),
                    verticalArrangement = Arrangement.spacedBy(Dimens.space2)) {
                    if (vm.busy) {
                        AppButton("取消生成", onClick = { vm.cancelAndReset() },
                            kind = AppButtonKind.DANGER)
                    }
                    if (vm.hasDraft) {
                        AppButton("基于当前稿继续生成", onClick = { vm.draft() },
                            kind = AppButtonKind.AI, enabled = !vm.busy,
                            icon = Icons.Default.Refresh)
                        AppButton("保存版本", onClick = { vm.saveVersion() },
                            kind = AppButtonKind.SECONDARY,
                            enabled = !vm.busy && !vm.suggestionBusy)
                        AppButton("导出 Word", onClick = {
                            pickSaveFile("${vm.task.title.ifBlank { "公文" }}.docx")
                                ?.let { vm.export(true, it) }
                        }, kind = AppButtonKind.PRIMARY, enabled = !vm.busy)
                    }
                }
            }
            if (vm.hasDraft) {
                Spacer(Modifier.height(Dimens.space2))
                Text("标题格式", fontSize = 11.sp, color = Muted)
                if (!vm.busy) FormatToolbar(vm.titleFormatting, vm::updateTitleFormatting,
                    defaultSize = 22, defaultFont = "方正小标宋简体")
                if (vm.formatDirty) Text("格式已修改，保存版本后生效；导出时会自动保存。",
                    fontSize = 11.sp, color = Warn)
                if (vm.formatIssues.isNotEmpty()) {
                    Spacer(Modifier.height(Dimens.space2))
                    Text("当前格式复检：${vm.formatIssues.size} 项问题", fontSize = 12.sp, color = Warn)
                    vm.formatIssues.take(8).forEach { issue ->
                        val location = issue["location"].str()
                        val element = issue["element"].str()
                        val suggestion = issue["suggestion"].str()
                        Text("${location} ${element}：${suggestion}", fontSize = 11.sp, color = Muted)
                    }
                }
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

        // A4 页面宽度按当前栏宽缩放；字号仍按后端规则显示。
        BoxWithConstraints(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.TopCenter) {
            val pageWidth = minOf(maxWidth, 794.dp)
            val scale = pageWidth.value / 794f
            val profile = vm.renderProfile
            val leftInset = (profile.pageCm("left_margin_cm", 2.8f) * 37.8f * scale).dp
            val rightInset = (profile.pageCm("right_margin_cm", 2.6f) * 37.8f * scale).dp
            val topInset = (profile.pageCm("top_margin_cm", 3.7f) * 37.8f * scale).dp
            val bottomInset = (profile.pageCm("bottom_margin_cm", 3.5f) * 37.8f * scale).dp
        DocumentSurface(modifier = Modifier.width(pageWidth).fillMaxHeight(), padding = 0.dp,
            pagePadding = PaddingValues(start = leftInset, end = rightInset,
                top = 0.dp, bottom = 0.dp)) {
            // 正文默认就是「所见即所得」：按公文格式渲染（标题居中、
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
                AppLinkButton(if (sourceMode) "返回排版视图" else "纯文本编辑",
                    onClick = { sourceMode = !sourceMode })
            }
            Spacer(Modifier.height(Dimens.space3))
            if (!sourceMode) {
                Row(
                    Modifier.fillMaxWidth()
                        .clip(RoundedCornerShape(Dimens.radiusSm))
                        .background(SurfaceTonal)
                        .padding(horizontal = Dimens.space3, vertical = Dimens.space2),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("排版视图", fontSize = 11.5.sp, fontWeight = FontWeight.SemiBold,
                        color = Primary)
                    Spacer(Modifier.width(Dimens.space3))
                    val bodyStyle = profile.previewStyle("body")
                    val titleStyle = profile.previewStyle("title")
                    Text("标题 ${titleStyle.size.toInt()}pt · 正文 ${bodyStyle.size.toInt()}pt · 行距 ${bodyStyle.lineHeight}pt · 首行缩进 ${bodyStyle.firstLineChars.toInt()} 字符",
                        fontSize = 11.sp, color = Muted)
                }
                Spacer(Modifier.height(Dimens.space5))
            }
            val documentHeader: @Composable () -> Unit = {
            if (vm.task.documentNumberEnabled && vm.task.documentNumber.isNotBlank()) {
                val numberStyle = profile.previewStyle("document_number")
                Text(vm.task.documentNumber, fontSize = numberStyle.size.sp,
                    fontFamily = PreviewFonts.family(numberStyle.fontName),
                    modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center,
                    color = Ink2, lineHeight = numberStyle.lineHeight.sp)
                Spacer(Modifier.height(Dimens.space3))
            }
            if (vm.task.title.isNotBlank()) {
                val titleStyle = profile.previewStyle("title")
                val selectedStyle = vm.titleFormatting
                Text(vm.task.title, fontSize = (selectedStyle.fontSizePt ?: titleStyle.size).sp,
                    fontFamily = PreviewFonts.family(selectedStyle.fontName ?: titleStyle.fontName),
                    fontWeight = if (selectedStyle.bold == true) FontWeight.Bold else FontWeight.Normal,
                    modifier = Modifier.fillMaxWidth(), textAlign = when (selectedStyle.alignment) {
                        "left" -> TextAlign.Start
                        "right" -> TextAlign.Right
                        "justify" -> TextAlign.Justify
                        else -> TextAlign.Center
                    },
                    color = Ink, lineHeight = titleStyle.lineHeight.sp)
                Spacer(Modifier.height(Dimens.space5))
            }
            // 主送机关行回归正文（由 AI 按文种判断是否书写），不再在这里写死渲染，
            // 否则填完「报送对象」字段会无 AI 参与地直接插入一行。
            }
            if (sourceMode) {
                documentHeader()
                val bodyStyle = profile.previewStyle("body")
                OutlinedTextField(
                    value = vm.content,
                    onValueChange = vm::replaceSourceContent,
                    enabled = !vm.suggestionBusy && !vm.busy,
                    modifier = Modifier.fillMaxWidth().weight(1f),
                    textStyle = androidx.compose.ui.text.TextStyle(
                        fontSize = bodyStyle.size.sp,
                        fontFamily = PreviewFonts.family(bodyStyle.fontName),
                        color = Ink, lineHeight = bodyStyle.lineHeight.sp),
                    shape = RoundedCornerShape(Dimens.radiusMd),
                    colors = TextFieldDefaults.outlinedTextFieldColors(
                        backgroundColor = Surface,
                        focusedBorderColor = LineSubtle,
                        unfocusedBorderColor = Color.Transparent,
                        cursorColor = Primary),
                )
            } else {
                FormattedBodyEditor(
                    vm = vm,
                    modifier = Modifier.fillMaxWidth().weight(1f),
                    onOpenSuggestions = onOpenSuggestions,
                    topInset = topInset,
                    bottomInset = bottomInset,
                    header = documentHeader,
                )
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
}

// ---------------- 逐段建议：只对当前选中的正文行生效 ----------------

@Composable
private fun ParagraphSuggestionPanel(vm: WritingViewModel, modifier: Modifier) {
    var details by remember { mutableStateOf(false) }
    Column(modifier.fillMaxHeight()) {
        Text("选中一段，查看 AI 建议", fontSize = 13.sp,
            fontWeight = FontWeight.SemiBold, color = Ink)
        Spacer(Modifier.height(Dimens.space3))
        val selected = vm.selectedParagraph
        if (selected == null) {
            Text("点击正文右侧的 ✎ 选中一段，再点「AI优化」生成建议；" +
                "也可以先在下方写下对 AI 的要求（例如字数、语气）。", fontSize = 12.sp,
                color = Muted, lineHeight = 18.sp)
            return@Column
        }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
            Text("原文", fontSize = 11.sp, color = Muted)
            Text(selected["content"].str(), fontSize = 12.sp, color = Ink,
                lineHeight = 19.sp)
            Spacer(Modifier.height(Dimens.space3))
            if (vm.suggestionBusy) {
                AiWorkingRow("正在为这一段生成建议…")
            } else {
                val state = vm.selectedSuggestion?.get("status").str()
                when (state) {
                    "pending" -> {
                        Text("建议（可直接修改）", fontSize = 11.sp, color = Muted)
                        OutlinedTextField(
                            value = vm.suggestionText,
                            onValueChange = { vm.suggestionText = it },
                            modifier = Modifier.fillMaxWidth(),
                            textStyle = androidx.compose.ui.text.TextStyle(
                                fontSize = 12.sp, color = Ink, lineHeight = 19.sp),
                        )
                        if (vm.suggestionText == selected["content"].str()) {
                            Text("AI 认为本段可保留原文。", fontSize = 11.sp, color = Muted)
                        }
                    }
                    "accepted" -> Text("已采纳；这段已更新。可再次 AI 优化，" +
                        "或直接点击正文手动修改。", fontSize = 12.sp, color = EmeraldInk,
                        lineHeight = 18.sp)
                    "rejected" -> Text("已拒绝；原文保持不变。可输入要求后再次 AI 优化。",
                        fontSize = 12.sp, color = Muted, lineHeight = 18.sp)
                    else -> Text("尚无建议。可先在下方写下对 AI 的要求，再点「AI优化」。",
                        fontSize = 12.sp, color = Muted, lineHeight = 18.sp)
                }
                Spacer(Modifier.height(Dimens.space3))
                AppLinkButton(if (details) "收起详情" else "看详情", onClick = { details = !details })
                if (details) {
                    Text("本次建议只作用于选中的一段；采纳后会生成新版本。" +
                        "如正文已被手动修改，请先保存版本再继续。",
                        fontSize = 11.sp, color = Muted, lineHeight = 17.sp)
                }
            }
        }
        Spacer(Modifier.height(Dimens.space3))
        OutlinedTextField(
            value = vm.suggestionInstruction,
            onValueChange = { vm.suggestionInstruction = it },
            modifier = Modifier.fillMaxWidth(),
            placeholder = { Text("给 AI 的要求：例如更简洁、控制在 300 字内", fontSize = 11.sp) },
            textStyle = androidx.compose.ui.text.TextStyle(fontSize = 12.sp, color = Ink),
            singleLine = true,
        )
        Spacer(Modifier.height(Dimens.space2))
        val pending = vm.selectedSuggestion?.get("status").str() == "pending"
        if (pending) {
            Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space2)) {
                AppButton("✓ 接受", onClick = { vm.acceptSuggestion() },
                    kind = AppButtonKind.PRIMARY,
                    enabled = vm.suggestionReady && vm.suggestionText.isNotBlank() &&
                        !vm.suggestionText.contains('\n'))
                AppButton("✗ 拒绝", onClick = { vm.rejectSuggestion() },
                    kind = AppButtonKind.SECONDARY, enabled = vm.suggestionReady)
            }
            Spacer(Modifier.height(Dimens.space2))
            AppLinkButton("重新建议", onClick = { vm.suggestParagraph(regenerate = true) })
        } else {
            // 点 ✎ 不再自动调 AI；由这个按钮显式触发。已采纳/已拒绝的段落同样可以再次优化。
            AppButton("AI优化", onClick = { vm.suggestParagraph(regenerate = true) },
                kind = AppButtonKind.AI, enabled = vm.suggestionReady,
                icon = Icons.Default.AutoAwesome)
        }
    }
}

// ---------------- 助手栏：对话、逐段建议与依据 ----------------

private val QUICK_ACTIONS = listOf(
    Triple("扩写", "expand", "扩写当前内容"),
    Triple("润色", "polish", "润色当前内容"),
    Triple("精简", "condense", "精简当前内容"),
    Triple("规范化", "normalize", "调整为司法行政机关正式材料语言"),
    Triple("补充结构", "complete", "判断当前文档缺少哪些必要部分并补充"),
    Triple("检查问题", "revise", "检查当前文档存在的问题并列出"),
)

@Composable
private fun AssistantPanel(
    vm: WritingViewModel,
    modifier: Modifier,
    selectedTab: Int,
    onTabSelected: (Int) -> Unit,
) {
    var showQuickActions by remember { mutableStateOf(false) }
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
            tabs = listOf("对话", "逐段建议", "依据"),
            selectedIndex = selectedTab,
            onSelect = onTabSelected,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(Dimens.space3))

        when (selectedTab) {
            0 -> {
                AppLinkButton(if (showQuickActions) "收起快捷操作" else "展开快捷操作",
                    onClick = { showQuickActions = !showQuickActions })
                if (showQuickActions) {
                    Column(
                        Modifier.fillMaxWidth().heightIn(max = 260.dp)
                            .verticalScroll(rememberScrollState()),
                        verticalArrangement = Arrangement.spacedBy(Dimens.space2),
                    ) {
                        val actions = vm.spec?.aiActions.orEmpty()
                        if (actions.isNotEmpty()) {
                            SectionTitle("针对本次任务")
                            actions.chunked(2).forEach { row ->
                                Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space2)) {
                                    row.forEach { action ->
                                        Box(Modifier.weight(1f)) {
                                            AiActionChip(action,
                                                onClick = { vm.revise(action, "revise") },
                                                enabled = !vm.busy && vm.hasDraft,
                                                icon = Icons.Default.AutoAwesome)
                                        }
                                    }
                                    if (row.size == 1) Spacer(Modifier.weight(1f))
                                }
                            }
                        }
                        SectionTitle("对当前文档")
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
                        if (!vm.hasDraft) {
                            Text("生成正文后可用这些操作继续打磨", fontSize = 11.5.sp,
                                color = Muted)
                        }
                    }
                }
                LazyColumn(
                    Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(Dimens.space3),
                ) {
                    items(vm.messages) { m ->
                        AiBubble(text = m.content, isUser = m.role == "user",
                            label = vm.spec?.agent?.ifBlank { "助手" } ?: "助手")
                        if (m.revisionSummary.isNotBlank()) {
                            var expanded by remember(m) { mutableStateOf(false) }
                            AppLinkButton(if (expanded) "收起修改详情" else "查看修改详情",
                                onClick = { expanded = !expanded })
                            if (expanded) Text(m.revisionSummary, fontSize = 12.sp, color = Muted)
                        }
                    }
                }
            }
            1 -> {
                ParagraphSuggestionPanel(vm, Modifier.weight(1f))
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
                            onSourceClick = if (vm.referenceItems.isNotEmpty())
                                ({ index -> vm.referenceItems.getOrNull(index)?.let(vm::openReference) })
                            else null,
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

        if (selectedTab == 0) {
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
            }
        }
        WritingStatusLine(vm.status)
    }
    vm.openedReference?.let { reference ->
        AppDialog(
            onDismissRequest = vm::closeReference,
            title = reference.title,
            subtitle = "知识库原文 · 按当前账号权限读取",
            width = 820.dp,
            actions = { AppButton("关闭", onClick = vm::closeReference,
                kind = AppButtonKind.SECONDARY) },
        ) {
            Text(
                when {
                    vm.referenceLoading -> "正在读取原文…"
                    vm.referenceError != null -> vm.referenceError.orEmpty()
                    else -> vm.openedReferenceDocument?.get("content").str()
                        .ifBlank { "暂无可展示的原文" }
                },
                fontSize = 13.sp, color = Ink, lineHeight = 21.sp,
            )
        }
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
