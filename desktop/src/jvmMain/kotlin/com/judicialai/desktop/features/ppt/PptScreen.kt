package com.judicialai.desktop.features.ppt

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Card
import androidx.compose.material.Icon
import androidx.compose.material.IconButton
import androidx.compose.material.LinearProgressIndicator
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedButton
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Tab
import androidx.compose.material.TabRow
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.platform.pickFiles
import com.judicialai.desktop.core.platform.pickSaveFile
import com.judicialai.desktop.core.platform.rememberServerImage
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.components.AppButton
import com.judicialai.desktop.design.components.AppButtonKind
import com.judicialai.desktop.design.components.AppButtonSize
import com.judicialai.desktop.design.components.AppDialog
import com.judicialai.desktop.design.theme.SecondaryText
import kotlinx.coroutines.delay

/** 页型中文标签（与服务端 10 种页型一致） */
val SLIDE_TYPE_LABELS = linkedMapOf(
    "cover" to "封面", "toc" to "目录", "section" to "章节页",
    "content" to "内容页", "data" to "数据页", "chart" to "图表页",
    "case" to "案例页", "timeline" to "时间线", "process" to "流程页",
    "summary" to "总结页", "closing" to "结尾页",
)

fun slideTypeLabel(type: String) = SLIDE_TYPE_LABELS[type] ?: type

/**
 * PPT 助手工作台（重设计）：
 * 新建 = 极简入口（材料 + 一句话意图 + 可选项，无技术参数）
 * → 生成前预检（信息不足先确认） → 流式大纲（阶段可见、可取消） → 可编辑大纲确认 → 三栏工作台；
 * 我的 PPT = 打开续改 / 导入已有 PPT / 下载 / 删除；模板库保持不变。
 */
