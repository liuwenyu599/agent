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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Button
import androidx.compose.material.Checkbox
import androidx.compose.material.Divider
import androidx.compose.material.DropdownMenu
import androidx.compose.material.DropdownMenuItem
import androidx.compose.material.Icon
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedButton
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.runtime.Composable
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
import com.judicialai.desktop.core.platform.pickFiles
import com.judicialai.desktop.core.platform.pickSaveFile
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.components.AppCard
import com.judicialai.desktop.design.components.ErrorText

private val EpPrimary = Color(0xFF2F54EB)
private val OkGreen = Color(0xFF2E7D32)
private val WarnOrange = Color(0xFFF9A825)
private val BadRed = Color(0xFFC62828)
private val TextSecondary = Color(0xFF6B7280)

private val STEP_LABELS = listOf("填写需求", "上传材料", "检索依据", "AI 起草", "结果编辑", "导出保存")
private val DOC_TYPES = listOf("通知", "请示", "报告", "工作总结", "函", "讲话稿", "方案")
private val URGENCY = listOf("普通", "加急", "特急")
private val SECRECY = listOf("公开", "内部", "秘密")

/** 智能写作工作台：一句话入口 → 渐进式任务构建 → 起草 → 质检 → 版本 → Word。 */
@Composable
fun WritingScreen() {
    val vm = remember { WritingViewModel(Repositories.writing) }

    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        StepBar(vm.step)
        ErrorText(vm.status)

        Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            LeftPanel(vm, Modifier.width(280.dp).fillMaxHeight())
            CenterPanel(vm, Modifier.weight(1f).fillMaxHeight())
            if (vm.hasDraft) RightPanel(vm, Modifier.width(280.dp).fillMaxHeight())
        }
    }
}

// ---------------- 顶部步骤条 ----------------

@Composable
private fun StepBar(current: Int) {
    AppCard(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            STEP_LABELS.forEachIndexed { i, label ->
                val no = i + 1
                val active = no == current
                val done = no < current
                Box(
                    Modifier.size(24.dp).clip(CircleShape)
                        .background(if (active || done) EpPrimary else Color(0xFFE5E7EB)),
                    contentAlignment = Alignment.Center,
                ) {
                    Text("$no", fontSize = 12.sp,
                        color = if (active || done) Color.White else TextSecondary)
                }
                Text(label, fontSize = 13.sp,
                    fontWeight = if (active) FontWeight.Bold else FontWeight.Normal,
                    color = if (active) EpPrimary else if (done) Color(0xFF111827) else TextSecondary)
                if (no < STEP_LABELS.size) {
                    Box(Modifier.width(16.dp).height(1.dp).background(Color(0xFFD1D5DB)))
                }
            }
        }
    }
}

// ---------------- 左栏：任务要素 ----------------

@Composable
private fun LeftPanel(vm: WritingViewModel, modifier: Modifier) {
    AppCard(modifier) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {

            Text("1. 文档信息", fontWeight = FontWeight.Bold, fontSize = 14.sp)
            DropdownField("文种", vm.docType, DOC_TYPES) { vm.docType = it }
            OutlinedTextField(vm.title, { vm.title = it },
                label = { Text("标题") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(vm.recipient, { vm.recipient = it },
                label = { Text("发文对象（主送机关）") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(vm.authority, { vm.authority = it },
                label = { Text("发文机关（落款）") }, modifier = Modifier.fillMaxWidth())
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Box(Modifier.weight(1f)) { DropdownField("紧急程度", vm.urgency, URGENCY) { vm.urgency = it } }
                Box(Modifier.weight(1f)) { DropdownField("密级", vm.secrecy, SECRECY) { vm.secrecy = it } }
            }

            Divider()
            Text("2. 写作要求", fontWeight = FontWeight.Bold, fontSize = 14.sp)
            OutlinedTextField(
                vm.requirements, { vm.requirements = it },
                label = { Text("如：结合现行政策，明确工作要求，语言正式、结构完整") },
                modifier = Modifier.fillMaxWidth().height(90.dp),
            )

            Divider()
            Text("3. 上传材料（可选）", fontWeight = FontWeight.Bold, fontSize = 14.sp)
            OutlinedButton(onClick = { vm.uploadMaterials(pickFiles("选择写作材料", multi = true)) },
                modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(16.dp))
                Text(" 上传 Word / PDF / 图片")
            }
            vm.attachments.forEach { a ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(a.name, fontSize = 12.sp, maxLines = 1,
                        overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                    Icon(Icons.Default.Close, contentDescription = "移除",
                        modifier = Modifier.size(16.dp).clickable { vm.removeAttachment(a) },
                        tint = TextSecondary)
                }
            }

            Divider()
            Text("4. 高级选项", fontWeight = FontWeight.Bold, fontSize = 14.sp)
            CheckRow("检索知识库（推荐）", vm.useRag) { vm.useRag = it }
            CheckRow("参考相似范文", vm.useSimilar) { vm.useSimilar = it }
            CheckRow("使用模板结构", vm.useTemplate) { vm.useTemplate = it }

            Divider()
            Text("要素完整度", fontWeight = FontWeight.Bold, fontSize = 14.sp)
            vm.completeness().forEach { (label, ok) ->
                Text((if (ok) "✅ " else "⚠️ ") + label + if (ok) "" else "（待补充）",
                    fontSize = 12.sp, color = if (ok) OkGreen else WarnOrange)
            }

            Spacer(Modifier.height(4.dp))
            Button(onClick = { vm.draft() }, enabled = !vm.busy,
                modifier = Modifier.fillMaxWidth()) {
                Text(if (vm.hasDraft) "重新生成" else "AI 起草")
            }
            if (!vm.hasDraft && !vm.hasMaterials) {
                Text("没有材料也可以开始：", fontSize = 12.sp, color = TextSecondary)
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    TextButton(onClick = { vm.draft(outlineOnly = true) }) { Text("先搭框架", fontSize = 12.sp) }
                    TextButton(onClick = { vm.retrieveReferences() }) { Text("从资料库找依据", fontSize = 12.sp) }
                    TextButton(onClick = { vm.uploadMaterials(pickFiles("选择写作材料", multi = true)) }) {
                        Text("补充材料", fontSize = 12.sp)
                    }
                }
            }
        }
    }
}

