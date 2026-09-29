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
import androidx.compose.material.DropdownMenu
import androidx.compose.material.DropdownMenuItem
import androidx.compose.material.Icon
import androidx.compose.material.IconButton
import androidx.compose.material.LinearProgressIndicator
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedButton
import androidx.compose.material.OutlinedTextField
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
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.bool
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.components.AppButton
import com.judicialai.desktop.design.components.AppButtonKind
import com.judicialai.desktop.design.components.AppButtonSize
import com.judicialai.desktop.design.components.AppDialog
import com.judicialai.desktop.design.theme.SecondaryText
import kotlinx.serialization.json.JsonObject

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
    var libraryView by remember { mutableStateOf<String?>(null) }
    var returnToWorksAfterClose by remember { mutableStateOf(false) }
    val pendingDocId = AppState.pendingPptDocId
    val generating = AppState.pptOutlineGenerating
    val pendingJobId = AppState.pendingPptJobId

    LaunchedEffect(Unit) { vm.loadTemplates(); vm.loadDocuments(); vm.loadKbs() }
    LaunchedEffect(pendingDocId) {
        if (pendingDocId != null && vm.docId == null) vm.openDocument(pendingDocId)
    }
    LaunchedEffect(pendingJobId) { if (pendingJobId != null) vm.resumeJob() }
    DisposableEffect(Unit) { onDispose { vm.stopJobPolling() } }

    vm.pendingConfirm?.let { if (it.isNotEmpty()) PptPrecheckDialog(vm, it) }
    vm.job?.let { if (it.status == PptJobStatus.CLARIFYING) PptJobClarifyDialog(vm, it) }

    Column(Modifier.fillMaxSize()) {
        val lastError = AppState.pptLastError
        when {
            generating && vm.docId == null -> PptGeneratingBanner(vm)
            lastError != null && vm.docId == null ->
                PptFailedBanner(lastError) { AppState.pptLastError = null }
        }
        when {
            vm.jobVisible -> PptAsyncWorkbench(vm)
            vm.step == PptStep.WORKBENCH -> PptWorkbench(vm) {
                vm.closeDocument()
                if (returnToWorksAfterClose) {
                    returnToWorksAfterClose = false
                    libraryView = "docs"
                    vm.loadDocuments()
                }
            }
            vm.step == PptStep.OUTLINE -> OutlineConfirmPane(vm)
            libraryView == "docs" -> Column(Modifier.fillMaxSize().padding(24.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = { libraryView = null }) { Text("← 返回创建") }
                    Spacer(Modifier.width(8.dp))
                    Text("我的作品", style = MaterialTheme.typography.h6)
                }
                Spacer(Modifier.height(12.dp))
                PptDocsPane(vm, onOpen = {
                    returnToWorksAfterClose = true
                    libraryView = null
                })
            }
            libraryView == "templates" -> Column(Modifier.fillMaxSize().padding(24.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = { libraryView = null }) { Text("← 返回创建") }
                    Spacer(Modifier.width(8.dp))
                    Text("模板管理", style = MaterialTheme.typography.h6)
                }
                Spacer(Modifier.height(12.dp))
                PptTemplatesPane(vm)
            }
            else -> PptEntryPane(vm,
                onOpenDocuments = {
                    returnToWorksAfterClose = false
                    libraryView = "docs"
                    vm.loadDocuments()
                },
                onOpenTemplates = { libraryView = "templates"; vm.loadTemplates() })
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
    AppDialog(
        onDismissRequest = { vm.cancelConfirm() },
        title = "生成前请确认关键信息",
        subtitle = "为避免凭空编造，请确认以下信息；也可以明确选择按默认方案继续。",
        width = 560.dp,
        actions = {
            AppButton("取消", onClick = { vm.cancelConfirm() }, kind = AppButtonKind.SECONDARY)
            Spacer(Modifier.width(8.dp))
            AppButton("按默认方案继续", onClick = { vm.confirmAndGenerate(false) },
                kind = AppButtonKind.SECONDARY)
            Spacer(Modifier.width(8.dp))
            AppButton("确认并生成大纲", onClick = { vm.confirmAndGenerate(true) })
        },
    ) {
        questions.forEach { q ->
            OutlinedTextField(q.answer, { q.answer = it }, label = { Text(q.question) },
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
            if (clarifying) "AI 需要你回答一个问题才能继续，请返回 PPT 创建页处理"
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
private fun PptEntryPane(
    vm: PptViewModel,
    onOpenDocuments: () -> Unit,
    onOpenTemplates: () -> Unit,
) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState())
            .padding(horizontal = 32.dp, vertical = 28.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("今天想做一份什么 PPT？", style = MaterialTheme.typography.h5)
                Spacer(Modifier.height(4.dp))
                Text("描述任务或上传现有材料，先确认内容结构，再由 AI 完成整套视觉设计。",
                    style = MaterialTheme.typography.body2, color = SecondaryText)
            }
            TextButton(onClick = onOpenDocuments) { Text("我的作品") }
            TextButton(onClick = onOpenTemplates) { Text("模板管理") }
        }

        Card(Modifier.fillMaxWidth(), elevation = 2.dp) {
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(
                    vm.topic, { vm.topic = it },
                    placeholder = { Text("例如：根据社区矫正年度工作总结，生成一份面向局领导的工作汇报，重点体现工作成效、问题分析和下一步计划。") },
                    modifier = Modifier.fillMaxWidth().heightIn(min = 112.dp),
                )
                vm.materials.forEachIndexed { i, m ->
                    Card(Modifier.fillMaxWidth(), elevation = 0.dp,
                        backgroundColor = MaterialTheme.colors.primary.copy(alpha = 0.04f)) {
                        Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(m.filename, style = MaterialTheme.typography.subtitle2, maxLines = 1)
                                Text(if (m.summary.isNotBlank()) "已分析 · " + m.summary
                                    else "已分析 · ${m.chars} 字",
                                    style = MaterialTheme.typography.caption,
                                    color = SecondaryText, maxLines = 2)
                            }
                            IconButton(onClick = { vm.removeMaterial(i) }) {
                                Icon(Icons.Default.Close, "移除", tint = SecondaryText)
                            }
                        }
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedButton(enabled = !vm.analyzing, onClick = {
                        val files = pickFiles("选择材料（doc/docx/pdf/txt/md/xlsx/csv/pptx，可多选）")
                        if (files.isNotEmpty()) vm.analyzeMaterials(files)
                    }) { Text(if (vm.analyzing) "分析材料中…" else "＋ 添加材料") }
                    Spacer(Modifier.width(10.dp))
                    Text(if (vm.selectedKbIds.isEmpty()) "可结合知识库生成"
                        else "知识库 · 已选 ${vm.selectedKbIds.size} 个",
                        style = MaterialTheme.typography.caption,
                        color = if (vm.selectedKbIds.isEmpty()) SecondaryText else MaterialTheme.colors.primary)
                    Spacer(Modifier.weight(1f))
                    Text("主题、材料、知识库有其一即可开始",
                        style = MaterialTheme.typography.caption, color = SecondaryText)
                }
            }
        }

        if (vm.kbs.isNotEmpty()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("内容依据", style = MaterialTheme.typography.subtitle2,
                    modifier = Modifier.weight(1f))
                Text("共 " + vm.kbs.size + " 个可用知识库",
                    style = MaterialTheme.typography.caption, color = SecondaryText)
            }
            vm.kbs.chunked(4).forEach { rowKbs ->
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    rowKbs.forEach { kb ->
                        val kbId = kb["id"].str()
                        val picked = kbId in vm.selectedKbIds
                        OutlinedButton(
                            onClick = { vm.toggleKb(kbId) },
                            colors = sel(picked),
                            modifier = Modifier.weight(1f),
                        ) {
                            Text((if (picked) "✓ " else "") +
                                kb["name"].str().ifBlank { "未命名知识库" }, maxLines = 1)
                        }
                    }
                    repeat(4 - rowKbs.size) { Spacer(Modifier.weight(1f)) }
                }
            }
            Text("仅按当前主题语义检索相关片段，不会把整库内容直接灌入。",
                style = MaterialTheme.typography.caption, color = SecondaryText)
        } else if (vm.kbsError != null) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(vm.kbsError ?: "知识库暂时加载失败",
                    style = MaterialTheme.typography.caption, color = SecondaryText,
                    modifier = Modifier.weight(1f))
                TextButton(enabled = !vm.kbsLoading, onClick = { vm.loadKbs() }) {
                    Text(if (vm.kbsLoading) "重试中…" else "重新加载")
                }
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                vm.slideCount,
                { vm.slideCount = it.filter(Char::isDigit).take(2) },
                label = { Text("页数（可选，2–18）") },
                isError = vm.slideCount.isNotBlank() &&
                    (vm.slideCount.toIntOrNull()?.let { it !in 2..18 } != false),
                modifier = Modifier.weight(1f),
            )
            OutlinedTextField(vm.generationYear, { vm.updateGenerationYear(it.filter(Char::isDigit).take(4)) },
                label = { Text("年度") }, modifier = Modifier.weight(1f))
            OutlinedTextField(vm.location, { vm.updateLocation(it) },
                label = { Text("单位/地点") }, modifier = Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(vm.presenter, { vm.updatePresenter(it) },
                label = { Text("汇报人（可选）") }, modifier = Modifier.weight(1f))
            OutlinedTextField(vm.reportDate, { vm.updateReportDate(it) },
                label = { Text("落款日期") }, modifier = Modifier.weight(1f))
        }

        Text("视觉风格", style = MaterialTheme.typography.subtitle2)
        Text("不选择时由 AI 根据内容自动匹配；模板只控制视觉与版式，不改变已确认内容。",
            style = MaterialTheme.typography.caption, color = SecondaryText)
        TemplatePicker(vm)

        val canGenerate = !vm.busy &&
            (vm.topic.isNotBlank() || vm.materials.isNotEmpty() || vm.selectedKbIds.isNotEmpty())
        AppButton(
            text = if (vm.busy) vm.outlineStage.ifBlank { "正在生成大纲…" } else "生成大纲",
            onClick = { vm.startOutline() }, enabled = canGenerate,
            size = AppButtonSize.LG, fill = true,
        )
        Text("先确认页数、标题和逐页内容，再交给 AI 视觉设计，避免直接出片后反复返工。",
            style = MaterialTheme.typography.caption, color = SecondaryText)
        if (vm.busy && vm.step == PptStep.ENTRY) OutlineGeneratingPanel(vm)
        PptStatus(vm)

        if (vm.documents.isNotEmpty()) {
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("最近创建", style = MaterialTheme.typography.subtitle2,
                    modifier = Modifier.weight(1f))
                TextButton(onClick = onOpenDocuments) { Text("查看全部") }
            }
            vm.documents.take(3).forEach { d ->
                Card(Modifier.fillMaxWidth(), elevation = 1.dp) {
                    Row(Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(d["title"].str().ifBlank { "未命名 PPT" },
                                style = MaterialTheme.typography.subtitle2)
                            Text(d["updated_at"].str().ifBlank { d["created_at"].str() },
                                style = MaterialTheme.typography.caption, color = SecondaryText)
                        }
                        TextButton(onClick = { vm.openDocument(d["id"].str()) }) {
                            Text("继续编辑 →")
                        }
                    }
                }
            }
        }
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
                    vm.outlineStage.ifBlank { "正在整理内容，完成后自动进入大纲确认" },
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
            Text("模板加载中或为空，可进入右上角“模板管理”上传。", style = MaterialTheme.typography.caption,
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
            Button(onClick = {
                val target = pickSaveFile(
                    (vm.outlineTitle.ifBlank { vm.topic.ifBlank { "演示文稿" } }) + ".pptx"
                ) ?: return@Button
                vm.confirmOutlineAndGenerate(target)
            }) { Text("确认大纲并生成 PPT") }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(vm.outlineTitle, { vm.outlineTitle = it },
                label = { Text("PPT 标题") }, modifier = Modifier.weight(2f))
            OutlinedTextField(vm.outlineSubtitle, { vm.outlineSubtitle = it },
                label = { Text("副标题（可选）") }, modifier = Modifier.weight(1f))
        }

        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                vm.outlineAdjustInstruction,
                { vm.outlineAdjustInstruction = it },
                label = { Text("AI 调整大纲") },
                placeholder = { Text("例如：把目录页改成正文页；合并第 3、4 页") },
                modifier = Modifier.weight(1f),
                singleLine = true,
            )
            Button(
                onClick = { vm.aiAdjustOutline() },
                enabled = !vm.aiBusy && vm.outlineAdjustInstruction.isNotBlank(),
            ) {
                Text(if (vm.aiBusy) "调整中…" else "AI 调整")
            }
        }
        vm.aiNote?.let {
            Text(it, style = MaterialTheme.typography.caption, color = SecondaryText)
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
    var pendingDelete by remember { mutableStateOf<JsonObject?>(null) }
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
                        IconButton(onClick = { pendingDelete = d }) {
                            Icon(Icons.Default.Delete, "删除", tint = MaterialTheme.colors.error)
                        }
                    }
                }
            }
            if (vm.documents.isEmpty()) item {
                Text("暂无 PPT，可返回创建页生成，或点击上方“导入 PPT 续改”。",
                    style = MaterialTheme.typography.caption, color = SecondaryText)
            }
        }
    }

    pendingDelete?.let { d ->
        AppDialog(
            onDismissRequest = { pendingDelete = null },
            title = "删除 PPT",
            subtitle = "删除后该 PPT 的大纲与编辑记录将无法继续使用。",
            width = 460.dp,
            actions = {
                AppButton("取消", onClick = { pendingDelete = null }, kind = AppButtonKind.SECONDARY)
                Spacer(Modifier.width(8.dp))
                AppButton("确认删除", onClick = {
                    vm.deleteDocument(d["id"].str())
                    pendingDelete = null
                }, kind = AppButtonKind.DANGER)
            },
        ) {
            Text(d["title"].str().ifBlank { "未命名 PPT" })
        }
    }
}