@Composable
fun PptScreen() {
    val vm = remember { PptViewModel(Repositories.ppt) }
    var tab by remember { mutableStateOf(0) }

    // 跨页面恢复：切走再切回时 remember 会重建 ViewModel（状态清零），
    // 但生成协程不会被取消，服务端文档早已落库。这里读取全局状态：
    // 本地还没有文档而全局有 id → 按 id 从服务端取回大纲，直接回到工作台。
    // 读取发生在组合内，生成完成后（可能是离开页面之后才跑完）id 一写入就会触发重组并自动恢复。
    val pendingDocId = AppState.pendingPptDocId
    val generating = AppState.pptOutlineGenerating
    // 异步生成任务号：切走再切回时据此重新挂上轮询（进度在服务端，不会丢）
    val pendingJobId = AppState.pendingPptJobId

    LaunchedEffect(Unit) { vm.loadTemplates(); vm.loadDocuments() }

    // 以 id 为 key：id 从 null 变为具体值时（生成完成）自动执行一次恢复
    LaunchedEffect(pendingDocId) {
        if (pendingDocId != null && vm.docId == null) vm.openDocument(pendingDocId)
    }

    // 异步生成任务：回到页面时重新挂上（续接轮询 / 补一次落盘）
    LaunchedEffect(pendingJobId) {
        if (pendingJobId != null) vm.resumeJob()
    }

    // 离开页面必须停掉轮询协程，否则每个页面都会留下一条永远跑着的轮询。
    // 任务状态与目标文件都在服务端与全局 PptJobEngine 里，回来时 resumeJob 会续上。
    DisposableEffect(Unit) {
        onDispose { vm.stopJobPolling() }
    }

    // 生成前预检：信息不足时弹出关键信息确认框（90 秒未操作自动按默认方案生成）
    vm.pendingConfirm?.let { qs ->
        if (qs.isNotEmpty()) PptPrecheckDialog(vm, qs)
    }

    // PPTAgent 追问：信息不足时它会先反问而不是直接生成。
    // 后端刻意不自动代答（自动代答等于替用户编需求），所以必须把问题抛给用户：
    // 回答后 POST /clarify 带着上下文续跑同一个任务。任务状态是全局的，
    // 所以即便用户当时在别的页面、切回来也还能看到这个追问框。
    val pendingQuestion = vm.job
    // 只认状态、不认 question 是否为空：万一后端给了状态却没给问题文本，
    // 也必须让用户能作答，否则任务会永远卡在「等待补充信息」没人能推动
    if (pendingQuestion != null && pendingQuestion.status == PptJobStatus.CLARIFYING) {
        PptJobClarifyDialog(vm, pendingQuestion)
    }

    Column(Modifier.fillMaxSize()) {
        TabRow(selectedTabIndex = tab) {
            Tab(tab == 0, { tab = 0 }) { Text("新建 PPT", Modifier.padding(12.dp)) }
            Tab(tab == 1, { tab = 1 }) { Text("我的 PPT", Modifier.padding(12.dp)) }
            Tab(tab == 2, { tab = 2 }) { Text("模板库", Modifier.padding(12.dp)) }
        }
        // 还没拿到 doc_id 就切回来了：明确告诉用户生成仍在进行（协程并未被取消），
        // 不要呈现一片空白让人以为生成丢了
        val lastError = AppState.pptLastError
        // 异步生成任务进度（全局 PptJobEngine，不随页面销毁）
        val job = vm.job
        when {
            generating && vm.docId == null -> PptGeneratingBanner(vm)
            lastError != null && vm.docId == null ->
                // 上次生成（可能发生在切走期间）失败了：本地 status 已随 ViewModel 丢失，
                // 只有全局记录还在，必须让用户知道失败原因
                PptFailedBanner(lastError) { AppState.pptLastError = null }
            // 生成中 / 等待补充信息，但用户在别的 Tab：给一条提示，避免以为任务没了
            job != null && (job.isActive || job.status == PptJobStatus.CLARIFYING) &&
                tab != 0 -> PptJobRunningBanner(job)
        }
        when {
            // 异步生成任务存在（生成中 / 完成 / 失败 / 已取消）→ 展示生成工作台
            tab == 0 && vm.jobVisible -> PptAsyncWorkbench(vm)
            tab == 0 && vm.step == PptStep.WORKBENCH -> PptWorkbench(vm)
            tab == 0 && vm.step == PptStep.OUTLINE -> OutlineConfirmPane(vm)
            else -> Column(Modifier.padding(12.dp)) {
                when (tab) {
                    0 -> PptEntryPane(vm)
                    1 -> PptDocsPane(vm, onOpen = { tab = 0 })
                    else -> PptTemplatesPane(vm)
                }
            }
        }
    }
}

/**
 * 生成前确认框：预检发现关键信息不足时列出待确认问题（预填默认方案）。
 * 90 秒倒计时结束或点击「按默认方案生成」→ 用默认方案直接开跑；点「取消」放弃本次生成。
 * 使用统一 AppDialog：内容区可滚动、限高，避免问题较多时溢出。
 */
@Composable
private fun PptPrecheckDialog(vm: PptViewModel, questions: List<ConfirmQuestion>) {
    var remaining by remember { mutableStateOf(90) }
    LaunchedEffect(questions) {
        while (remaining > 0 && vm.pendingConfirm != null) {
            delay(1000)
            remaining--
        }
        // 倒计时结束仍未操作：按最合理的默认方案先跑
        if (vm.pendingConfirm != null) vm.confirmAndGenerate(useAnswers = false)
    }
    AppDialog(
        onDismissRequest = { vm.cancelConfirm() },
        title = "生成前请确认关键信息",
        subtitle = "为避免凭空编造，请确认以下信息；留空则按默认方案生成。",
        width = 560.dp,
        actions = {
            AppButton("取消", onClick = { vm.cancelConfirm() }, kind = AppButtonKind.SECONDARY)
            Spacer(Modifier.width(8.dp))
            AppButton("按默认方案生成（${remaining}s）",
                onClick = { vm.confirmAndGenerate(useAnswers = false) },
                kind = AppButtonKind.SECONDARY)
            Spacer(Modifier.width(8.dp))
            AppButton("确认并生成", onClick = { vm.confirmAndGenerate(useAnswers = true) })
        },
    ) {
        questions.forEach { q ->
            OutlinedTextField(
                value = q.answer, onValueChange = { q.answer = it },
                label = { Text(q.question) },
                modifier = Modifier.fillMaxWidth())
        }
    }
}