// ---------------- 中栏：入口 / 编辑器 ----------------

@Composable
private fun CenterPanel(vm: WritingViewModel, modifier: Modifier) {
    AppCard(modifier) {
        if (!vm.hasDraft) {
            // 零门槛入口
            Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center) {
                Text("今天想写什么？", fontSize = 24.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(6.dp))
                Text("一句话告诉我即可，文种、依据、框架由系统逐步补全",
                    fontSize = 13.sp, color = TextSecondary)
                Spacer(Modifier.height(20.dp))
                OutlinedTextField(
                    vm.entryInput, { vm.entryInput = it },
                    placeholder = { Text("例如：帮我写一份 2026 年度司法行政工作总结") },
                    modifier = Modifier.fillMaxWidth(0.8f),
                    enabled = !vm.busy,
                )
                Spacer(Modifier.height(12.dp))
                Button(onClick = { vm.startFromIntent() },
                    enabled = !vm.busy && vm.entryInput.isNotBlank()) {
                    Text(if (vm.busy) "系统处理中…" else "开始写作")
                }
                Spacer(Modifier.height(10.dp))
                Text("也可以在左侧直接填写文档要素后点「AI 起草」",
                    fontSize = 12.sp, color = TextSecondary)
            }
        } else {
            // 公文编辑区
            Column(Modifier.fillMaxSize()) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("公文编辑区", fontWeight = FontWeight.Bold, fontSize = 14.sp)
                    Spacer(Modifier.weight(1f))
                    vm.qualityLevel?.let { QualityBadge(it) }
                }
                Spacer(Modifier.height(6.dp))
                if (vm.title.isNotBlank()) {
                    Text(vm.title, fontSize = 18.sp, fontWeight = FontWeight.Bold,
                        modifier = Modifier.fillMaxWidth(),
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                }
                if (vm.docNumber.isNotBlank()) {
                    Text(vm.docNumber, fontSize = 13.sp, color = TextSecondary,
                        modifier = Modifier.fillMaxWidth(),
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                }
                Spacer(Modifier.height(6.dp))
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
                    TextButton(onClick = { vm.newTask() }) { Text("新建任务", fontSize = 12.sp) }
                }
            }
        }
    }
}

// ---------------- 右栏：状态 / AI 助手 / 依据 / 操作 ----------------

