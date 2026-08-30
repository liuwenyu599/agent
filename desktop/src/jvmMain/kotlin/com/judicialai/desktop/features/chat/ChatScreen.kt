package com.judicialai.desktop.features.chat

import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Card
import androidx.compose.material.Checkbox
import androidx.compose.material.CheckboxDefaults
import androidx.compose.material.CircularProgressIndicator
import androidx.compose.material.Icon
import androidx.compose.material.IconButton
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.material.TextFieldDefaults
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.MailOutline
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Star
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.platform.pickFiles
import com.judicialai.desktop.core.platform.pickSaveFile
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.theme.EpDanger
import com.judicialai.desktop.design.theme.EpPrimary
import com.judicialai.desktop.design.theme.EpPrimaryDark
import com.judicialai.desktop.design.theme.EpSuccess
import com.judicialai.desktop.design.theme.EpWarning
import com.judicialai.desktop.design.theme.HoverBlue
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.SurfaceSoft
import com.judicialai.desktop.design.theme.TextPlaceholder
import com.judicialai.desktop.design.theme.TextPrimary
import com.judicialai.desktop.design.theme.TextRegular
import com.judicialai.desktop.design.theme.TextSecondary
import com.judicialai.desktop.features.chat.model.ChatMessage

/** 智能写作（信息写作）：1:1 还原 Web ChatView.vue */
@Composable
fun ChatScreen(vm: ChatViewModel = remember { ChatViewModel(Repositories.chat) }) {
    LaunchedEffect(Unit) {
        vm.loadSessions()
        // 常用参考模板：按使用频率取前若干（与 Web 一致）
        when (val r = Repositories.templates.list()) {
            is ApiResult.Ok -> vm.loadPopularTemplates(
                r.data.sortedByDescending { it["use_count"].int() }
                    .take(6)
                    .map { (it["id"]?.toString()?.trim('"') ?: "") to
                        (it["name"]?.toString()?.trim('"') ?: "") }
                    .filter { it.first.isNotBlank() }
            )
            is ApiResult.Err -> Unit
        }
    }

    Row(Modifier.fillMaxSize()) {
        // ===== 左侧会话列表（260px，#f5f7fa） =====
        Column(Modifier.width(260.dp).fillMaxHeight().background(SurfaceSoft)) {
            Row(
                Modifier.fillMaxWidth().height(60.dp).background(Surface)
                    .padding(horizontal = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Default.Edit, contentDescription = null,
                    tint = TextPrimary, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text("信息写作", fontSize = 16.sp, fontWeight = FontWeight.SemiBold,
                    color = TextPrimary, modifier = Modifier.weight(1f))
                Button(
                    onClick = { vm.newSession() },
                    colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary),
                    shape = RoundedCornerShape(6.dp),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(
                        horizontal = 10.dp, vertical = 4.dp),
                ) {
                    Icon(Icons.Default.Add, contentDescription = null,
                        tint = Color.White, modifier = Modifier.size(14.dp))
                    Text("新对话", color = Color.White, fontSize = 12.sp)
                }
            }
            Box(Modifier.fillMaxWidth().height(1.dp).background(Color(0xFFE4E7ED)))
            LazyColumn(Modifier.weight(1f).padding(8.dp)) {
                items(vm.sessions, key = { it.id }) { s ->
                    val active = vm.currentSessionId == s.id
                    var hovered by remember { mutableStateOf(false) }
                    Row(
                        Modifier.fillMaxWidth().padding(bottom = 4.dp)
                            .clip(RoundedCornerShape(8.dp))
                            .background(if (active) EpPrimary else Color.Transparent)
                            .clickable { vm.openSession(s.id) }
                            .padding(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(s.title, fontSize = 14.sp, fontWeight = FontWeight.Medium,
                                color = if (active) Color.White else TextPrimary,
                                maxLines = 1, overflow = TextOverflow.Ellipsis)
                            if (s.createdAt.isNotBlank()) {
                                Text(s.createdAt.take(16).replace("T", " "),
                                    fontSize = 12.sp,
                                    color = if (active) Color.White.copy(alpha = 0.7f)
                                    else TextSecondary)
                            }
                        }
                        IconButton(onClick = { vm.deleteSession(s) },
                            modifier = Modifier.size(24.dp)) {
                            Icon(Icons.Default.Delete, contentDescription = "删除会话",
                                tint = if (active) Color.White else TextPlaceholder,
                                modifier = Modifier.size(16.dp))
                        }
                    }
                }
                if (vm.sessions.isEmpty()) {
                    item {
                        Box(Modifier.fillMaxWidth().padding(32.dp),
                            contentAlignment = Alignment.Center) {
                            Text("暂无会话", color = TextSecondary, fontSize = 13.sp)
                        }
                    }
                }
            }
        }

        // ===== 右侧聊天区 =====
        Column(Modifier.weight(1f).fillMaxHeight().background(Color(0xFFF5F5F5))) {
            Box(Modifier.weight(1f).fillMaxWidth()) {
                if (vm.messages.isEmpty()) {
                    WelcomePanel(vm)
                } else {
                    MessageList(vm)
                }
            }
            InputArea(vm)
        }
    }
}