// ================= 模板库 =================

@Composable
private fun PptTemplatesPane(vm: PptViewModel) {
    var pendingDelete by remember { mutableStateOf<JsonObject?>(null) }
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
                            if (t["is_mine"].bool()) {
                                TextButton(
                                    enabled = !vm.templateEditorBusy,
                                    onClick = { vm.openTemplateEditor(t["id"].str()) },
                                ) { Text("编辑骨架") }
                                IconButton(onClick = { pendingDelete = t }) {
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

    pendingDelete?.let { t ->
        AppDialog(
            onDismissRequest = { pendingDelete = null },
            title = "删除 PPT 模板",
            subtitle = "删除后新建 PPT 将无法继续选择该模板；已有 PPT 不受影响。",
            width = 460.dp,
            actions = {
                AppButton("取消", onClick = { pendingDelete = null }, kind = AppButtonKind.SECONDARY)
                Spacer(Modifier.width(8.dp))
                AppButton("确认删除", onClick = {
                    vm.deleteTemplate(t["id"].str())
                    pendingDelete = null
                }, kind = AppButtonKind.DANGER)
            },
        ) {
            Text(t["name"].str().ifBlank { "未命名模板" })
        }
    }

    vm.templateEditor?.let { TemplateSkeletonEditor(vm, it) }
}

@Composable
private fun TemplateSkeletonEditor(vm: PptViewModel, t: JsonObject) {
    val id = t["id"].str()
    val originalLayouts = t["layouts"].obj()
    val library = t["layout_library"].arr().mapNotNull { it.obj() }

    var name by remember(id) { mutableStateOf(t["name"].str()) }
    var category by remember(id) { mutableStateOf(t["category"].str()) }
    var description by remember(id) { mutableStateOf(t["description"].str()) }
    var font by remember(id) { mutableStateOf(t["font"].str().ifBlank { "微软雅黑" }) }

    var cover by remember(id) { mutableStateOf(originalLayouts["cover"].str()) }
    var toc by remember(id) { mutableStateOf(originalLayouts["toc"].str()) }
    var content by remember(id) { mutableStateOf(originalLayouts["content"].str()) }
    var data by remember(id) { mutableStateOf(originalLayouts["data"].str()) }
    var closing by remember(id) { mutableStateOf(originalLayouts["closing"].str()) }

    AppDialog(
        onDismissRequest = { vm.closeTemplateEditor() },
        title = "编辑模板骨架",
        subtitle = "给核心页型指定实际学习到的模板页。保存后“严格套模板”会优先使用这些版式。",
        width = 720.dp,
        actions = {
            AppButton("取消", onClick = { vm.closeTemplateEditor() },
                kind = AppButtonKind.SECONDARY)
            Spacer(Modifier.width(8.dp))
            AppButton(
                "保存骨架",
                enabled = !vm.templateEditorBusy && name.isNotBlank(),
                loading = vm.templateEditorBusy,
                onClick = {
                    val mappings = buildMap {
                        if (cover.isNotBlank()) put("cover", cover)
                        if (toc.isNotBlank()) put("toc", toc)
                        if (content.isNotBlank()) put("content", content)
                        if (data.isNotBlank()) put("data", data)
                        if (closing.isNotBlank()) put("closing", closing)
                    }
                    vm.saveTemplateEditor(id, name, category, description, font, mappings)
                },
            )
        },
    ) {
        Column(
            Modifier.fillMaxWidth().heightIn(max = 560.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(name, { name = it }, label = { Text("模板名称") },
                    modifier = Modifier.weight(1f), singleLine = true)
                OutlinedTextField(category, { category = it }, label = { Text("类别") },
                    modifier = Modifier.weight(1f), singleLine = true)
                OutlinedTextField(font, { font = it }, label = { Text("默认字体") },
                    modifier = Modifier.weight(1f), singleLine = true)
            }
            OutlinedTextField(
                description, { description = it }, label = { Text("模板说明") },
                modifier = Modifier.fillMaxWidth(),
            )
            Text("核心版式骨架", style = MaterialTheme.typography.subtitle2)
            Text(
                if (library.isEmpty()) "该模板尚未识别到可编辑版式；可重新上传结构更完整的 PPTX。"
                else "系统已识别 ${library.size} 种实际页面版式。为核心页型指定来源页后，生成时会优先克隆对应骨架。",
                style = MaterialTheme.typography.caption, color = SecondaryText,
            )
            if (library.isNotEmpty()) {
                TemplateLayoutSelector("封面", cover, library) { cover = it }
                TemplateLayoutSelector("目录", toc, library) { toc = it }
                TemplateLayoutSelector("正文", content, library) { content = it }
                TemplateLayoutSelector("数据页", data, library) { data = it }
                TemplateLayoutSelector("结束页", closing, library) { closing = it }
            }
        }
    }
}

@Composable
private fun TemplateLayoutSelector(
    label: String,
    selectedId: String,
    layouts: List<JsonObject>,
    onSelected: (String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    val selected = layouts.firstOrNull { it["id"].str() == selectedId }
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(label, modifier = Modifier.width(72.dp), style = MaterialTheme.typography.body2)
        Box(Modifier.weight(1f)) {
            OutlinedButton(onClick = { expanded = true }, modifier = Modifier.fillMaxWidth()) {
                Text(
                    selected?.get("name")?.str()
                        ?.let { "$it（${selected["id"].str()}）" }
                        ?: "自动匹配",
                    maxLines = 1,
                )
            }
            DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                DropdownMenuItem(onClick = {
                    onSelected("")
                    expanded = false
                }) { Text("自动匹配") }
                layouts.forEach { lay ->
                    DropdownMenuItem(onClick = {
                        onSelected(lay["id"].str())
                        expanded = false
                    }) {
                        Text(
                            lay["name"].str().ifBlank { lay["id"].str() } +
                                " · " + slideTypeLabel(lay["detected_type"].str())
                        )
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
