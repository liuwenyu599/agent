package com.judicialai.desktop.features.writing

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Button
import androidx.compose.material.Checkbox
import androidx.compose.material.Divider
import androidx.compose.material.Icon
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedButton
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Switch
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Send
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.core.platform.pickFiles
import com.judicialai.desktop.core.platform.pickSaveFile
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.components.AppCard
import com.judicialai.desktop.design.components.ErrorText

private val EpPrimary = Color(0xFF2F54EB)
private val OkGreen = Color(0xFF2E7D32)
private val WarnOrange = Color(0xFFF9A825)
private val BadRed = Color(0xFFC62828)
private val TextSecondary = Color(0xFF6B7280)
private val Pending = "待补充"

/** 智能写作工作台：一个持续的 Writing Task（对话 + 文档 + 版本）。 */
@Composable
fun WritingScreen() {
    val vm = remember { WritingViewModel(Repositories.writing) }

    if (!vm.hasTask) {
        EntryView(vm)
        return
    }

    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        ErrorText(vm.status)
        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            TaskPanel(vm, Modifier.width(280.dp).fillMaxHeight())
            EditorPanel(vm, Modifier.weight(1f).fillMaxHeight())
            AssistantPanel(vm, Modifier.width(300.dp).fillMaxHeight())
        }
    }
}

// ---------------- 零门槛入口 ----------------

@Composable
private fun EntryView(vm: WritingViewModel) {
    androidx.compose.runtime.LaunchedEffect(Unit) {
        com.judicialai.desktop.app.AppState.pendingWritingIntent?.let {
            vm.entryInput = it
            com.judicialai.desktop.app.AppState.pendingWritingIntent = null
            vm.startFromIntent()
        }
    }
    Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center) {
        Text("今天想写什么？", fontSize = 26.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(6.dp))
        Text("一句话告诉我即可，文种、依据、框架由系统逐步引导补全",
            fontSize = 13.sp, color = TextSecondary)
        Spacer(Modifier.height(20.dp))
        OutlinedTextField(
            vm.entryInput, { vm.entryInput = it },
            placeholder = { Text("例如：帮我写一份 2026 年度司法行政工作总结") },
            modifier = Modifier.fillMaxWidth(0.6f),
            enabled = !vm.busy,
        )
        Spacer(Modifier.height(12.dp))
        Button(onClick = { vm.startFromIntent() },
            enabled = !vm.busy && vm.entryInput.isNotBlank()) {
            Text(if (vm.busy) "系统处理中…" else "开始写作")
        }
        vm.status?.let {
            Spacer(Modifier.height(8.dp))
            Text(it, fontSize = 12.sp, color = BadRed)
        }
    }
}

// ---------------- 左栏：写作任务状态 ----------------