/** 欢迎页：标题 + 四张快捷卡片 + 常用参考模板 */
@Composable
private fun WelcomePanel(vm: ChatViewModel) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(40.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text("信息写作", fontSize = 24.sp, color = TextPrimary, fontWeight = FontWeight.Medium)
        Spacer(Modifier.height(8.dp))
        Text("直接说出您的需求，或上传材料，AI 会判断信息是否足够并协助完成写作",
            fontSize = 14.sp, color = TextSecondary)
        Spacer(Modifier.height(30.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            ActionCard("自由写作", "如：帮我写一篇新闻稿 / 把这个材料整理成简报",
                Icons.Default.Edit, EpSuccess, Modifier.weight(1f)) { }
            ActionCard("公文助手", "通知、请示、报告等结构化公文写作",
                Icons.Default.Star, EpPrimary, Modifier.weight(1f)) {
                AppState.screen = com.judicialai.desktop.app.AppScreen.TEMPLATES
            }
            ActionCard("根据材料写", "上传 Word/PDF/图片，AI 基于材料起草",
                Icons.Default.MailOutline, EpWarning, Modifier.weight(1f)) {
                vm.upload(pickFiles("选择材料（Word/PDF/图片）", multi = true))
            }
            ActionCard("知识库", "管理单位文档，写作时自动检索引用",
                Icons.Default.List, TextSecondary, Modifier.weight(1f)) {
                AppState.screen = com.judicialai.desktop.app.AppScreen.KNOWLEDGE
            }
        }
        if (vm.popularTemplates.isNotEmpty()) {
            Spacer(Modifier.height(30.dp))
            Text("常用参考模板（点击后在对话中作为写作参考）：", fontSize = 14.sp,
                color = TextSecondary)
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                vm.popularTemplates.take(6).forEach { t ->
                    Box(
                        Modifier.clip(RoundedCornerShape(6.dp))
                            .background(HoverBlue)
                            .clickable { vm.selectReferenceTemplate(t) }
                            .padding(horizontal = 16.dp, vertical = 8.dp),
                    ) {
                        Text(t.second, color = EpPrimary, fontSize = 13.sp)
                    }
                }
            }
        }
    }
}

@Composable
private fun ActionCard(
    title: String, desc: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    color: Color, modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    Card(
        modifier = modifier.clip(RoundedCornerShape(8.dp)).clickable(onClick = onClick),
        elevation = 2.dp, backgroundColor = Surface,
    ) {
        Column(
            Modifier.padding(24.dp).fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(32.dp))
            Spacer(Modifier.height(12.dp))
            Text(title, fontSize = 16.sp, color = TextPrimary, fontWeight = FontWeight.Medium)
            Spacer(Modifier.height(8.dp))
            Text(desc, fontSize = 13.sp, color = TextSecondary,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        }
    }
}

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
        items(vm.messages) { msg -> MessageBubble(msg, vm) }
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
private fun MessageBubble(msg: ChatMessage, vm: ChatViewModel) {
    val isUser = msg.role == "user"
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
                }
            }
        }
        Spacer(Modifier.width(12.dp))
        if (isUser) AvatarBox(EpPrimaryDark, "我")
    }
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

