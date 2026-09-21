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
import com.judicialai.desktop.design.theme.Accent
import com.judicialai.desktop.design.theme.EpPrimary
import com.judicialai.desktop.design.theme.TextSecondary
import com.judicialai.desktop.design.theme.Warn

private val Pending = "待补充"

/** 智能写作：任务入口 → AI 规划 → 针对本次任务的三栏工作台。 */
@Composable
fun WritingScreen() {
    val vm = remember { WritingViewModel(Repositories.writing) }

    if (!vm.hasTask) {
        TaskEntryScreen(vm)
        return
    }

    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        ErrorText(vm.status)
        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            // 左栏：有 AI 规划结果时按本次任务渲染，否则回退后端 task_context 字段面板
            if (vm.spec != null) {
                SpecPanel(vm, Modifier.width(290.dp).fillMaxHeight())
            } else {
                TaskPanel(vm, Modifier.width(280.dp).fillMaxHeight())
            }
            EditorPanel(vm, Modifier.weight(1f).fillMaxHeight())
            AssistantPanel(vm, Modifier.width(300.dp).fillMaxHeight())
        }
    }
}

// ---------------- 零门槛入口 ----------------

/**
 * 任务入口：第一屏克制，只有一句话输入 + 常见目标。
 * 提交后由 AI 做任务规划（文种 / 目标 / 材料 / 知识需求 / 模板），
 * 生成 WorkspaceSpec 后再进入针对本次写作的三栏工作台。
 */
@Composable
private fun TaskEntryScreen(vm: WritingViewModel) {
    androidx.compose.runtime.LaunchedEffect(Unit) {
        com.judicialai.desktop.app.AppState.pendingWritingIntent?.let {
            vm.entryInput = it
            com.judicialai.desktop.app.AppState.pendingWritingIntent = null
            vm.planAndStart()
        }
    }

    Column(
        Modifier.fillMaxSize().background(com.judicialai.desktop.design.theme.HomeBg)
            .padding(horizontal = 40.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text("${com.judicialai.desktop.app.AppState.displayName}，今天你想做什么？",
            fontSize = 26.sp, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(8.dp))
        Text("用一句话描述这次写作任务，系统会为你构造本次写作所需的工作环境",
            fontSize = 13.sp, color = TextSecondary)

        Spacer(Modifier.height(28.dp))
        // 大输入框
        Column(
            Modifier.fillMaxWidth(0.62f)
                .clip(RoundedCornerShape(16.dp))
                .background(Color.White)
                .padding(14.dp),
        ) {
            OutlinedTextField(
                vm.entryInput, { vm.entryInput = it },
                placeholder = { Text("描述你要完成的工作……", fontSize = 14.sp, color = TextSecondary) },
                modifier = Modifier.fillMaxWidth().height(84.dp),
                enabled = !vm.busy,
                maxLines = 4,
            )
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("文种、材料、知识范围与模板由 AI 自动规划", fontSize = 11.5.sp,
                    color = TextSecondary, modifier = Modifier.weight(1f))
                Button(
                    onClick = { vm.planAndStart() },
                    enabled = !vm.busy && vm.entryInput.isNotBlank(),
                    shape = RoundedCornerShape(12.dp),
                ) { Text(if (vm.planning) "规划中…" else "规划并开始 →") }
            }
        }

        Spacer(Modifier.height(16.dp))
        // 常见目标
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            listOf(
                "起草通知" to "起草一份关于行政复议案件办理时限的通知",
                "撰写报告" to "根据本月工作材料撰写一份向区政府报送的工作情况报告",
                "根据材料成文" to "根据这份会议材料整理一份会议纪要",
                "其他" to "",
            ).forEach { (label, text) ->
                Box(
                    Modifier.clip(RoundedCornerShape(999.dp))
                        .background(Color.White)
                        .clickable { vm.entryInput = text }
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                ) { Text(label, fontSize = 12.5.sp, color = com.judicialai.desktop.design.theme.Ink2) }
            }
        }

        Spacer(Modifier.height(18.dp))
        // 上下文条：科室 / Agent / 知识范围（真实取自后端，缺失则不显示）
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically) {
            ContextTag("当前科室：${com.judicialai.desktop.app.AppState.departmentName.ifBlank { "未设置" }}")
            ContextTag("可用知识：全局公共 + 本科室")
        }

        if (vm.planning) {
            Spacer(Modifier.height(22.dp))
            Column(
                Modifier.fillMaxWidth(0.62f).clip(RoundedCornerShape(16.dp))
                    .background(Color.White).padding(18.dp),
            ) {
                Text("AI 正在规划本次写作工作台", fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(8.dp))
                listOf(
                    "理解任务语义与写作目标",
                    "识别文种、报送对象与使用场景",
                    "匹配参考材料与知识来源（受科室权限约束）",
                    "确定模板并生成左栏参数",
                ).forEachIndexed { i, s ->
                    Row(Modifier.padding(vertical = 3.dp)) {
                        Text("${i + 1}", fontSize = 11.sp, color = com.judicialai.desktop.design.theme.Primary)
                        Spacer(Modifier.width(8.dp))
                        Text(s, fontSize = 12.5.sp, color = TextSecondary)
                    }
                }
            }
        }

        vm.planError?.let {
            Spacer(Modifier.height(16.dp))
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("任务规划不可用：$it", fontSize = 12.sp, color = Warn)
                Spacer(Modifier.height(6.dp))
                TextButton(onClick = { vm.startWithoutPlan() }) { Text("不规划，直接开始写作") }
            }
        }
        vm.status?.let {
            Spacer(Modifier.height(10.dp))
            Text(it, fontSize = 12.sp, color = Accent)
        }
    }
}

