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
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Card
import androidx.compose.material.Checkbox
import androidx.compose.material.CheckboxDefaults
import androidx.compose.material.CircularProgressIndicator
import androidx.compose.material.Icon
import androidx.compose.material.AlertDialog
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.material.TextFieldDefaults
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Send
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
import com.judicialai.desktop.core.platform.pickFiles
import com.judicialai.desktop.core.platform.pickSaveFile
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.components.AppButton
import com.judicialai.desktop.design.components.AppButtonKind
import com.judicialai.desktop.design.components.AppButtonSize
import com.judicialai.desktop.design.components.AppDialog
import com.judicialai.desktop.design.components.AppIconButton
import com.judicialai.desktop.design.components.AppSegmentedTabs
import com.judicialai.desktop.design.components.AppTextField
import com.judicialai.desktop.design.components.Hairline
import com.judicialai.desktop.design.components.LoadingBlock
import com.judicialai.desktop.design.components.NoticeBar
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Danger
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.EpDanger
import com.judicialai.desktop.design.theme.EpPrimary
import com.judicialai.desktop.design.theme.EpPrimaryDark
import com.judicialai.desktop.design.theme.EpSuccess
import com.judicialai.desktop.design.theme.HoverBlue
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Ok
import com.judicialai.desktop.design.theme.OkSoft
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.PrimarySoft
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.SurfaceDeep
import com.judicialai.desktop.design.theme.SurfaceTonal
import com.judicialai.desktop.design.theme.TextPrimary
import com.judicialai.desktop.design.theme.TextRegular
import com.judicialai.desktop.design.theme.TextSecondary
import com.judicialai.desktop.design.theme.Warn
import com.judicialai.desktop.design.theme.WarnSoft
import com.judicialai.desktop.features.chat.model.ChatMessage
import com.judicialai.desktop.features.chat.model.HistoryCategory
import com.judicialai.desktop.features.chat.model.HistoryItem

/**
 * 历史记录：左列（对话 / 文档 / PPT / 工作流 四类，可继续 · 重命名 · 删除）
 * + 右侧区（打开会话后继续聊；打开文档时内嵌查看正文，不离开本入口）。
 * 右侧不再放「信息写作」快启面板，无会话时只给一句引导。
 */
