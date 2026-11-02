package com.judicialai.desktop.features.knowledge

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.key.*
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.LocalAwtWindow
import com.judicialai.desktop.core.platform.pickFiles
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.components.AppDialog
import com.judicialai.desktop.design.components.AppTextField
import com.judicialai.desktop.design.components.ChatBubble
import com.judicialai.desktop.design.components.DocumentBodyView
import com.judicialai.desktop.design.components.MarkdownView
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.PrimarySoft
import com.judicialai.desktop.design.theme.TextSecondary
import com.judicialai.desktop.features.chat.model.ChatAttachment
import com.judicialai.desktop.features.chat.model.ChatMessage
import com.judicialai.desktop.features.chat.model.KnowledgeCitation
import java.awt.Graphics2D
import java.awt.Toolkit
import java.awt.datatransfer.DataFlavor
import java.awt.datatransfer.Transferable
import java.awt.dnd.DnDConstants
import java.awt.dnd.DropTarget
import java.awt.dnd.DropTargetAdapter
import java.awt.dnd.DropTargetDropEvent
import java.awt.image.BufferedImage
import java.io.File
import java.util.prefs.Preferences
import javax.imageio.ImageIO

@OptIn(ExperimentalComposeUiApi::class)
@Composable
fun KnowledgeQaScreen(
    vm: KnowledgeQaViewModel = remember {
        KnowledgeQaViewModel(Repositories.knowledge, Repositories.chat)
    },
) {
    LaunchedEffect(Unit) { vm.loadSessions() }
    var input by remember { mutableStateOf("") }

    val awtWindow = LocalAwtWindow.current
    DisposableEffect(awtWindow) {
        if (awtWindow == null) return@DisposableEffect onDispose { }
        val previous = awtWindow.dropTarget
        val target = DropTarget(
            awtWindow,
            DnDConstants.ACTION_COPY,
            object : DropTargetAdapter() {
                override fun drop(event: DropTargetDropEvent) {
                    val files = filesFromTransferable(event.transferable)
                    if (files.isEmpty()) {
                        event.rejectDrop()
                        return
                    }
                    event.acceptDrop(DnDConstants.ACTION_COPY)
                    vm.upload(files)
                    event.dropComplete(true)
                }
            },
            true,
        )
        awtWindow.dropTarget = target
        onDispose {
            if (awtWindow.dropTarget === target) awtWindow.dropTarget = previous
        }
    }

    Row(
        Modifier.fillMaxSize()
            .background(com.judicialai.desktop.design.theme.AppBg)
            .onPreviewKeyEvent {
                if (it.type == KeyEventType.KeyDown && it.isCtrlPressed && it.key == Key.V) {
                    val files = clipboardFiles()
                    if (files.isNotEmpty()) {
                        vm.upload(files)
                        true
                    } else false
                } else false
            },
    ) {
        QaSessionSidebar(vm)
        Column(Modifier.weight(1f).fillMaxHeight().padding(20.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("知识库问答", style = MaterialTheme.typography.h5)
                    Text("检索范围：公共知识库 + 本科室知识库 + 本人知识库",
                        style = MaterialTheme.typography.caption)
                }
                TextButton(onClick = { vm.loadSessions() }) {
                    Icon(Icons.Default.Refresh, null)
                    Spacer(Modifier.width(4.dp))
                    Text("刷新会话")
                }
            }

            Spacer(Modifier.height(12.dp))
            Card(Modifier.weight(1f).fillMaxWidth(), elevation = 1.dp) {
                if (vm.messages.isEmpty()) {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text("可直接提问，也可以附带图片或文档")
                            Spacer(Modifier.height(6.dp))
                            Text("图片由视觉模型理解；文档先解析文本，再结合知识库回答。",
                                style = MaterialTheme.typography.caption)
                        }
                    }
                } else {
                    LazyColumn(
                        Modifier.fillMaxSize().padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        items(vm.messages) { msg -> QaMessageCard(msg, vm::openCitation) }
                    }
                }
            }

            vm.status?.let {
                Spacer(Modifier.height(8.dp))
                Text(it, color = if (vm.sending) MaterialTheme.colors.primary
                                 else MaterialTheme.colors.error,
                    style = MaterialTheme.typography.caption)
            }

            if (vm.attachments.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    vm.attachments.forEach { a -> AttachmentChip(a, vm::removeAttachment) }
                }
            }

            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.Bottom) {
                OutlinedButton(
                    enabled = !vm.uploading && !vm.sending,
                    onClick = {
                        val files = pickFiles("选择图片或文档（png/jpg/doc/docx/pdf/xlsx）", multi = true)
                        if (files.isNotEmpty()) vm.upload(files)
                    },
                ) {
                    Icon(Icons.Default.AttachFile, null)
                    Spacer(Modifier.width(4.dp))
                    Text(if (vm.uploading) "上传中…" else "附件")
                }
                Spacer(Modifier.width(8.dp))
                AppTextField(
                    value = input,
                    onValueChange = { input = it },
                    label = "问题",
                    placeholder = "输入问题；也可拖拽文件或 Ctrl+V 粘贴文件/图片",
                    modifier = Modifier.weight(1f),
                    singleLine = false,
                    minLines = 2,
                    maxLines = 4,
                    enabled = !vm.sending,
                )
                Spacer(Modifier.width(8.dp))
                Button(
                    enabled = input.isNotBlank() && !vm.sending,
                    onClick = {
                        val q = input
                        input = ""
                        vm.send(q)
                    },
                    modifier = Modifier.height(56.dp),
                ) {
                    if (vm.sending) CircularProgressIndicator(
                        modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                    else Text("发送")
                }
            }
            Spacer(Modifier.height(4.dp))
            Text("支持：按钮选择、资源管理器拖拽、Ctrl+V 粘贴；png/jpg/doc/docx/pdf/xlsx",
                style = MaterialTheme.typography.caption)
        }
    }

    vm.openedCitation?.let { citation ->
        CitationDialog(citation, vm.openedDocument, vm.documentLoading, vm::closeCitation)
    }
}