@Composable
private fun TaskPanel(vm: WritingViewModel, modifier: Modifier) {
    AppCard(modifier) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {

            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("写作任务", fontWeight = FontWeight.Bold, fontSize = 14.sp)
                Spacer(Modifier.weight(1f))
                TextButton(onClick = { vm.newTask() }) { Text("新建任务", fontSize = 11.sp) }
            }

            TaskField("文种", vm.task.documentType, vm) { v -> vm.patchContext(mapOf("document_type" to v)) }
            TaskField("标题", vm.task.title, vm) { v -> vm.patchContext(mapOf("title" to v)) }
            TaskField("主题", vm.task.topic, vm) { v -> vm.patchContext(mapOf("topic" to v)) }
            TaskField("时间", vm.task.timeRange, vm) { v -> vm.patchContext(mapOf("time_range" to v)) }
            TaskField("主送机关", vm.task.recipient, vm) { v -> vm.patchContext(mapOf("recipient" to v)) }
            TaskField("发文机关", vm.task.authority, vm) { v -> vm.patchContext(mapOf("authority" to v)) }
            if (vm.task.keyFacts.isNotEmpty()) {
                Text("主要工作：${vm.task.keyFacts.joinToString("、")}",
                    fontSize = 12.sp)
            }

            // 文号：可选元数据，默认关闭
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("文号", fontSize = 12.sp, color = TextSecondary, modifier = Modifier.width(72.dp))
                Switch(checked = vm.task.documentNumberEnabled,
                    onCheckedChange = { vm.toggleDocNumber(it) })
                Text(if (vm.task.documentNumberEnabled) "启用" else "不使用",
                    fontSize = 12.sp)
            }
            if (vm.task.documentNumberEnabled) {
                OutlinedTextField(
                    vm.task.documentNumber, { vm.setDocNumber(it) },
                    label = { Text("文号（手工填写，系统不编造）") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                )
            }
            if (vm.task.documentDate.isNotBlank()) {
                Text("成文日期：${vm.task.documentDate}", fontSize = 12.sp)
            }

            if (vm.task.missingFields.isNotEmpty()) {
                Divider()
                Text("还需要的信息", fontWeight = FontWeight.Bold, fontSize = 13.sp)
                vm.task.missingFields.forEach {
                    Text("○ $it", fontSize = 12.sp, color = WarnOrange)
                }
            }

            Divider()
            Text("材料", fontWeight = FontWeight.Bold, fontSize = 13.sp)
            OutlinedButton(onClick = { vm.uploadMaterials(pickFiles("选择写作材料", multi = true)) },
                modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(16.dp))
                Text(" 上传 Word / PDF / 图片", fontSize = 12.sp)
            }
            if (vm.materials.isEmpty()) {
                Text("未上传（可先起草，随时补充）", fontSize = 11.sp, color = TextSecondary)
            }
            vm.materials.forEach { a ->
                Text("📄 ${a.name}", fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }

            Spacer(Modifier.height(4.dp))
            if (!vm.hasDraft) {
                Button(onClick = { vm.draft() }, enabled = !vm.busy,
                    modifier = Modifier.fillMaxWidth()) { Text("生成初稿") }
                OutlinedButton(onClick = { vm.draft(outlineOnly = true) }, enabled = !vm.busy,
                    modifier = Modifier.fillMaxWidth()) { Text("先搭框架", fontSize = 12.sp) }
            }
        }
    }
}

/** 可编辑任务字段：失焦/回车由用户点右侧 ✓ 同步后端 */
@Composable
private fun TaskField(label: String, value: String, vm: WritingViewModel,
                      onSync: (String) -> Unit) {
    var editing = androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf<String?>(null) }
    val shown = editing.value ?: value
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, fontSize = 12.sp, color = TextSecondary, modifier = Modifier.width(72.dp))
        OutlinedTextField(
            value = shown,
            onValueChange = { editing.value = it },
            placeholder = { Text(Pending, fontSize = 12.sp, color = TextSecondary) },
            modifier = Modifier.weight(1f).heightIn(max = 46.dp),
            singleLine = true,
            textStyle = MaterialTheme.typography.body2,
        )
        if (editing.value != null && editing.value != value) {
            Text("✓", fontSize = 14.sp, color = EpPrimary,
                modifier = Modifier.clickable {
                    onSync(editing.value ?: "")
                    editing.value = null
                }.padding(4.dp))
        }
    }
}

// ---------------- 中栏：当前文档 ----------------

@Composable
private fun EditorPanel(vm: WritingViewModel, modifier: Modifier) {
    AppCard(modifier) {
        if (!vm.hasDraft) {
            Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center) {
                Text("还没有草稿", fontSize = 16.sp, color = TextSecondary)
                Spacer(Modifier.height(6.dp))
                Text("在右侧告诉 AI「先写一版」，或点击左侧「生成初稿」",
                    fontSize = 12.sp, color = TextSecondary)
            }
            return@AppCard
        }
        Column(Modifier.fillMaxSize()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                // 明确标注：这是初稿，待完善
                Text("V${maxOf(vm.versionNo, 1)} 初稿", fontSize = 11.sp, color = Color.White,
                    modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(WarnOrange)
                        .padding(horizontal = 6.dp, vertical = 2.dp))
                Spacer(Modifier.width(8.dp))
                Text("待完善", fontSize = 11.sp, color = TextSecondary)
                Spacer(Modifier.weight(1f))
                if (vm.task.documentNumberEnabled && vm.task.documentNumber.isNotBlank()) {
                    Text(vm.task.documentNumber, fontSize = 12.sp, color = TextSecondary)
                }
            }
            Spacer(Modifier.height(6.dp))
            if (vm.task.title.isNotBlank()) {
                Text(vm.task.title, fontSize = 18.sp, fontWeight = FontWeight.Bold,
                    modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center)
                Spacer(Modifier.height(6.dp))
            }
            OutlinedTextField(
                vm.content, { vm.content = it },
                modifier = Modifier.fillMaxWidth().weight(1f),
                textStyle = MaterialTheme.typography.body1.copy(lineHeight = 24.sp),
            )
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("字数：约 ${vm.content.length} 字", fontSize = 12.sp, color = TextSecondary)
                Spacer(Modifier.width(12.dp))
                Text("版本：${if (vm.versionNo > 0) "v${vm.versionNo}" else "未保存"}",
                    fontSize = 12.sp, color = TextSecondary)
                Spacer(Modifier.weight(1f))
                Button(onClick = { vm.saveVersion() }, enabled = !vm.busy) {
                    Text("保存版本", fontSize = 12.sp)
                }
            }
        }
    }
}