@Composable
fun ChatScreen(vm: ChatViewModel = remember { ChatViewModel(Repositories.chat) }) {
    LaunchedEffect(Unit) {
        vm.loadSessions()
        // 历史记录：对话 / 文档 / PPT / 工作流 四类各自读取（后端按当前登录用户过滤）
        vm.loadHistory(HistoryCategory.CHAT)
        vm.loadHistory(HistoryCategory.DOC)
        vm.loadHistory(HistoryCategory.PPT)
        vm.loadHistory(HistoryCategory.WORKFLOW)
    }

    var renameTarget by remember { mutableStateOf<HistoryItem?>(null) }
    var deleteTarget by remember { mutableStateOf<HistoryItem?>(null) }

    Row(Modifier.fillMaxSize()) {
        // ===== 左侧记录列：对话 / 文档 / PPT / 工作流，可继续 · 重命名 · 删除 =====
        Column(Modifier.width(300.dp).fillMaxHeight().background(SurfaceDeep)) {
            Row(
                Modifier.fillMaxWidth().height(60.dp).background(Surface)
                    .padding(horizontal = Dimens.space5),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("历史记录", fontSize = 16.sp, fontWeight = FontWeight.SemiBold,
                    color = Ink, modifier = Modifier.weight(1f))
                AppButton(
                    text = "新对话",
                    onClick = { vm.newSession() },
                    icon = Icons.Default.Add,
                    size = AppButtonSize.SM,
                )
            }
            Hairline()
            // 历史记录分类：对话 / 文档 / PPT / 工作流，全部为「我生成的」内容
            AppSegmentedTabs(
                tabs = HistoryCategory.values().map { it.label },
                selectedIndex = vm.historyCategory.ordinal,
                onSelect = { vm.selectHistoryCategory(HistoryCategory.values()[it]) },
                modifier = Modifier.fillMaxWidth()
                    .padding(horizontal = Dimens.space4, vertical = Dimens.space3),
            )
            Box(Modifier.weight(1f).fillMaxWidth()) {
                when {
                    vm.historyLoading -> LoadingBlock("正在读取记录…")
                    vm.historyItems().isEmpty() -> HistoryEmptyState(vm.historyCategory)
                    else -> LazyColumn(
                        Modifier.fillMaxSize()
                            .padding(horizontal = Dimens.space4, vertical = Dimens.space2),
                        verticalArrangement = Arrangement.spacedBy(Dimens.space2),
                    ) {
                        items(vm.historyItems(), key = { it.category.name + ":" + it.id }) { item ->
                            HistoryRow(
                                item = item,
                                selected = item.category == HistoryCategory.CHAT &&
                                    vm.currentSessionId == item.id,
                                onOpen = { vm.openHistoryItem(item) },
                                onRename = { renameTarget = item },
                                onDelete = { deleteTarget = item },
                            )
                        }
                    }
                }
            }
        }
        Box(Modifier.width(1.dp).fillMaxHeight().background(Line))

        // ===== 右侧：打开会话继续对话；打开文档时内嵌查看（不离开历史记录入口） =====
        Column(Modifier.weight(1f).fillMaxHeight().background(AppBg)) {
            vm.historyMessage?.let { msg ->
                NoticeBar(
                    text = msg,
                    fg = if (vm.historyMessageError) Warn else Ok,
                    bg = if (vm.historyMessageError) WarnSoft else OkSoft,
                    modifier = Modifier.padding(Dimens.space4),
                )
            }
            Box(Modifier.weight(1f).fillMaxWidth()) {
                when {
                    vm.openedDoc != null || vm.openedDocLoading -> InlineDocView(vm)
                    vm.messages.isEmpty() -> EmptyChatHint()
                    else -> MessageList(vm)
                }
            }
            // 文档内嵌查看时隐藏对话输入区，避免「对着文档说话」的错觉
            if (vm.openedDoc == null && !vm.openedDocLoading) {
                InputArea(vm)
            }
        }
    }

    // 重命名 / 删除：两个确认弹窗都挂在页面层，行内只负责触发
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

/** 记录行：类型图标 + 标题 + 副信息，hover / 选中时显示「继续 / 重命名 / 删除」 */
@Composable
private fun HistoryRow(
    item: HistoryItem,
    selected: Boolean,
    onOpen: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()
    val shape = RoundedCornerShape(Dimens.radiusMd)
    Row(
        Modifier.fillMaxWidth()
            .clip(shape)
            .background(if (selected) PrimarySoft else if (hovered) SurfaceTonal else Surface)
            .border(1.dp, if (selected) Primary else Line, shape)
            .clickable(interactionSource = interaction, indication = null) { onOpen() }
            .padding(horizontal = Dimens.space3, vertical = Dimens.space3),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(34.dp).clip(RoundedCornerShape(Dimens.radiusSm))
                .background(if (selected) PrimarySoft else SurfaceTonal),
            contentAlignment = Alignment.Center,
        ) {
            Icon(historyIconOf(item.category), contentDescription = null, tint = Primary,
                modifier = Modifier.size(Dimens.iconMd))
        }
        Spacer(Modifier.width(Dimens.space3))
        Column(Modifier.weight(1f)) {
            Text(item.title, fontSize = 13.5.sp, fontWeight = FontWeight.Medium, color = Ink,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.height(2.dp))
            Text(historySubOf(item), fontSize = 11.5.sp, color = Muted,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        if (hovered || selected) {
            Spacer(Modifier.width(Dimens.space2))
            Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space1)) {
                AppIconButton(Icons.AutoMirrored.Filled.ArrowForward, historyOpenLabelOf(item.category),
                    onOpen, tint = Primary, size = 28.dp)
                AppIconButton(Icons.Default.Edit, "重命名", onRename, tint = Ink2, size = 28.dp)
                AppIconButton(Icons.Default.Delete, "删除", onDelete, tint = Danger, size = 28.dp)
            }
        }
    }
}