/**
 * 跨页面生成提示条：大纲还在生成（协程不随页面切换取消）但本地还没拿到文档时显示。
 * 有实时阶段就展示阶段文案，否则说明「完成后会自动回到工作台」。
 */
@Composable
private fun PptGeneratingBanner(vm: PptViewModel) {
    Row(
        Modifier.fillMaxWidth()
            .background(MaterialTheme.colors.primary.copy(alpha = 0.08f))
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("正在生成 PPT", style = MaterialTheme.typography.subtitle2,
            color = MaterialTheme.colors.primary)
        Spacer(Modifier.width(8.dp))
        Text(vm.outlineStage.ifBlank { "生成完成后会自动回到工作台，可先去其他页面" },
            style = MaterialTheme.typography.caption, color = SecondaryText)
    }
}

/**
 * 异步生成进行中提示条：用户在别的 Tab（如「我的 PPT」）时也要能看到任务还在跑，
 * 否则会以为提交完就没下文了。等待补充信息时给出更明确的引导。
 */
@Composable
private fun PptJobRunningBanner(job: PptJobProgress) {
    val clarifying = job.status == PptJobStatus.CLARIFYING
    Row(
        Modifier.fillMaxWidth()
            .background(MaterialTheme.colors.primary.copy(alpha = 0.08f))
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(if (clarifying) "PPT 生成等你补充信息" else "PPT 正在生成",
            style = MaterialTheme.typography.subtitle2,
            color = MaterialTheme.colors.primary)
        Spacer(Modifier.width(8.dp))
        Text(
            if (clarifying) "AI 需要你回答一个问题才能继续，请切到「新建 PPT」查看"
            else job.stageText.ifBlank { "生成完成后会自动保存，可先去其他页面" },
            style = MaterialTheme.typography.caption, color = SecondaryText,
            modifier = Modifier.weight(1f))
    }
}

/**
 * 上次生成失败提示条：失败发生在切到别的页面期间时，本地 ViewModel 已被重建、
 * status 丢失，只有全局记录还在。
 * 停在入口页时没有「返回修改」这类可清除入口，所以给一个关闭按钮，否则提示永远清不掉。
 */
@Composable
private fun PptFailedBanner(message: String, onDismiss: () -> Unit) {
    Row(
        Modifier.fillMaxWidth()
            .background(MaterialTheme.colors.error.copy(alpha = 0.08f))
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("上次生成未完成：$message", style = MaterialTheme.typography.caption,
            color = MaterialTheme.colors.error, modifier = Modifier.weight(1f))
        Spacer(Modifier.width(8.dp))
        TextButton(onClick = onDismiss) { Text("知道了") }
    }
}

@Composable
internal fun sel(selected: Boolean) = ButtonDefaults.outlinedButtonColors(
    backgroundColor = if (selected) MaterialTheme.colors.primary.copy(alpha = 0.12f)
    else Color.Transparent)

// ================= 极简入口页 =================

