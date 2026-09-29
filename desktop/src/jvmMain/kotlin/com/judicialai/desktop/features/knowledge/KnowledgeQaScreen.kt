package com.judicialai.desktop.features.knowledge

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.input.key.*
import androidx.compose.ui.unit.dp
import com.judicialai.desktop.app.LocalAwtWindow
import com.judicialai.desktop.core.platform.pickFiles
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.components.AppDialog
import com.judicialai.desktop.design.components.MarkdownView
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
                Text(it, color = MaterialTheme.colors.error, style = MaterialTheme.typography.caption)
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
                OutlinedTextField(
                    value = input,
                    onValueChange = { input = it },
                    placeholder = { Text("输入问题；也可拖拽文件或 Ctrl+V 粘贴文件/图片") },
                    modifier = Modifier.weight(1f).heightIn(min = 56.dp, max = 120.dp),
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
    var newestFirst by remember { mutableStateOf(true) }
    val visibleSessions = if (newestFirst) vm.sessions
        else vm.sessions.sortedBy { it.createdAt }
    Column(Modifier.width(240.dp).fillMaxHeight()
        .background(MaterialTheme.colors.surface).padding(12.dp)) {
        Button(onClick = vm::newSession, modifier = Modifier.fillMaxWidth()) { Text("＋ 新建问答") }
        Spacer(Modifier.height(12.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("问答记录", style = MaterialTheme.typography.subtitle2,
                modifier = Modifier.weight(1f))
            TextButton(onClick = { newestFirst = true }) {
                Text("最新", color = if (newestFirst) MaterialTheme.colors.primary
                    else MaterialTheme.colors.onSurface.copy(alpha = 0.55f))
            }
            TextButton(onClick = { newestFirst = false }) {
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
    Column(
        Modifier.fillMaxWidth()
            .background(
                if (assistant) MaterialTheme.colors.surface
                else MaterialTheme.colors.primary.copy(alpha = 0.07f),
                RoundedCornerShape(10.dp))
            .border(1.dp, MaterialTheme.colors.onSurface.copy(alpha = 0.08f),
                RoundedCornerShape(10.dp))
            .padding(12.dp),
    ) {
        Text(if (assistant) "知识助手" else "我", style = MaterialTheme.typography.caption)
        Spacer(Modifier.height(5.dp))
        if (assistant) MarkdownView(msg.content) else Text(msg.content)
        if (msg.attachments.isNotEmpty()) {
            Spacer(Modifier.height(6.dp))
            Text("附件：" + msg.attachments.joinToString("、") { it.name },
                style = MaterialTheme.typography.caption)
        }
        if (msg.citations.isNotEmpty()) {
            Spacer(Modifier.height(10.dp))
            Text("引用", style = MaterialTheme.typography.subtitle2)
            Spacer(Modifier.height(4.dp))
            Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                msg.citations.forEachIndexed { index, c ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clickable { onCitation(c) }
                            .background(MaterialTheme.colors.primary.copy(alpha = 0.05f),
                                RoundedCornerShape(7.dp))
                            .padding(8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Default.Description, null, tint = MaterialTheme.colors.primary)
                        Spacer(Modifier.width(6.dp))
                        Column(Modifier.weight(1f)) {
                            Text("[${index + 1}] ${c.docTitle.ifBlank { c.source }}",
                                style = MaterialTheme.typography.body2)
                            Text("${kbTypeLabel(c.kbType)} · ${c.kbName.ifBlank { "知识库" }} · 第${c.chunkIndex}段",
                                style = MaterialTheme.typography.caption)
                        }
                        Text("查看原文 →", style = MaterialTheme.typography.caption,
                            color = MaterialTheme.colors.primary)
                    }
                }
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

@Composable
private fun HighlightedDocument(text: String, excerpt: String) {
    val needle = excerpt.trim().replace(Regex("\\s+"), " ").take(80)
    val blocks = text.split(Regex("\\n\\s*\\n"))
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        blocks.forEach { block ->
            val normalized = block.trim().replace(Regex("\\s+"), " ")
            val hit = needle.isNotBlank() && (
                normalized.contains(needle, ignoreCase = true) ||
                    needle.take(40).let { it.isNotBlank() && normalized.contains(it, ignoreCase = true) }
            )
            Box(
                Modifier.fillMaxWidth()
                    .background(
                        if (hit) MaterialTheme.colors.primary.copy(alpha = 0.12f)
                        else androidx.compose.ui.graphics.Color.Transparent,
                        RoundedCornerShape(6.dp),
                    )
                    .padding(if (hit) 8.dp else 0.dp),
            ) {
                MarkdownView(block)
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