/** 分类空态：图标 + 一句引导，而不是干巴巴的「暂无」 */
@Composable
private fun HistoryEmptyState(category: HistoryCategory) {
    Column(
        Modifier.fillMaxSize().padding(Dimens.space6),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Box(
            Modifier.size(52.dp).clip(CircleShape).background(PrimarySoft),
            contentAlignment = Alignment.Center,
        ) {
            Icon(historyIconOf(category), contentDescription = null, tint = Primary,
                modifier = Modifier.size(Dimens.iconLg))
        }
        Spacer(Modifier.height(Dimens.space3))
        Text(
            when (category) {
                HistoryCategory.CHAT -> "还没有对话记录"
                HistoryCategory.DOC -> "还没有生成过文档"
                HistoryCategory.PPT -> "还没有生成过 PPT"
                HistoryCategory.WORKFLOW -> "还没有发起过工作流"
            },
            fontSize = 13.sp, color = Ink2,
        )
        Spacer(Modifier.height(Dimens.space1))
        Text(
            when (category) {
                HistoryCategory.CHAT -> "点右上角「新对话」开始，记录会出现在这里"
                HistoryCategory.DOC -> "在「智能写作」中生成后会出现在这里"
                HistoryCategory.PPT -> "在「PPT 助手」中生成后会出现在这里"
                HistoryCategory.WORKFLOW -> "在「科室空间 · 工作流」中创建后会出现在这里"
            },
            fontSize = 11.5.sp, color = Muted)
    }
}

/** 右栏空态：极简一句话引导，不再放快启卡片 */
@Composable
private fun EmptyChatHint() {
    Column(
        Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Box(
            Modifier.size(56.dp).clip(CircleShape).background(PrimarySoft),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Default.History, contentDescription = null, tint = Primary,
                modifier = Modifier.size(Dimens.iconLg))
        }
        Spacer(Modifier.height(Dimens.space4))
        Text("从左侧选择一条记录继续，或点「新对话」开始", fontSize = 14.sp, color = Ink2)
        Spacer(Modifier.height(Dimens.space1))
        Text("文档在历史记录内直接打开；PPT 跳到工作台继续对话修改；工作流跳到「科室空间 · 工作流」",
            fontSize = 12.sp, color = Muted)
    }
}

/**
 * 文档内嵌查看：点文档不离开历史记录入口，左侧仍可切换其他记录。
 * 只读查看正文；需要编辑/存版本/导出时再带 id 跳「我的文档」页。
 */
@Composable
private fun InlineDocView(vm: ChatViewModel) {
    val doc = vm.openedDoc
    Column(Modifier.fillMaxSize().padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { vm.closeInlineDoc() }) {
                Text("← 返回对话区", color = EpPrimary, fontSize = 13.sp)
            }
            Spacer(Modifier.weight(1f))
            if (doc != null) {
                Button(
                    onClick = {
                        // 带 id 跳文档页：DocumentsScreen 消费后直接打开这一条进入编辑
                        AppState.pendingDocumentId = doc["id"].str()
                        AppState.navigate(AppScreen.DOCUMENTS)
                    },
                    colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary),
                    shape = RoundedCornerShape(6.dp),
                ) { Text("前往文档页编辑 →", color = Color.White, fontSize = 12.sp) }
            }
        }
        when {
            vm.openedDocLoading -> LoadingBlock("正在打开文档…")
            doc == null -> Text("文档加载失败或已被删除", fontSize = 13.sp, color = Muted)
            else -> {
                Text(doc["title"].str().ifBlank { "（未命名文档）" },
                    fontSize = 17.sp, fontWeight = FontWeight.Bold, color = Ink)
                val meta = listOf(
                    doc["document_number"].str(),
                    doc["updated_at"].str().take(16).replace("T", " "),
                ).filter { it.isNotBlank() }.joinToString(" · ")
                if (meta.isNotBlank()) Text(meta, fontSize = 12.sp, color = Muted)
                Hairline()
                SelectionContainer {
                    Text(
                        doc["content"].str().ifBlank { "（暂无内容）" },
                        fontSize = 14.sp, lineHeight = 24.sp, color = TextPrimary,
                        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()),
                    )
                }
            }
        }
    }
}