@Composable
private fun PptEntryPane(vm: PptViewModel) {
    Column(Modifier.verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {

        Text("想做一份什么 PPT？", style = MaterialTheme.typography.subtitle1)
        OutlinedTextField(vm.topic, { vm.topic = it },
            label = { Text("一句话说明，如：社区矫正工作年度汇报") },
            modifier = Modifier.fillMaxWidth())

        // 材料区：上传后逐份显示 AI 分析结果，不再是黑盒
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("参考材料", style = MaterialTheme.typography.subtitle2,
                modifier = Modifier.weight(1f))
            OutlinedButton(enabled = !vm.analyzing, onClick = {
                val files = pickFiles("选择材料（doc/docx/pdf/txt/md/xlsx/csv/pptx，可多选）")
                if (files.isNotEmpty()) vm.analyzeMaterials(files)
            }) { Text(if (vm.analyzing) "分析中…" else "添加材料") }
        }
        if (vm.materials.isEmpty()) {
            Text("可上传工作总结、数据表、既有 PPT 等，AI 会逐份分析并作为内容依据。",
                style = MaterialTheme.typography.caption, color = SecondaryText)
        }
        vm.materials.forEachIndexed { i, m ->
            Card(Modifier.fillMaxWidth(), elevation = 1.dp) {
                Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("${m.filename}（${m.chars} 字）",
                            style = MaterialTheme.typography.subtitle2, maxLines = 1)
                        if (m.summary.isNotBlank()) {
                            Text(m.summary, style = MaterialTheme.typography.caption,
                                color = SecondaryText, maxLines = 3)
                        }
                    }
                    IconButton(onClick = { vm.removeMaterial(i) }) {
                        Icon(Icons.Default.Close, "移除", tint = MaterialTheme.colors.error)
                    }
                }
            }
        }

        // 可选项：页数 / 汇报人 / 时间
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(vm.slideCount, { vm.slideCount = it.filter(Char::isDigit) },
                label = { Text("页数（可选）") }, modifier = Modifier.weight(1f))
            OutlinedTextField(vm.presenter, { vm.presenter = it },
                label = { Text("汇报人（可选）") }, modifier = Modifier.weight(1f))
            OutlinedTextField(vm.reportDate, { vm.reportDate = it },
                label = { Text("汇报时间（可选）") }, modifier = Modifier.weight(1f))
        }

        TemplatePicker(vm)

        // 「AI 智能设计」是主路径：用户不用手动挑模板、也不用在大纲确认页多停一步，
        // 直接让 AI 逐页设计排版，所以给它最高的视觉权重（AI 渐变实心主按钮）。
        val canGenerate = !vm.busy && (vm.topic.isNotBlank() || vm.materials.isNotEmpty())
        AppButton(
            text = if (vm.autoDesignAfterOutline) "AI 智能设计中…" else "AI 智能设计",
            onClick = {
                // 先定保存位置：任务跑完会自动落盘到这里。
                // 用户在这里取消 = 什么都不发起（不生成大纲、不提交任务）
                val target = pickSaveFile(
                    (vm.topic.ifBlank { "演示文稿" }) + ".pptx") ?: return@AppButton
                vm.startAiDesign(target)
            },
            enabled = canGenerate,
            kind = AppButtonKind.AI,
            size = AppButtonSize.LG,
            loading = vm.autoDesignAfterOutline,
            fill = true,
        )
        Text(
            "AI 逐页设计排版，约 5–15 分钟；比“生成大纲”少一步确认，直接出片。" +
                "模板只作内容结构参考，不必手动挑。",
            style = MaterialTheme.typography.caption, color = SecondaryText)

        // 次要路径：只出大纲，停在确认页自己逐页改
        OutlinedButton(
            enabled = canGenerate,
            onClick = { vm.startOutline() },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(
                if (vm.busy && !vm.autoDesignAfterOutline)
                    vm.outlineStage.ifBlank { "生成中…" } else "生成大纲")
        }

        // 生成过程可见：实时阶段 + 浅蓝进度 + 骨架屏 + 可取消
        // （不再是没有进度、不能取消、看不到过程的空白等待）
        if (vm.busy && vm.step == PptStep.ENTRY) {
            OutlineGeneratingPanel(vm)
        }

        PptStatus(vm)
    }
}