@Composable
private fun QaSessionSidebar(vm: KnowledgeQaViewModel) {
    val prefs = remember(com.judicialai.desktop.app.AppState.username) {
        Preferences.userRoot().node(
            "com/judicialai/desktop/knowledge-qa/" +
                com.judicialai.desktop.app.AppState.username.ifBlank { "anonymous" }
        )
    }
    var newestFirst by remember(com.judicialai.desktop.app.AppState.username) {
        mutableStateOf(prefs.get("sort", "newest") != "oldest")
    }
    val visibleSessions = if (newestFirst) vm.sessions
        else vm.sessions.sortedBy { it.createdAt }
    Column(Modifier.width(240.dp).fillMaxHeight()
        .background(MaterialTheme.colors.surface).padding(12.dp)) {
        Button(onClick = vm::newSession, modifier = Modifier.fillMaxWidth()) { Text("＋ 新建问答") }
        Spacer(Modifier.height(12.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("问答记录", style = MaterialTheme.typography.subtitle2,
                modifier = Modifier.weight(1f))
            TextButton(onClick = {
                newestFirst = true
                prefs.put("sort", "newest")
            }) {
                Text("最新", color = if (newestFirst) MaterialTheme.colors.primary
                    else MaterialTheme.colors.onSurface.copy(alpha = 0.55f))
            }
            TextButton(onClick = {
                newestFirst = false
                prefs.put("sort", "oldest")
            }) {
                Text("最早", color = if (!newestFirst) MaterialTheme.colors.primary
                    else MaterialTheme.colors.onSurface.copy(alpha = 0.55f))
            }
        }
        Spacer(Modifier.height(6.dp))
        LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(visibleSessions, key = { it.id }) { s ->
                val selected = s.id == vm.currentSessionId
                Row(
                    Modifier.fillMaxWidth()
                        .background(
                            if (selected) MaterialTheme.colors.primary.copy(alpha = 0.08f)
                            else MaterialTheme.colors.surface,
                            RoundedCornerShape(8.dp))
                        .clickable { vm.openSession(s.id) }
                        .padding(10.dp),
                ) {
                    Column {
                        Text(s.title, maxLines = 2, style = MaterialTheme.typography.body2)
                        if (s.createdAt.isNotBlank()) Text(
                            s.createdAt.take(16).replace("T", " "),
                            style = MaterialTheme.typography.caption)
                    }
                }
            }
        }
    }
}