/** 重命名弹窗：非空、≤200 字校验，超限/为空时确定禁用并给出提示 */
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
            HistoryCategory.WORKFLOW -> "修改工作流名称"
        },
        width = 460.dp,
        actions = {
            AppButton("取消", onClick = onDismiss, kind = AppButtonKind.SECONDARY,
                enabled = !busy)
            Spacer(Modifier.width(Dimens.space2))
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

/** 删除二次确认：明确告知删除对象与不可恢复 */
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
            Spacer(Modifier.width(Dimens.space2))
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
                HistoryCategory.WORKFLOW -> "该工作流及其全部节点内容"
            } + "将从你的记录中移除，且无法恢复。",
            fontSize = 12.5.sp, color = Ink2, lineHeight = 18.sp,
        )
    }
}

private fun historyIconOf(category: HistoryCategory): ImageVector = when (category) {
    HistoryCategory.CHAT -> Icons.Default.History
    HistoryCategory.DOC -> Icons.Default.Description
    HistoryCategory.PPT -> Icons.Default.PlayArrow
    HistoryCategory.WORKFLOW -> Icons.Default.Share
}

/** 「继续」按钮的说明文案：如实写明每类的打开方式 */
private fun historyOpenLabelOf(category: HistoryCategory): String = when (category) {
    HistoryCategory.CHAT -> "继续对话"
    HistoryCategory.DOC -> "在这里打开这条文档"
    HistoryCategory.PPT -> "打开这条 PPT 继续修改"
    HistoryCategory.WORKFLOW -> "打开工作流"
}

private fun historySubOf(item: HistoryItem): String =
    listOf(item.sub, item.time.take(16).replace("T", " "))
        .filter { it.isNotBlank() }
        .joinToString(" · ")
        .ifBlank { "—" }

/** 消息列表：用户右侧蓝气泡，助手左侧白气泡 + 回答依据 + 操作 */
@Composable
private fun MessageList(vm: ChatViewModel) {
    val listState = rememberLazyListState()
    LaunchedEffect(vm.messages.size) {
        if (vm.messages.isNotEmpty()) listState.animateScrollToItem(vm.messages.size - 1)
    }
    LazyColumn(
        state = listState,
        modifier = Modifier.fillMaxSize().padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        itemsIndexed(vm.messages) { i, msg ->
            // 该条 AI 回复对应的用户原始需求（向前找最近一条 user 消息）
            val userRequest = if (msg.role != "user")
                vm.messages.subList(0, i).lastOrNull { it.role == "user" }?.content ?: ""
            else ""
            MessageBubble(msg, vm, userRequest)
        }
        if (vm.sending) {
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Box(Modifier.size(36.dp).clip(CircleShape).background(Color(0xFF26A269)),
                        contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(color = Color.White, strokeWidth = 2.dp,
                            modifier = Modifier.size(18.dp))
                    }
                    Card(shape = RoundedCornerShape(8.dp), elevation = 1.dp) {
                        Text("正在生成，请稍候…", fontSize = 14.sp, color = TextSecondary,
                            modifier = Modifier.padding(15.dp))
                    }
                }
            }
        }
    }
}