// ---------------- 右栏：AI 对话 + 依据 + 操作 ----------------

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
    AppCard(modifier) {
        Column(Modifier.fillMaxSize()) {
            Text("AI 助手", fontWeight = FontWeight.Bold, fontSize = 14.sp)
            Spacer(Modifier.height(6.dp))

            // 对话区（持续对话，贯穿任务全程）
            LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                items(vm.messages) { m ->
                    val isUser = m.role == "user"
                    Column(Modifier.fillMaxWidth(),
                        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start) {
                        Box(
                            Modifier.clip(RoundedCornerShape(8.dp))
                                .background(if (isUser) EpPrimary else Color(0xFFF3F4F6))
                                .padding(8.dp),
                        ) {
                            Text(m.content, fontSize = 12.sp,
                                color = if (isUser) Color.White else Color(0xFF111827))
                        }
                    }
                }
                if (vm.busy) {
                    item { Text("AI 处理中…", fontSize = 12.sp, color = TextSecondary) }
                }
            }

            // 快捷操作：全部走当前文档 revision 逻辑
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                QUICK_ACTIONS.take(3).forEach { (label, mode, hint) ->
                    OutlinedButton(onClick = { vm.revise(hint, mode) },
                        enabled = !vm.busy && vm.hasDraft) { Text(label, fontSize = 11.sp) }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                QUICK_ACTIONS.drop(3).forEach { (label, mode, hint) ->
                    OutlinedButton(onClick = { vm.revise(hint, mode) },
                        enabled = !vm.busy && vm.hasDraft) { Text(label, fontSize = 11.sp) }
                }
            }

            // 对话输入：主要操作方式
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    vm.chatInput, { vm.chatInput = it },
                    placeholder = { Text("继续说：把第二部分写详细一点…", fontSize = 12.sp) },
                    modifier = Modifier.weight(1f).heightIn(max = 46.dp),
                    singleLine = true,
                    enabled = !vm.busy,
                    textStyle = MaterialTheme.typography.body2,
                )
                Icon(Icons.Default.Send, contentDescription = "发送",
                    tint = if (vm.chatInput.isBlank() || vm.busy) TextSecondary else EpPrimary,
                    modifier = Modifier.padding(start = 6.dp).size(22.dp)
                        .clickable(enabled = vm.chatInput.isNotBlank() && !vm.busy) { vm.sendChat() })
            }

            // 写作依据
            if (vm.references.isNotEmpty()) {
                Spacer(Modifier.height(6.dp))
                Divider()
                Text("写作依据（${vm.references.size}）", fontWeight = FontWeight.Bold, fontSize = 12.sp)
                vm.references.take(5).forEach {
                    Text("📄 $it", fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }

            // 版本与操作
            if (vm.hasDraft) {
                Spacer(Modifier.height(6.dp))
                Divider()
                if (vm.versions.isNotEmpty()) {
                    Text("历史版本：" + vm.versions.joinToString("  ") { "v${it["version_no"].int()}" },
                        fontSize = 11.sp, color = TextSecondary)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    OutlinedButton(onClick = {
                        pickSaveFile("${vm.task.title.ifBlank { "公文" }}.docx")?.let { vm.export(true, it) }
                    }, enabled = !vm.busy, modifier = Modifier.weight(1f)) { Text("导出 Word", fontSize = 11.sp) }
                    OutlinedButton(onClick = { vm.addToTraining() },
                        enabled = !vm.busy, modifier = Modifier.weight(1f)) { Text("加入训练数据", fontSize = 11.sp) }
                }
            }
        }
    }
}