/** 大纲生成中面板：阶段文案 + 进度条 + 浅蓝骨架屏 + 取消按钮 */
@Composable
private fun OutlineGeneratingPanel(vm: PptViewModel) {
    Card(Modifier.fillMaxWidth(), elevation = 1.dp) {
        Column(Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("正在生成大纲", style = MaterialTheme.typography.subtitle2,
                    color = MaterialTheme.colors.primary)
                Spacer(Modifier.width(8.dp))
                Text(
                    vm.outlineStage.ifBlank { "后端处理中，完成后自动进入大纲确认" },
                    style = MaterialTheme.typography.caption, color = SecondaryText,
                    modifier = Modifier.weight(1f))
                TextButton(onClick = { vm.cancelOutline() }) {
                    Text("取消生成", color = MaterialTheme.colors.error,
                        style = MaterialTheme.typography.caption)
                }
            }
            LinearProgressIndicator(
                modifier = Modifier.fillMaxWidth().height(4.dp),
                color = Color(0xFF64A8F0),
                backgroundColor = Color(0xFFE3EBF5),
            )
            // 骨架屏：示意即将产出的大纲结构，而不是空白
            SkeletonBar(Modifier.fillMaxWidth(0.55f).height(14.dp))
            SkeletonBar(Modifier.fillMaxWidth(0.9f).height(10.dp))
            SkeletonBar(Modifier.fillMaxWidth(0.8f).height(10.dp))
            SkeletonBar(Modifier.fillMaxWidth(0.85f).height(10.dp))
        }
    }
}

@Composable
internal fun TemplatePicker(vm: PptViewModel) {
    Text("选择模板", style = MaterialTheme.typography.subtitle2)
    Row(Modifier.fillMaxWidth().height(130.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        vm.templates.take(6).forEach { t ->
            val tid = t["id"].str()
            val selected = tid == vm.templateId
            Card(
                Modifier.width(180.dp).fillMaxHeight(),
                elevation = if (selected) 6.dp else 1.dp,
                backgroundColor = if (selected)
                    MaterialTheme.colors.primary.copy(alpha = 0.10f)
                else MaterialTheme.colors.surface,
            ) {
                TextButton(onClick = { vm.templateId = tid }, modifier = Modifier.fillMaxSize()) {
                    Column(Modifier.fillMaxSize()) {
                        val img = rememberServerImage(AppState.api,
                            t["preview_url"].str().ifBlank { null })
                        if (img != null) {
                            Image(img, contentDescription = t["name"].str(),
                                modifier = Modifier.fillMaxWidth().weight(1f),
                                contentScale = ContentScale.Crop)
                        } else {
                            Box(Modifier.fillMaxWidth().weight(1f),
                                contentAlignment = Alignment.Center) {
                                Text(t["name"].str(), style = MaterialTheme.typography.caption)
                            }
                        }
                        Text(t["name"].str(), style = MaterialTheme.typography.caption,
                            maxLines = 1, modifier = Modifier.padding(4.dp))
                    }
                }
            }
        }
        if (vm.templates.isEmpty()) {
            Text("模板加载中或为空，可到“模板库”上传。", style = MaterialTheme.typography.caption,
                color = SecondaryText, modifier = Modifier.align(Alignment.CenterVertically))
        }
    }
}

// ================= 可编辑大纲确认 =================

@Composable
internal fun OutlineConfirmPane(vm: PptViewModel) {
    Column(Modifier.fillMaxSize().padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("确认大纲（共 ${vm.slides.size} 页，逐页可改）",
                style = MaterialTheme.typography.subtitle1, modifier = Modifier.weight(1f))
            TextButton(onClick = { vm.backToEntry() }) { Text("返回修改") }
            OutlinedButton(onClick = {
                vm.addSlideAfter(vm.slides.size - 1)
            }) { Text("添加页面") }
            Spacer(Modifier.width(8.dp))
            Button(onClick = { vm.toWorkbench() }) { Text("确认，进入编辑") }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(vm.outlineTitle, { vm.outlineTitle = it },
                label = { Text("PPT 标题") }, modifier = Modifier.weight(2f))
            OutlinedTextField(vm.outlineSubtitle, { vm.outlineSubtitle = it },
                label = { Text("副标题（可选）") }, modifier = Modifier.weight(1f))
        }

        LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            itemsIndexed(vm.slides, key = { i, _ -> i }) { i, s ->
                Card(Modifier.fillMaxWidth(), elevation = 1.dp) {
                    Column(Modifier.padding(10.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("${i + 1}", style = MaterialTheme.typography.subtitle1,
                                color = MaterialTheme.colors.primary)
                            Spacer(Modifier.width(8.dp))
                            SlideTypeDropdown(s)
                            Spacer(Modifier.weight(1f))
                            TextButton(onClick = { vm.moveSlide(i, -1) },
                                enabled = i > 0) { Text("上移") }
                            TextButton(onClick = { vm.moveSlide(i, 1) },
                                enabled = i < vm.slides.size - 1) { Text("下移") }
                            TextButton(onClick = { vm.addSlideAfter(i) }) { Text("下插一页") }
                            IconButton(onClick = { vm.removeSlide(i) }) {
                                Icon(Icons.Default.Delete, "删除本页",
                                    tint = MaterialTheme.colors.error)
                            }
                        }
                        OutlinedTextField(s.title, { s.title = it },
                            label = { Text("本页标题") }, modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(s.pointsText, { s.pointsText = it },
                            label = { Text("要点（一行一条）") },
                            modifier = Modifier.fillMaxWidth().heightIn(min = 80.dp, max = 200.dp))
                        if (s.sources.isNotEmpty()) {
                            Text("内容依据：" + s.sources.joinToString("、"),
                                style = MaterialTheme.typography.caption,
                                color = SecondaryText)
                        }
                    }
                }
            }
        }
        PptStatus(vm)
    }
}