@Composable
private fun QaMessageCard(msg: ChatMessage, onCitation: (KnowledgeCitation) -> Unit) {
    val assistant = msg.role == "assistant"
    ChatBubble(
        isUser = !assistant,
        label = if (assistant) "知识助手" else "我",
        // 助手气泡要容得下引用列表，比普通对话放宽一些
        maxWidth = if (assistant) 620.dp else 460.dp,
    ) {
        Column {
            if (assistant) {
                MarkdownView(msg.content)
            } else {
                SelectionContainer {
                    Text(msg.content, fontSize = 13.sp, lineHeight = 20.sp, color = Color.White)
                }
            }
            if (msg.attachments.isNotEmpty()) {
                Spacer(Modifier.height(6.dp))
                Text("附件：" + msg.attachments.joinToString("、") { it.name },
                    style = MaterialTheme.typography.caption,
                    color = if (assistant) TextSecondary else Color.White.copy(alpha = 0.75f))
            }
            if (msg.citations.isNotEmpty()) {
                CitationList(msg.citations, assistant, onCitation)
            }
        }
    }
}

/**
 * 引用来源区：与正文用分隔线隔开并带独立小标题。
 *
 * 引用是「答案的依据」，必须让用户在视觉上一眼看出它不属于回答正文，
 * 否则会误以为模型在正文里啰嗦地报出处。
 */
@Composable
private fun CitationList(
    citations: List<KnowledgeCitation>,
    assistant: Boolean,
    onCitation: (KnowledgeCitation) -> Unit,
) {
    Spacer(Modifier.height(10.dp))
    Divider(color = Line)
    Spacer(Modifier.height(8.dp))
    Text(
        "引用来源（${citations.size}）",
        fontSize = 11.5.sp,
        color = if (assistant) Ink2 else Color.White.copy(alpha = 0.75f),
    )
    Spacer(Modifier.height(6.dp))
    Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
        citations.forEachIndexed { index, c ->
            val interaction = remember { MutableInteractionSource() }
            val hovered by interaction.collectIsHoveredAsState()
            Row(
                Modifier.fillMaxWidth()
                    .clip(RoundedCornerShape(7.dp))
                    .background(
                        if (assistant) PrimarySoft else Color.White.copy(alpha = 0.10f),
                        RoundedCornerShape(7.dp),
                    )
                    .border(
                        1.dp,
                        if (hovered) Primary.copy(alpha = 0.55f) else Color.Transparent,
                        RoundedCornerShape(7.dp),
                    )
                    .clickable(interactionSource = interaction, indication = null) {
                        onCitation(c)
                    }
                    .padding(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Default.Description, null, tint = Primary,
                    modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(6.dp))
                Column(Modifier.weight(1f)) {
                    Text("[${index + 1}] ${c.docTitle.ifBlank { c.source }}",
                        fontSize = 12.5.sp, color = if (assistant) Ink else Color.White)
                    Text("${kbTypeLabel(c.kbType)} · ${c.kbName.ifBlank { "知识库" }} · 第${c.chunkIndex}段",
                        style = MaterialTheme.typography.caption,
                        color = if (assistant) Ink2 else Color.White.copy(alpha = 0.7f))
                }
                Text("查看原文 →", style = MaterialTheme.typography.caption, color = Primary)
            }
        }
    }
}

@Composable
private fun AttachmentChip(a: ChatAttachment, onRemove: (ChatAttachment) -> Unit) {
    Row(
        Modifier.background(MaterialTheme.colors.primary.copy(alpha = 0.06f), RoundedCornerShape(8.dp))
            .padding(horizontal = 8.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(a.name, style = MaterialTheme.typography.caption)
        Spacer(Modifier.width(4.dp))
        Icon(Icons.Default.Close, contentDescription = "移除",
            modifier = Modifier.size(16.dp).clickable { onRemove(a) })
    }
}

@Composable
private fun CitationDialog(
    citation: KnowledgeCitation,
    document: kotlinx.serialization.json.JsonObject?,
    loading: Boolean,
    onClose: () -> Unit,
) {
    AppDialog(
        onDismissRequest = onClose,
        title = citation.docTitle.ifBlank { citation.source },
        subtitle = "${kbTypeLabel(citation.kbType)} · ${citation.kbName.ifBlank { "知识库" }} · 第${citation.chunkIndex}段",
        width = 820.dp,
        actions = { TextButton(onClick = onClose) { Text("关闭") } },
    ) {
        if (loading) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                Spacer(Modifier.width(8.dp))
                Text("正在读取原文…")
            }
        } else {
            if (citation.excerpt.isNotBlank()) {
                Text("命中段落", style = MaterialTheme.typography.subtitle2)
                Spacer(Modifier.height(4.dp))
                Box(Modifier.fillMaxWidth()
                    .background(MaterialTheme.colors.primary.copy(alpha = 0.10f), RoundedCornerShape(8.dp))
                    .padding(10.dp)) {
                    Text(citation.excerpt, style = MaterialTheme.typography.body2)
                }
                Spacer(Modifier.height(10.dp))
            }
            Text("原文", style = MaterialTheme.typography.subtitle2)
            Spacer(Modifier.height(4.dp))
            Column(Modifier.fillMaxWidth().heightIn(max = 520.dp)
                .verticalScroll(rememberScrollState())) {
                HighlightedDocument(
                    text = document?.get("content").str().ifBlank { "暂无可展示原文" },
                    excerpt = citation.excerpt,
                )
            }
        }
    }
}