@Composable
private fun MessageBubble(msg: ChatMessage, vm: ChatViewModel, userRequest: String = "") {
    val isUser = msg.role == "user"
    var addToTrainingFor by remember { mutableStateOf<ChatMessage?>(null) }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        if (!isUser) AvatarBox(Color(0xFF26A269), "AI")
        Spacer(Modifier.width(12.dp))
        Column(
            Modifier.widthIn(max = 560.dp),
            horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(if (isUser) "我" else "助手", fontSize = 12.sp,
                    color = TextSecondary)
            }
            Spacer(Modifier.height(4.dp))
            Card(
                shape = RoundedCornerShape(8.dp), elevation = 1.dp,
                backgroundColor = if (isUser) EpPrimaryDark else Surface,
            ) {
                Column(Modifier.padding(15.dp)) {
                    if (msg.attachments.isNotEmpty()) {
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp),
                            modifier = Modifier.padding(bottom = 8.dp)) {
                            msg.attachments.forEach { a ->
                                Box(Modifier.clip(RoundedCornerShape(4.dp))
                                    .background(Color.White.copy(alpha = 0.2f))
                                    .padding(horizontal = 8.dp, vertical = 3.dp)) {
                                    Text(a.name + if (a.failed) "（解析失败）" else "",
                                        fontSize = 11.sp, color = Color.White)
                                }
                            }
                        }
                    }
                    Text(
                        msg.content,
                        fontSize = 15.sp,
                        lineHeight = 27.sp,
                        color = if (isUser) Color.White else TextPrimary,
                    )
                    if (!isUser && msg.qualityLevel != null) {
                        Spacer(Modifier.height(10.dp))
                        val levelColor = when (msg.qualityLevel) {
                            "A" -> Color(0xFF2E7D32)
                            "B" -> Color(0xFFF9A825)
                            else -> Color(0xFFC62828)
                        }
                        Row(verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("质检 ${msg.qualityLevel}", fontSize = 11.sp,
                                color = Color.White,
                                modifier = Modifier.clip(RoundedCornerShape(4.dp))
                                    .background(levelColor)
                                    .padding(horizontal = 6.dp, vertical = 2.dp))
                            if (msg.qualityIssues.isNotEmpty()) {
                                Text("${msg.qualityIssues.size} 项提示", fontSize = 12.sp,
                                    color = TextSecondary)
                            }
                            if (msg.documentId != null) {
                                Text("已存草稿", fontSize = 12.sp, color = EpPrimary)
                            }
                        }
                        msg.qualityIssues.take(3).forEach {
                            Text("· $it", fontSize = 12.sp, color = TextSecondary,
                                maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        if (msg.unverifiedCitations.isNotEmpty()) {
                            Text("内容核查未核实：${msg.unverifiedCitations.take(3).joinToString("、")}",
                                fontSize = 12.sp, color = Color(0xFFC62828),
                                maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                    }
                    if (!isUser && msg.sources.isNotEmpty()) {
                        Spacer(Modifier.height(12.dp))
                        Box(Modifier.fillMaxWidth().height(1.dp)
                            .background(Color(0xFFE0E0E0)))
                        Spacer(Modifier.height(8.dp))
                        Text("回答依据", fontSize = 12.sp, color = TextSecondary,
                            fontWeight = FontWeight.SemiBold)
                        msg.sources.forEachIndexed { i, s ->
                            Row(Modifier.padding(vertical = 3.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Box(Modifier.size(20.dp).clip(CircleShape)
                                    .background(EpPrimary),
                                    contentAlignment = Alignment.Center) {
                                    Text("${i + 1}", fontSize = 11.sp, color = Color.White)
                                }
                                Text(s, fontSize = 13.sp, color = EpPrimary,
                                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                        }
                    }
                }
            }
            if (!isUser) {
                Row {
                    TextButton(onClick = {
                        val target = pickSaveFile("写作结果.docx") ?: return@TextButton
                        vm.export(mapOf("title" to "写作结果", "content" to msg.content),
                            redHeader = false, target = target)
                    }) { Text("生成 Word", fontSize = 12.sp, color = EpPrimary) }
                    TextButton(onClick = {
                        val target = pickSaveFile("公文.docx") ?: return@TextButton
                        vm.export(mapOf("title" to "公文", "content" to msg.content),
                            redHeader = true, target = target)
                    }) { Text("红头导出", fontSize = 12.sp, color = EpPrimary) }
                    TextButton(onClick = { addToTrainingFor = msg }) {
                        Text("加入训练集", fontSize = 12.sp, color = EpSuccess)
                    }
                }
            }
        }
        Spacer(Modifier.width(12.dp))
        if (isUser) AvatarBox(EpPrimaryDark, "我")
    }

    addToTrainingFor?.let {
        AddToTrainingDialog(vm, it.content, userRequest) { addToTrainingFor = null }
    }
}

@Composable
private fun AddToTrainingDialog(vm: ChatViewModel, draft: String, userRequest: String,
                                onClose: () -> Unit) {
    var instruction by remember { mutableStateOf(userRequest) }
    var output by remember { mutableStateOf(draft) }
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text("加入训练集") },
        text = {
            Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("将本次写作结果加入候选训练数据，审核通过后才参与训练。请把「最终定稿」修改为你认可的版本。",
                    fontSize = 12.sp, color = TextSecondary)
                OutlinedTextField(instruction, { instruction = it },
                    label = { Text("你的原始需求") }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(output, { output = it },
                    label = { Text("最终定稿（AI 初稿基础上修改）") },
                    modifier = Modifier.fillMaxWidth().height(220.dp))
            }
        },
        confirmButton = {
            Button(onClick = {
                if (instruction.isNotBlank() && output.isNotBlank()) {
                    vm.addToTraining(instruction, draft, output)
                }
                onClose()
            }, colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary)) {
                Text("加入训练集", color = Color.White)
            }
        },
        dismissButton = { TextButton(onClick = onClose) { Text("取消") } },
    )
}