@Composable
internal fun SlideTypeDropdown(s: SlideEdit) {
    var open by remember { mutableStateOf(false) }
    Box {
        OutlinedButton(onClick = { open = true }, colors = sel(false)) {
            Text(slideTypeLabel(s.type))
        }
        androidx.compose.material.DropdownMenu(open, { open = false }) {
            SLIDE_TYPE_LABELS.forEach { (key, label) ->
                androidx.compose.material.DropdownMenuItem(onClick = {
                    s.type = key; open = false
                }) { Text(label) }
            }
        }
    }
}

// ================= 我的 PPT =================

@Composable
private fun PptDocsPane(vm: PptViewModel, onOpen: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("我的 PPT", style = MaterialTheme.typography.subtitle1,
                modifier = Modifier.weight(1f))
            OutlinedButton(enabled = !vm.busy, onClick = {
                pickFiles("选择要导入的 .pptx").firstOrNull()?.let { f ->
                    if (f.name.endsWith(".pptx", ignoreCase = true)) {
                        vm.importPptx(f); onOpen()
                    } else vm.status = "仅支持 .pptx 文件"
                }
            }) { Text("导入 PPT 续改") }
            Spacer(Modifier.width(4.dp))
            IconButton(onClick = { vm.loadDocuments() }) {
                Icon(Icons.Default.Refresh, "刷新")
            }
        }
        PptStatus(vm)
        LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(vm.documents) { d ->
                val id = d["id"].str()
                Card(Modifier.fillMaxWidth(), elevation = 1.dp) {
                    Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(d["title"].str().ifBlank { "未命名PPT" },
                                style = MaterialTheme.typography.subtitle2)
                            val meta = listOf(
                                d["slide_count"].str().let { if (it.isNotBlank()) "$it 页" else "" },
                                d["template_name"].str(),
                                d["updated_at"].str().ifBlank { d["created_at"].str() },
                            ).filter { it.isNotBlank() }.joinToString(" · ")
                            Text(meta, style = MaterialTheme.typography.caption,
                                color = SecondaryText)
                        }
                        OutlinedButton(enabled = !vm.busy, onClick = {
                            vm.openDocument(id); onOpen()
                        }) { Text("打开") }
                        Spacer(Modifier.width(4.dp))
                        Button(enabled = vm.downloadingId != id, onClick = {
                            val target = pickSaveFile(
                                d["title"].str().ifBlank { "演示文稿" } + ".pptx") ?: return@Button
                            vm.download(id, target)
                        }) { Text(if (vm.downloadingId == id) "下载中…" else "下载") }
                        Spacer(Modifier.width(4.dp))
                        IconButton(onClick = { vm.deleteDocument(id) }) {
                            Icon(Icons.Default.Delete, "删除", tint = MaterialTheme.colors.error)
                        }
                    }
                }
            }
            if (vm.documents.isEmpty()) item {
                Text("暂无 PPT，可到“新建 PPT”生成，或点击上方“导入 PPT 续改”。",
                    style = MaterialTheme.typography.caption, color = SecondaryText)
            }
        }
    }
}

