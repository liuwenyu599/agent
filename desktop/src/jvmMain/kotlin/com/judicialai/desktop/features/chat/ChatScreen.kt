package com.judicialai.desktop.features.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Icon
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.material.TextFieldDefaults
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Share
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.components.AppButton
import com.judicialai.desktop.design.components.AppButtonKind
import com.judicialai.desktop.design.components.AppDialog
import com.judicialai.desktop.design.components.AppIconButton
import com.judicialai.desktop.design.components.AppTextField
import com.judicialai.desktop.design.components.Hairline
import com.judicialai.desktop.design.components.LoadingBlock
import com.judicialai.desktop.design.components.MarkdownView
import com.judicialai.desktop.design.components.NoticeBar
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Danger
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.LineStrong
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Ok
import com.judicialai.desktop.design.theme.OkSoft
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.PrimarySoft
import com.judicialai.desktop.design.theme.QuickGreen
import com.judicialai.desktop.design.theme.QuickOrange
import com.judicialai.desktop.design.theme.QuickPurple
import com.judicialai.desktop.design.theme.QuickBlue
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.SurfaceTonal
import com.judicialai.desktop.design.theme.Warn
import com.judicialai.desktop.design.theme.WarnSoft
import com.judicialai.desktop.features.chat.model.ChatMessage
import com.judicialai.desktop.features.chat.model.HistoryCategory
import com.judicialai.desktop.features.chat.model.HistoryItem
import java.time.LocalDate
import java.util.prefs.Preferences

private const val HISTORY_TITLE_MAX = 200

private fun categoryColor(c: HistoryCategory): Color = when (c) {
    HistoryCategory.CHAT -> QuickBlue
    HistoryCategory.DOC -> QuickGreen
    HistoryCategory.PPT -> QuickOrange
    HistoryCategory.WORKFLOW -> QuickPurple
}

private fun categoryIcon(c: HistoryCategory): ImageVector = when (c) {
    HistoryCategory.CHAT -> Icons.Default.History
    HistoryCategory.DOC -> Icons.Default.Description
    HistoryCategory.PPT -> Icons.Default.PlayArrow
    HistoryCategory.WORKFLOW -> Icons.Default.Share
}

private data class DayGroup(val label: String, val items: List<HistoryItem>)

private fun groupByDay(items: List<HistoryItem>, newestFirst: Boolean): List<DayGroup> {
    val today = LocalDate.now()
    val dayComparator = if (newestFirst) compareByDescending<String> { it } else compareBy { it }
    return items.groupBy { it.time.take(10) }
        .toSortedMap(dayComparator)
        .map { (day, list) ->
            val d = runCatching { LocalDate.parse(day) }.getOrNull()
            val label = when (d) {
                today -> "今天"
                today.minusDays(1) -> "昨天"
                null -> if (day.isBlank()) "时间未知" else day
                else -> "${d.monthValue}月${d.dayOfMonth}日"
            }
            DayGroup(label, list)
        }
}