@Composable
private fun ContextTag(text: String) {
    Box(
        Modifier.clip(RoundedCornerShape(8.dp)).background(Color.White)
            .padding(horizontal = 10.dp, vertical = 5.dp),
    ) { Text(text, fontSize = 12.sp, color = com.judicialai.desktop.design.theme.Ink2) }
}

/**
 * 动态左栏：本次写作的参数由 AI 规划结果决定。
 * 换一个任务，左栏就变成那一类公文真正需要的分区（如会议纪要 → 参会信息 / 时间地点）。
 */
@Composable
private fun SpecPanel(vm: WritingViewModel, modifier: Modifier) {
    val spec = vm.spec ?: return
    AppCard(modifier) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("本次写作", fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f))
                TextButton(onClick = { vm.backToEntry() }) { Text("重新描述", fontSize = 11.5.sp) }
            }
            if (spec.agent.isNotBlank()) {
                Text(spec.agent, fontSize = 11.sp, color = TextSecondary)
            }
            Spacer(Modifier.height(6.dp))

            // 任务要素（文种 / 报送对象 / …）
            if (spec.docType.isNotBlank()) SpecRow("文种", spec.docType)
            if (spec.audience.isNotBlank()) SpecRow("报送对象", spec.audience)
            if (spec.target.isNotBlank()) SpecRow("写作目标", spec.target)
            spec.fields.forEach { SpecRow(it.label, it.value.ifBlank { Pending }) }

            // 参考材料
            if (spec.materials.isNotEmpty()) {
                Spacer(Modifier.height(14.dp))
                Text("参考材料", fontSize = 11.5.sp, color = TextSecondary,
                    fontWeight = FontWeight.SemiBold)
                spec.materials.forEach { opt ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clickable(enabled = opt.note.isBlank()) { vm.toggleMaterial(opt) }
                            .padding(vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Checkbox(checked = opt.selected,
                            onCheckedChange = { if (opt.note.isBlank()) vm.toggleMaterial(opt) },
                            modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text(opt.label, fontSize = 12.sp, modifier = Modifier.weight(1f),
                            maxLines = 1, overflow = TextOverflow.Ellipsis)
                        if (opt.note.isNotBlank()) Text(opt.note, fontSize = 10.5.sp, color = Warn)
                    }
                }
            }

            // 知识来源（后端按权限下发的候选项）
            if (spec.knowledge.isNotEmpty()) {
                Spacer(Modifier.height(14.dp))
                Text("知识来源", fontSize = 11.5.sp, color = TextSecondary,
                    fontWeight = FontWeight.SemiBold)
                spec.knowledge.forEach { opt ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clickable(enabled = opt.note.isBlank()) { vm.toggleKnowledge(opt) }
                            .padding(vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            Modifier.size(14.dp).clip(RoundedCornerShape(999.dp))
                                .background(
                                    if (opt.selected) com.judicialai.desktop.design.theme.Ok
                                    else com.judicialai.desktop.design.theme.Line,
                                ),
                        )
                        Spacer(Modifier.width(8.dp))
                        Text(opt.label, fontSize = 12.sp, modifier = Modifier.weight(1f),
                            maxLines = 1, overflow = TextOverflow.Ellipsis)
                        if (opt.note.isNotBlank()) Text(opt.note, fontSize = 10.5.sp, color = Warn)
                    }
                }
                if (spec.scopes.isNotEmpty()) {
                    Spacer(Modifier.height(6.dp))
                    Text("检索范围：" + spec.scopes.joinToString(" + "),
                        fontSize = 10.5.sp, color = TextSecondary)
                }
            }

            // 模板
            if (spec.templateName.isNotBlank()) {
                Spacer(Modifier.height(14.dp))
                Text("模板", fontSize = 11.5.sp, color = TextSecondary,
                    fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(6.dp))
                Row(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
                        .background(com.judicialai.desktop.design.theme.HomeBg)
                        .clickable { com.judicialai.desktop.app.AppState.navigate(
                            com.judicialai.desktop.app.AppScreen.TEMPLATES) }
                        .padding(horizontal = 10.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(spec.templateName, fontSize = 12.sp, modifier = Modifier.weight(1f),
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text("切换", fontSize = 11.sp, color = TextSecondary)
                }
            }

            if (spec.source == "rule") {
                Spacer(Modifier.height(12.dp))
                Text("本次规划由规则降级生成（模型不可用），结构可能较简略",
                    fontSize = 10.5.sp, color = Warn)
            }
        }
    }
}

@Composable
private fun SpecRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
        Text(label, fontSize = 11.5.sp, color = TextSecondary, modifier = Modifier.width(76.dp))
        Text(value, fontSize = 12.sp, modifier = Modifier.weight(1f),
            maxLines = 2, overflow = TextOverflow.Ellipsis)
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
                    Text("○ $it", fontSize = 12.sp, color = Warn)
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
                    modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(Warn)
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

            // AI 针对本次任务给出的动作（来自规划结果，逐条走后端 revision 接口）
            val actions = vm.spec?.aiActions.orEmpty()
            if (actions.isNotEmpty() && vm.hasDraft) {
                Text("当前任务", fontSize = 11.sp, color = TextSecondary)
                Spacer(Modifier.height(4.dp))
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    actions.chunked(2).forEach { row ->
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            row.forEach { a ->
                                OutlinedButton(
                                    onClick = { vm.revise(a, "revise") },
                                    enabled = !vm.busy,
                                    modifier = Modifier.weight(1f).height(34.dp),
                                ) { Text(a, fontSize = 11.5.sp, maxLines = 1) }
                            }
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))
            }

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