/**
 * 按段落切分原文并高亮命中片段。
 *
 * 块内渲染改用 [DocumentBodyView]：知识库原文是 docx/pdf 抽取的纯文本，
 * 用 MarkdownView 等于铺一屏没结构的字。同一个问题此前已在知识库文档查看处修过，
 * 这里是同一条链路的下游。
 */
@Composable
private fun HighlightedDocument(text: String, excerpt: String) {
    val needle = excerpt.trim().replace(Regex("\\s+"), " ").take(80)
    val blocks = text.split(Regex("\\n\\s*\\n"))
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        blocks.forEach { block ->
            val normalized = block.trim().replace(Regex("\\s+"), " ")
            val hit = needle.isNotBlank() && (
                normalized.contains(needle, ignoreCase = true) ||
                    needle.take(40).let { it.isNotBlank() && normalized.contains(it, ignoreCase = true) }
            )
            // 命中与否都要有相同的 padding：原先只有命中块加 padding，
            // 会让相邻段落左边界左右参差，读起来像排版错位。
            Row(Modifier.fillMaxWidth()
                .background(
                    if (hit) PrimarySoft else Color.Transparent,
                    RoundedCornerShape(6.dp))
                .padding(horizontal = 8.dp, vertical = 6.dp)) {
                if (hit) {
                    Box(Modifier.width(3.dp).fillMaxHeight()
                        .background(Primary, RoundedCornerShape(2.dp)))
                    Spacer(Modifier.width(8.dp))
                }
                Box(Modifier.weight(1f)) { DocumentBodyView(block) }
            }
        }
    }
}

private fun kbTypeLabel(type: String): String = when (type.lowercase()) {
    "public" -> "公共库"
    "department" -> "本科室库"
    "personal" -> "个人库"
    else -> "知识库"
}

private fun filesFromTransferable(t: Transferable?): List<File> {
    if (t == null) return emptyList()
    return runCatching {
        if (!t.isDataFlavorSupported(DataFlavor.javaFileListFlavor)) return@runCatching emptyList()
        @Suppress("UNCHECKED_CAST")
        (t.getTransferData(DataFlavor.javaFileListFlavor) as? List<File>)
            .orEmpty().filter(KnowledgeQaViewModel::supported)
    }.getOrDefault(emptyList())
}

private fun clipboardFiles(): List<File> {
    val clipboard = runCatching { Toolkit.getDefaultToolkit().systemClipboard }.getOrNull()
        ?: return emptyList()
    val t = runCatching { clipboard.getContents(null) }.getOrNull() ?: return emptyList()
    val files = filesFromTransferable(t)
    if (files.isNotEmpty()) return files
    if (!t.isDataFlavorSupported(DataFlavor.imageFlavor)) return emptyList()

    return runCatching {
        val image = t.getTransferData(DataFlavor.imageFlavor) as? java.awt.Image
            ?: return@runCatching emptyList<File>()
        val w = image.getWidth(null)
        val h = image.getHeight(null)
        if (w <= 0 || h <= 0) return@runCatching emptyList<File>()
        val buffered = BufferedImage(w, h, BufferedImage.TYPE_INT_ARGB)
        val g: Graphics2D = buffered.createGraphics()
        try { g.drawImage(image, 0, 0, null) } finally { g.dispose() }
        val out = kotlin.io.path.createTempFile("knowledge-paste-", ".png").toFile()
        out.deleteOnExit()
        ImageIO.write(buffered, "png", out)
        listOf(out)
    }.getOrDefault(emptyList())
}