@Composable
fun ChatScreen(vm: ChatViewModel = remember { ChatViewModel(Repositories.chat) }) {
    LaunchedEffect(Unit) {
        vm.loadSessions()
        vm.loadHistory(HistoryCategory.CHAT)
        vm.loadHistory(HistoryCategory.DOC)
        vm.loadHistory(HistoryCategory.PPT)
        vm.loadHistory(HistoryCategory.WORKFLOW)
    }

    val historyPrefs = remember(AppState.username) {
        Preferences.userRoot().node("com/judicialai/desktop/history/" +
            AppState.username.ifBlank { "anonymous" })
    }
    var query by remember { mutableStateOf("") }
    var filter by remember { mutableStateOf<HistoryCategory?>(null) }
    val sortPrefKey = "sort." + (filter?.name?.lowercase() ?: "all")
    var sortMode by remember(AppState.username, sortPrefKey) {
        mutableStateOf(historyPrefs.get(sortPrefKey, "newest"))
    }
    var renameTarget by remember { mutableStateOf<HistoryItem?>(null) }
    var deleteTarget by remember { mutableStateOf<HistoryItem?>(null) }
    var viewingChat by remember { mutableStateOf<HistoryItem?>(null) }

    LaunchedEffect(viewingChat?.id) {
        viewingChat?.let { vm.openSession(it.id) }
    }

    val base = if (filter == null) vm.allHistoryItems() else vm.historyItemsOf(filter!!)
    val filteredItems = base.filter {
        query.isBlank() || it.title.contains(query, ignoreCase = true) ||
            it.sub.contains(query, ignoreCase = true)
    }
    val items = when (sortMode) {
        "oldest" -> filteredItems.sortedBy { it.time }
        "title" -> filteredItems.sortedBy { it.title.lowercase() }
        else -> filteredItems.sortedByDescending { it.time }
    }
    val groups = if (sortMode == "title") {
        listOf(DayGroup("按标题排序", items))
    } else {
        groupByDay(items, newestFirst = sortMode != "oldest")
    }

    Column(Modifier.fillMaxSize().background(AppBg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 18.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text("历史记录", fontSize = 21.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                Spacer(Modifier.height(2.dp))
                Text("我生成的对话、文档、PPT 与工作流程，按时间归档",
                    fontSize = 12.5.sp, color = Muted)
            }
            Spacer(Modifier.weight(1f))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                HistoryCategory.values().forEach { c ->
                    StatChip(icon = categoryIcon(c), label = c.label,
                        count = vm.historyCount(c), color = categoryColor(c),
                        selected = filter == c,
                        onClick = { filter = if (filter == c) null else c })
                }
            }
        }

        Row(
            Modifier.fillMaxWidth().padding(horizontal = 24.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                placeholder = { Text("搜索标题或摘要…", fontSize = 13.sp, color = Muted) },
                leadingIcon = {
                    Icon(Icons.Default.Search, contentDescription = null,
                        tint = Muted, modifier = Modifier.size(18.dp))
                },
                singleLine = true,
                shape = RoundedCornerShape(10.dp),
                modifier = Modifier.width(320.dp).height(52.dp),
                colors = TextFieldDefaults.outlinedTextFieldColors(
                    backgroundColor = Surface,
                    focusedBorderColor = Primary,
                    unfocusedBorderColor = Line,
                    cursorColor = Primary),
            )
            Spacer(Modifier.width(14.dp))
            Text(
                if (filter == null) "全部 ${items.size} 条"
                else "${filter?.label ?: ""} ${items.size} 条",
                fontSize = 12.5.sp, color = Muted)
            Spacer(Modifier.weight(1f))
            Text("排序：", fontSize = 12.sp, color = Muted)
            listOf(
                "newest" to "最新优先",
                "oldest" to "最早优先",
                "title" to "标题 A-Z",
            ).forEach { (key, label) ->
                val selected = sortMode == key
                TextButton(onClick = {
                    sortMode = key
                    historyPrefs.put(sortPrefKey, key)
                }) {
                    Text(label, fontSize = 12.sp,
                        color = if (selected) Primary else Ink2,
                        fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal)
                }
            }
        }

        vm.historyMessage?.let { msg ->
            NoticeBar(
                text = msg,
                fg = if (vm.historyMessageError) Warn else Ok,
                bg = if (vm.historyMessageError) WarnSoft else OkSoft,
                modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp),
            )
        }

        Spacer(Modifier.height(10.dp))

        Box(Modifier.weight(1f).fillMaxWidth()) {
            when {
                vm.historyLoading && items.isEmpty() -> LoadingBlock("正在读取记录…")
                items.isEmpty() -> TimelineEmpty(filter, query.isNotBlank())
                else -> LazyColumn(
                    Modifier.fillMaxSize().padding(horizontal = 24.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    groups.forEach { g ->
                        item(key = "day:${g.label}") { DayHeader(g.label) }
                        items(g.items, key = { it.category.name + ":" + it.id }) { item ->
                            TimelineCard(
                                item = item,
                                onOpen = {
                                    when (item.category) {
                                        HistoryCategory.CHAT -> viewingChat = item
                                        else -> vm.openHistoryItem(item)
                                    }
                                },
                                onRename = { renameTarget = item },
                                onDelete = { deleteTarget = item },
                            )
                        }
                    }
                    item { Spacer(Modifier.height(20.dp)) }
                }
            }
        }
    }

    viewingChat?.let { item ->
        ChatViewDialog(item = item, messages = vm.messages, onClose = { viewingChat = null })
    }
    if (vm.openedDoc != null || vm.openedDocLoading) {
        DocPreviewDialog(
            vm,
            onOpenSourceChat = { sessionId, docTitle ->
                viewingChat = HistoryItem(
                    id = sessionId,
                    title = if (docTitle.isBlank()) "生成该文档的对话"
                    else "生成《$docTitle》的对话",
                    category = HistoryCategory.CHAT,
                )
            },
        )
    }
    renameTarget?.let { item ->
        RenameDialog(
            item = item,
            busy = vm.historyBusy,
            onDismiss = { renameTarget = null },
            onConfirm = { title ->
                vm.renameHistory(item, title)
                renameTarget = null
            },
        )
    }
    deleteTarget?.let { item ->
        DeleteConfirmDialog(
            item = item,
            busy = vm.historyBusy,
            onDismiss = { deleteTarget = null },
            onConfirm = {
                vm.deleteHistory(item)
                deleteTarget = null
            },
        )
    }
}