// ================= 模板库 =================

@Composable
private fun PptTemplatesPane(vm: PptViewModel) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("模板库（上传后自动学习版式与风格）", style = MaterialTheme.typography.subtitle1,
                modifier = Modifier.weight(1f))
            IconButton(onClick = { vm.loadTemplates() }) {
                Icon(Icons.Default.Refresh, "刷新")
            }
            Button(enabled = !vm.busy, onClick = {
                pickFiles("选择 pptx 模板").firstOrNull()?.let { vm.uploadTemplate(it) }
            }) { Text(if (vm.busy) "学习中…" else "上传模板") }
        }
        PptStatus(vm)
        LazyVerticalGrid(columns = GridCells.Adaptive(200.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(vm.templates) { t ->
                Card(elevation = 2.dp) {
                    Column {
                        val img = rememberServerImage(AppState.api,
                            t["preview_url"].str().ifBlank { null })
                        if (img != null) {
                            Image(img, contentDescription = t["name"].str(),
                                modifier = Modifier.fillMaxWidth().height(110.dp),
                                contentScale = ContentScale.Crop)
                        } else {
                            Box(Modifier.fillMaxWidth().height(110.dp),
                                contentAlignment = Alignment.Center) {
                                Text("无预览", style = MaterialTheme.typography.caption,
                                    color = SecondaryText)
                            }
                        }
                        Row(Modifier.padding(8.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(t["name"].str(), style = MaterialTheme.typography.subtitle2,
                                    maxLines = 1)
                                Text(t["layout_count"].str().ifBlank { "?" } + " 种版式",
                                    style = MaterialTheme.typography.caption, color = SecondaryText)
                            }
                            IconButton(onClick = { vm.deleteTemplate(t["id"].str()) }) {
                                Icon(Icons.Default.Delete, "删除",
                                    tint = MaterialTheme.colors.error)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
internal fun PptStatus(vm: PptViewModel) {
    vm.status?.let {
        Text(it, style = MaterialTheme.typography.caption,
            color = if (isFailureStatus(it)) MaterialTheme.colors.error
            else MaterialTheme.colors.primary)
    }
}

/**
 * 判定一条 status 是否为「失败」语义。
 *
 * 之前只认"完成/已保存/已"三个成功词，其余一律判红——于是
 * 「正在打开文档…」「正在解析「xxx」…」这类**过程提示**也被染成红色错误字，
 * 切回 PPT 页面瞬间就是一行红字。这里先排除失败关键词，再判中性/成功。
 */
private fun isFailureStatus(text: String): Boolean {
    val failureHints = listOf(
        "失败", "错误", "中断", "不存在", "已删除", "不可达", "超时",
        "无法", "不能", "缺少", "请先", "仅支持", "已过期", "不合法", "异常",
    )
    if (failureHints.any { text.contains(it) }) return true
    val neutralHints = listOf("完成", "已", "正在", "中…", "处理中")
    return neutralHints.none { text.contains(it) }
}