@Composable
private fun RightPanel(vm: WritingViewModel, modifier: Modifier) {
    AppCard(modifier) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {

            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("文档状态", fontWeight = FontWeight.Bold, fontSize = 14.sp)
                Spacer(Modifier.weight(1f))
                Text("生成完成", fontSize = 11.sp, color = Color.White,
                    modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(OkGreen)
                        .padding(horizontal = 6.dp, vertical = 2.dp))
            }
            StatusRow("质量评级", when (vm.qualityLevel) {
                "A" -> "A（优秀）"; "B" -> "B（需人工完善）"; "D" -> "D（需重生成）"; else -> "—"
            }, when (vm.qualityLevel) { "A" -> OkGreen; "B" -> WarnOrange; else -> BadRed })
            StatusRow("质检提示", "${vm.qualityIssues.size} 项",
                if (vm.qualityIssues.isEmpty()) OkGreen else WarnOrange)
            StatusRow("未核实引用", "${vm.unverifiedCitations.size} 项",
                if (vm.unverifiedCitations.isEmpty()) OkGreen else BadRed)
            if (vm.generatedAt.isNotBlank()) StatusRow("生成时间", vm.generatedAt, TextSecondary)
            vm.qualityIssues.take(3).forEach {
                Text("· $it", fontSize = 11.sp, color = TextSecondary,
                    maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            vm.unverifiedCitations.take(3).forEach {
                Text("⚠️ 缺少事实依据：$it", fontSize = 11.sp, color = BadRed,
                    maxLines = 2, overflow = TextOverflow.Ellipsis)
            }

            Divider()
            Text("AI 助手", fontWeight = FontWeight.Bold, fontSize = 14.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                AssistButton("智能修改", vm) { vm.aiAssist("对当前草稿进行智能修改，提升公文规范性") }
                AssistButton("扩写润色", vm) { vm.aiAssist("在不改变事实的前提下扩写润色") }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                AssistButton("补充政策依据", vm) { vm.aiAssist("补充可引用的政策依据") }
                AssistButton("精简篇幅", vm) { vm.aiAssist("精简篇幅，保留要点") }
            }

            Divider()
            Text("写作依据（${vm.references.size}）", fontWeight = FontWeight.Bold, fontSize = 14.sp)
            if (vm.references.isEmpty()) {
                Text("起草后自动列出检索到的内部资料", fontSize = 11.sp, color = TextSecondary)
            }
            vm.references.take(8).forEach { ref ->
                Text("📄 $ref", fontSize = 11.sp, maxLines = 2,
                    overflow = TextOverflow.Ellipsis)
            }

            Divider()
            Text("操作", fontWeight = FontWeight.Bold, fontSize = 14.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedButton(onClick = {
                    pickSaveFile("${vm.title.ifBlank { "公文" }}.docx")?.let { vm.export(false, it) }
                }, enabled = !vm.busy, modifier = Modifier.weight(1f)) { Text("下载 Word", fontSize = 12.sp) }
                OutlinedButton(onClick = {
                    pickSaveFile("${vm.title.ifBlank { "公文" }}-红头.docx")?.let { vm.export(true, it) }
                }, enabled = !vm.busy, modifier = Modifier.weight(1f)) { Text("生成红头版", fontSize = 12.sp) }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Button(onClick = { vm.saveVersion() }, enabled = !vm.busy,
                    modifier = Modifier.weight(1f)) { Text("保存版本", fontSize = 12.sp) }
                OutlinedButton(onClick = { vm.addToTraining() }, enabled = !vm.busy,
                    modifier = Modifier.weight(1f)) { Text("加入训练数据", fontSize = 12.sp) }
            }
        }
    }
}

// ---------------- 小部件 ----------------

@Composable
private fun DropdownField(label: String, value: String, options: List<String>, onPick: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Column {
        Text(label, fontSize = 11.sp, color = TextSecondary)
        Box {
            Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(4.dp))
                    .background(Color(0xFFF3F4F6)).clickable { open = true }
                    .padding(horizontal = 10.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(value, fontSize = 13.sp, modifier = Modifier.weight(1f))
                Icon(Icons.Default.KeyboardArrowDown, contentDescription = null,
                    modifier = Modifier.size(16.dp), tint = TextSecondary)
            }
            DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                options.forEach { opt ->
                    DropdownMenuItem(onClick = { onPick(opt); open = false }) {
                        Text(opt, fontSize = 13.sp)
                    }
                }
            }
        }
    }
}

@Composable
private fun CheckRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Checkbox(checked = checked, onCheckedChange = onChange)
        Text(label, fontSize = 12.sp)
    }
}

@Composable
private fun StatusRow(label: String, value: String, color: Color) {
    Row {
        Text(label, fontSize = 12.sp, color = TextSecondary, modifier = Modifier.width(72.dp))
        Text(value, fontSize = 12.sp, color = color, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun QualityBadge(level: String) {
    val color = when (level) { "A" -> OkGreen; "B" -> WarnOrange; else -> BadRed }
    Text("质检 $level", fontSize = 11.sp, color = Color.White,
        modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(color)
            .padding(horizontal = 6.dp, vertical = 2.dp))
}

@Composable
private fun AssistButton(label: String, vm: WritingViewModel, onClick: () -> Unit) {
    OutlinedButton(onClick = onClick, enabled = !vm.busy) { Text(label, fontSize = 12.sp) }
}