@Composable
private fun StatChip(
    icon: ImageVector, label: String, count: Int, color: Color,
    selected: Boolean, onClick: () -> Unit,
) {
    Row(
        Modifier.clip(RoundedCornerShape(10.dp))
            .background(if (selected) color.copy(alpha = 0.12f) else Surface)
            .border(1.dp, if (selected) color else Line, RoundedCornerShape(10.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(16.dp))
        Text(label, fontSize = 12.5.sp, color = Ink2)
        Text("$count", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = color)
    }
}

@Composable
private fun DayHeader(label: String) {
    Row(
        Modifier.fillMaxWidth().padding(top = 14.dp, bottom = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(Primary))
        Spacer(Modifier.width(8.dp))
        Text(label, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Ink)
        Spacer(Modifier.width(12.dp))
        Box(Modifier.weight(1f).height(1.dp).background(Line))
    }
}

@Composable
private fun TimelineCard(
    item: HistoryItem,
    onOpen: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    val color = categoryColor(item.category)
    val shape = RoundedCornerShape(12.dp)
    Row(
        Modifier.fillMaxWidth()
            .clip(shape)
            .background(Surface)
            .border(1.dp, if (hovered) LineStrong else Line, shape)
            .clickable(interactionSource = interaction, indication = null) { onOpen() }
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(42.dp).clip(RoundedCornerShape(11.dp))
                .background(color.copy(alpha = 0.12f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(categoryIcon(item.category), contentDescription = null, tint = color,
                modifier = Modifier.size(20.dp))
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(item.title.ifBlank { "（未命名）" }, fontSize = 14.5.sp,
                    fontWeight = FontWeight.Medium, color = Ink,
                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false))
                Spacer(Modifier.width(8.dp))
                Box(
                    Modifier.clip(RoundedCornerShape(4.dp))
                        .background(color.copy(alpha = 0.10f))
                        .padding(horizontal = 6.dp, vertical = 2.dp),
                ) {
                    Text(item.category.label, fontSize = 10.5.sp, color = color)
                }
            }
            Spacer(Modifier.height(3.dp))
            Text(
                listOf(item.sub, item.time.take(16).replace("T", " "))
                    .filter { it.isNotBlank() }.joinToString(" · ").ifBlank { "—" },
                fontSize = 12.sp, color = Muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        if (hovered) {
            Spacer(Modifier.width(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                AppIconButton(Icons.AutoMirrored.Filled.ArrowForward,
                    historyOpenLabelOf(item.category), onOpen, tint = Primary, size = 30.dp)
                AppIconButton(Icons.Default.Edit, "重命名", onRename, tint = Ink2, size = 30.dp)
                AppIconButton(Icons.Default.Delete, "删除", onDelete, tint = Danger, size = 30.dp)
            }
        }
    }
}

@Composable
private fun TimelineEmpty(filter: HistoryCategory?, searching: Boolean) {
    Column(
        Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Box(
            Modifier.size(60.dp).clip(CircleShape).background(PrimarySoft),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                if (searching) Icons.Default.Search
                else filter?.let { categoryIcon(it) } ?: Icons.Default.History,
                contentDescription = null, tint = Primary, modifier = Modifier.size(26.dp))
        }
        Spacer(Modifier.height(14.dp))
        Text(
            when {
                searching -> "没有匹配的记录"
                filter != null -> "还没有${filter.label}记录"
                else -> "还没有任何记录"
            },
            fontSize = 14.sp, color = Ink2)
        Spacer(Modifier.height(4.dp))
        Text(
            when {
                searching -> "换个关键词试试"
                else -> "在智能写作、PPT 助手、工作流程中生成的内容会自动归档到这里"
            },
            fontSize = 12.sp, color = Muted)
    }
}

@Composable
private fun ChatViewDialog(
    item: HistoryItem,
    messages: List<ChatMessage>,
    onClose: () -> Unit,
) {
    AppDialog(
        onDismissRequest = onClose,
        title = item.title.ifBlank { "对话记录" },
        subtitle = "对话记录 · 只读回看",
        width = 640.dp,
        actions = {
            AppButton("关闭", onClick = onClose, kind = AppButtonKind.SECONDARY)
        },
    ) {
        if (messages.isEmpty()) {
            Text("正在读取或暂无消息…", fontSize = 12.5.sp, color = Muted)
        } else {
            Column(
                Modifier.fillMaxWidth().heightIn(max = 420.dp)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                messages.forEach { m ->
                    val isUser = m.role == "user"
                    Column(
                        Modifier.fillMaxWidth(),
                        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
                    ) {
                        Text(if (isUser) "我" else "助手", fontSize = 11.sp, color = Muted)
                        Spacer(Modifier.height(3.dp))
                        Box(
                            Modifier.widthIn(max = 460.dp)
                                .clip(RoundedCornerShape(10.dp))
                                .background(if (isUser) Primary else SurfaceTonal)
                                .padding(horizontal = 12.dp, vertical = 8.dp),
                        ) {
                            SelectionContainer {
                                Text(m.content, fontSize = 13.sp, lineHeight = 20.sp,
                                    color = if (isUser) Color.White else Ink)
                            }
                        }
                    }
                }
            }
        }
    }
}

/**
 * 文档内嵌预览。
 *
 * 「继续编辑」优先回**写作台**而不是「我的文档」页：文档绝大多数是写作台起草时
 * 快照下来的，写作台会连同当时的对话一起恢复（正文 + 对话 + 版本链），而文档页
 * 只能改正文、看不到当初那轮对话。服务端在文档上回带了 `task_id`（来源写作任务）
 * 与 `session_id`（来源对话），据此分三档：
 * - 有 task_id → 回写作台继续（正文和对话一起回来）；
 * - 只有 session_id（对话里生成的）→ 就地打开生成它的那轮对话；
 * - 都没有（手工新建等）→ 才退回文档页。
 */
@Composable
private fun DocPreviewDialog(
    vm: ChatViewModel,
    onOpenSourceChat: (String, String) -> Unit,
) {
    val doc = vm.openedDoc
    val taskId = doc?.get("task_id")?.str()?.trim().orEmpty()
    val sessionId = doc?.get("session_id")?.str()?.trim().orEmpty()
    AppDialog(
        onDismissRequest = { vm.closeInlineDoc() },
        title = doc?.get("title")?.str()?.ifBlank { "（未命名文档）" } ?: "文档预览",
        subtitle = listOfNotNull(
            doc?.get("document_number")?.str()?.ifBlank { null },
            doc?.get("updated_at")?.str()?.take(16)?.replace("T", " ")?.ifBlank { null },
        ).joinToString(" · ").ifBlank { "只读预览" },
        width = 720.dp,
        actions = {
            AppButton("关闭", onClick = { vm.closeInlineDoc() },
                kind = AppButtonKind.SECONDARY)
            Spacer(Modifier.width(8.dp))
            AppButton(
                when {
                    taskId.isNotBlank() -> "回到写作台继续 →"
                    sessionId.isNotBlank() -> "查看生成它的对话 →"
                    else -> "前往文档页编辑 →"
                },
                enabled = doc != null,
                onClick = {
                    when {
                        taskId.isNotBlank() -> {
                            // 模板中心「使用模板」的一次性参数会让写作台跳过任务恢复，
                            // 从历史记录进来时必须先清掉，否则打开的是空的入口页。
                            AppState.pendingWritingTemplate = null
                            AppState.pendingWritingIntent = null
                            AppState.pendingWritingTaskId = taskId
                            vm.closeInlineDoc()
                            AppState.navigate(AppScreen.WRITING)
                        }
                        sessionId.isNotBlank() -> {
                            val title = doc?.get("title")?.str().orEmpty()
                            vm.closeInlineDoc()
                            onOpenSourceChat(sessionId, title)
                        }
                        else -> {
                            doc?.get("id")?.str()?.let { AppState.pendingDocumentId = it }
                            vm.closeInlineDoc()
                            AppState.navigate(AppScreen.DOCUMENTS)
                        }
                    }
                },
            )
        },
    ) {
        when {
            vm.openedDocLoading -> LoadingBlock("正在打开文档…")
            doc == null -> Text("文档加载失败或已被删除", fontSize = 13.sp, color = Muted)
            else -> SelectionContainer {
                Column(
                    Modifier.fillMaxWidth().heightIn(max = 440.dp)
                        .verticalScroll(rememberScrollState()),
                ) {
                    MarkdownView(doc["content"].str().ifBlank { "（暂无内容）" })
                }
            }
        }
    }
}

@Composable
private fun RenameDialog(
    item: HistoryItem,
    busy: Boolean,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit,
) {
    var text by remember(item.id) { mutableStateOf(item.title) }
    val name = text.trim()
    val tooLong = name.length > HISTORY_TITLE_MAX
    val invalid = name.isBlank() || tooLong
    AppDialog(
        onDismissRequest = onDismiss,
        title = "重命名",
        subtitle = when (item.category) {
            HistoryCategory.CHAT -> "修改对话标题"
            HistoryCategory.DOC -> "修改文档标题"
            HistoryCategory.PPT -> "修改演示文稿标题"
            HistoryCategory.WORKFLOW -> "修改工作流程名称"
        },
        width = 460.dp,
        actions = {
            AppButton("取消", onClick = onDismiss, kind = AppButtonKind.SECONDARY,
                enabled = !busy)
            Spacer(Modifier.width(8.dp))
            AppButton("确定", onClick = { onConfirm(name) }, enabled = !invalid && !busy,
                loading = busy)
        },
    ) {
        AppTextField(
            value = text,
            onValueChange = { if (it.length <= HISTORY_TITLE_MAX + 20) text = it },
            label = "名称",
            singleLine = true,
            error = invalid && text.isNotBlank(),
            hint = when {
                name.isBlank() -> "名称不能为空"
                tooLong -> "不能超过 ${HISTORY_TITLE_MAX} 字（当前 ${name.length} 字）"
                else -> "≤ ${HISTORY_TITLE_MAX} 字"
            },
        )
    }
}

@Composable
private fun DeleteConfirmDialog(
    item: HistoryItem,
    busy: Boolean,
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
) {
    AppDialog(
        onDismissRequest = onDismiss,
        title = "删除确认",
        subtitle = "删除后不可恢复",
        width = 440.dp,
        actions = {
            AppButton("取消", onClick = onDismiss, kind = AppButtonKind.SECONDARY,
                enabled = !busy)
            Spacer(Modifier.width(8.dp))
            AppButton("确认删除", onClick = onConfirm, kind = AppButtonKind.DANGER,
                enabled = !busy, loading = busy)
        },
    ) {
        NoticeBar(text = "即将删除：${item.title}", fg = Warn, bg = WarnSoft)
        Text(
            when (item.category) {
                HistoryCategory.CHAT -> "该对话的全部消息"
                HistoryCategory.DOC -> "该文档及其全部版本"
                HistoryCategory.PPT -> "该演示文稿"
                HistoryCategory.WORKFLOW -> "该工作流程及其全部节点内容"
            } + "将从你的记录中移除，且无法恢复。",
            fontSize = 12.5.sp, color = Ink2, lineHeight = 18.sp,
        )
    }
}

private fun historyOpenLabelOf(category: HistoryCategory): String = when (category) {
    HistoryCategory.CHAT -> "回看对话"
    HistoryCategory.DOC -> "预览文档"
    HistoryCategory.PPT -> "到 PPT 工作台继续修改"
    HistoryCategory.WORKFLOW -> "打开工作流程"
}