@Composable
private fun AvatarBox(color: Color, label: String) {
    Box(Modifier.size(36.dp).clip(CircleShape).background(color),
        contentAlignment = Alignment.Center) {
        Text(label, color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.Bold)
    }
}

/** 输入区：参考模板条 + 待发附件 + 输入框 + 上传/RAG/发送 */
@Composable
private fun InputArea(vm: ChatViewModel) {
    var text by remember { mutableStateOf("") }
    Column(Modifier.fillMaxWidth().background(Surface).padding(20.dp)) {
        vm.referenceTemplate?.let { rt ->
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                modifier = Modifier.padding(bottom = 10.dp)) {
                Box(Modifier.clip(RoundedCornerShape(4.dp))
                    .background(EpSuccess.copy(alpha = 0.12f))
                    .padding(horizontal = 10.dp, vertical = 4.dp)) {
                    Text("参考模板：${rt.second}", fontSize = 12.sp, color = EpSuccess)
                }
                Text("仅作为写作参考，您仍可直接对话", fontSize = 12.sp, color = TextSecondary)
                Text("×", fontSize = 14.sp, color = TextSecondary,
                    modifier = Modifier.clip(CircleShape)
                        .clickable { vm.clearReferenceTemplate() }.padding(4.dp))
            }
        }
        if (vm.attachments.isNotEmpty()) {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp),
                modifier = Modifier.padding(bottom = 10.dp)) {
                vm.attachments.forEach { a ->
                    Box(Modifier.clip(RoundedCornerShape(4.dp))
                        .background(if (a.failed) EpDanger.copy(alpha = 0.12f)
                        else HoverBlue)
                        .clickable { vm.removeAttachment(a) }
                        .padding(horizontal = 10.dp, vertical = 4.dp)) {
                        Text(a.name + "  ×", fontSize = 12.sp,
                            color = if (a.failed) EpDanger else EpPrimary)
                    }
                }
            }
        }
        OutlinedTextField(
            value = text,
            onValueChange = { text = it },
            placeholder = {
                Text("请输入您的写作需求，例如：帮我写一篇关于社区矫正宣传的信息稿…",
                    color = TextSecondary, fontSize = 14.sp)
            },
            modifier = Modifier.fillMaxWidth().heightIn(min = 80.dp),
            colors = TextFieldDefaults.outlinedTextFieldColors(
                focusedBorderColor = EpPrimary, cursorColor = EpPrimary),
        )
        Spacer(Modifier.height(10.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { vm.upload(pickFiles("上传附件", multi = true)) }) {
                Text("📎 上传附件", color = TextRegular, fontSize = 13.sp)
            }
            Spacer(Modifier.width(16.dp))
            Checkbox(checked = vm.useRag, onCheckedChange = { vm.useRag = it },
                colors = CheckboxDefaults.colors(checkedColor = EpPrimary))
            Text("检索知识库", fontSize = 13.sp, color = TextRegular)
            Spacer(Modifier.weight(1f))
            vm.status?.let {
                Text(it, fontSize = 12.sp, color = TextSecondary)
                Spacer(Modifier.width(12.dp))
            }
            val writingIntent = listOf("写", "起草", "撰写", "拟").any { text.contains(it) } &&
                listOf("通知", "总结", "报告", "请示", "函", "讲话", "方案").any { text.contains(it) }
            if (writingIntent) {
                TextButton(onClick = {
                    AppState.pendingWritingIntent = text
                    AppState.navigate(AppScreen.WRITING)
                    text = ""
                }) { Text("进入写作工作台 →", fontSize = 12.sp) }
            }
            Button(
                onClick = { vm.send(text); text = "" },
                enabled = !vm.sending && text.isNotBlank(),
                colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary),
                shape = RoundedCornerShape(6.dp),
            ) {
                Icon(Icons.Default.Send, contentDescription = null,
                    tint = Color.White, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(6.dp))
                Text("发送", color = Color.White)
            }
        }
    }
}
