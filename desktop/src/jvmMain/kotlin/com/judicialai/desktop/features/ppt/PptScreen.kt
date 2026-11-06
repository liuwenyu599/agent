package com.judicialai.desktop.features.ppt

import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
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
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.PrimaryDeep
import com.judicialai.desktop.design.theme.SecondaryText
import com.judicialai.desktop.design.theme.Surface
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

    LaunchedEffect(Unit) {
        vm.loadTemplates(); vm.loadDocuments(); vm.loadKbs(); vm.loadLibraryMaterials()
    }
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

// ================= 极简入口页（按 ppt-assistant-redesign v3 设计稿重构） =================

/** 未提供配色的用户模板才使用预览占位渐变。 */
private val StyleGradients = listOf(
    listOf(Color(0xFFB01E23), Color(0xFF741217)),
    listOf(Color(0xFF234F91), Color(0xFF142F5A)),
    listOf(Color(0xFF14738D), Color(0xFF0B4D60)),
    listOf(Color(0xFF2B5AA0), Color(0xFF1B365D)),
)
/** 内容依据绿（材料芯片"已分析"文案） */
private val ChipGreen = Color(0xFF2E7D4F)

@Composable
private fun PptEntryPane(
    vm: PptViewModel,
    onOpenDocuments: () -> Unit,
    onOpenTemplates: () -> Unit,
) {
    /** 展开的工具面板：kb / image / page / meta（同一时间最多展开一个） */
    var openPanel by remember { mutableStateOf<String?>(null) }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState())
            .padding(horizontal = 32.dp, vertical = 20.dp),
    ) {
        // 顶部右侧入口（设计稿放在顶栏，桌面端无独立顶栏，收到 Hero 上方）
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Spacer(Modifier.weight(1f))
            TextButton(onClick = onOpenDocuments) { Text("我的作品", fontSize = 12.5.sp) }
            TextButton(onClick = onOpenTemplates) { Text("模板管理", fontSize = 12.5.sp) }
        }

        // Hero：居中标题
        Column(
            Modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("今天想做一份什么 PPT？",
                fontSize = 24.sp, fontWeight = FontWeight.SemiBold, color = Ink)
            Spacer(Modifier.height(6.dp))
            Text("描述任务或上传现有材料，先确认内容结构，再由 AI 完成整套视觉设计。",
                fontSize = 12.5.sp, color = SecondaryText)
        }
        Spacer(Modifier.height(20.dp))

        // Composer 输入卡
        Column(
            Modifier.fillMaxWidth()
                .clip(RoundedCornerShape(16.dp))
                .background(Surface)
                .border(1.dp, Line, RoundedCornerShape(16.dp)),
        ) {
            Column(Modifier.fillMaxWidth().padding(start = 24.dp, end = 24.dp, top = 20.dp)) {
                BasicTextField(
                    value = vm.topic,
                    onValueChange = { vm.topic = it },
                    textStyle = TextStyle(
                        fontSize = 14.5.sp, lineHeight = 25.sp, color = Ink),
                    modifier = Modifier.fillMaxWidth().heightIn(min = 96.dp),
                    decorationBox = { inner ->
                        Box {
                            if (vm.topic.isEmpty()) Text(
                                "例如：根据社区矫正年度工作总结，生成一份面向局领导的 12 页工作汇报，" +
                                    "重点体现工作成效、问题分析和下一步计划。",
                                fontSize = 14.sp, lineHeight = 24.sp, color = Muted)
                            inner()
                        }
                    },
                )
                Spacer(Modifier.height(12.dp))
                vm.materials.forEachIndexed { i, m -> MaterialChip(m) { vm.removeMaterial(i) } }
                if (vm.materials.isNotEmpty()) Spacer(Modifier.height(10.dp))
            }

            // 工具面板（点工具栏按钮展开/收起）
            when (openPanel) {
                "kb" -> KbPanel(vm)
                "image" -> MaterialLibraryPanel(vm)
                "page" -> PagePanel(vm)
                "meta" -> MetaPanel(vm)
            }

            // Composer 工具栏
            Row(
                Modifier.fillMaxWidth()
                    .background(if (openPanel != null) Line.copy(alpha = 0.35f) else Color.Transparent)
                    .padding(horizontal = 14.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                ComposerTool("＋ 添加材料", active = false, enabled = !vm.analyzing) {
                    val files = pickFiles("选择材料（doc/docx/pdf/txt/md/xlsx/csv/pptx，可多选）")
                    if (files.isNotEmpty()) vm.analyzeMaterials(files)
                }
                ComposerTool(
                    if (vm.selectedKbIds.isEmpty()) "▣ 知识库" else "▣ 知识库 · ${vm.selectedKbIds.size}",
                    active = openPanel == "kb",
                ) { openPanel = if (openPanel == "kb") null else "kb" }
                ComposerTool(
                    if (vm.selectedMaterialIds.isEmpty()) "▧ 图片素材"
                    else "▧ 图片 · ${vm.selectedMaterialIds.size}",
                    active = openPanel == "image",
                ) { openPanel = if (openPanel == "image") null else "image" }
                ComposerTool(
                    if (vm.slideCount.isNotBlank()) "▤ ${vm.slideCount} 页" else "▤ 页数",
                    active = openPanel == "page",
                ) { openPanel = if (openPanel == "page") null else "page" }
                ComposerTool("◇ 汇报信息", active = openPanel == "meta") {
                    openPanel = if (openPanel == "meta") null else "meta"
                }
                Spacer(Modifier.weight(1f))
                val canGenerate = !vm.busy && !vm.materialLibraryBusy &&
                    (vm.topic.isNotBlank() || vm.materials.isNotEmpty() ||
                        vm.selectedKbIds.isNotEmpty())
                TextButton(enabled = canGenerate, onClick = { vm.startOutline() }) {
                    Text("先看页面方案", fontSize = 12.sp, color = Primary)
                }
                GenerateButton(
                    enabled = canGenerate && !vm.busy,
                    label = if (vm.busy) vm.outlineStage.ifBlank { "正在生成…" } else "直接生成 PPT →",
                    onClick = { vm.startAiDesign() },
                )
            }
        }

        // Composer 下的辅助行
        Row(Modifier.fillMaxWidth().padding(top = 10.dp)) {
            Text("主题、材料、知识库有其一即可开始",
                fontSize = 11.sp, color = Muted)
            Spacer(Modifier.weight(1f))
            Text("35B 自动组织内容与页面，生成后可逐页修改",
                fontSize = 11.sp, color = Primary, fontWeight = FontWeight.SemiBold)
        }

        if (vm.busy && vm.step == PptStep.ENTRY) OutlineGeneratingPanel(vm)
        PptStatus(vm)

        Row(verticalAlignment = Alignment.CenterVertically) {
            var themeMenu by remember { mutableStateOf(false) }
            val themeName = vm.themes.firstOrNull { it["id"].str() == vm.themeId }
                ?.get("name").str().ifBlank { "按内容自动选择" }
            Box {
                TextButton(enabled = vm.templateId == null, onClick = { themeMenu = true }) {
                    Text("主题色 · $themeName")
                }
                DropdownMenu(themeMenu, onDismissRequest = { themeMenu = false }) {
                    DropdownMenuItem(onClick = { vm.themeId = null; themeMenu = false }) {
                        Text("按内容自动选择")
                    }
                    vm.themes.forEach { theme ->
                        DropdownMenuItem(onClick = {
                            vm.themeId = theme["id"].str()
                            themeMenu = false
                        }) { Text(theme["name"].str()) }
                    }
                }
            }
            TextButton(enabled = !vm.materialLibraryBusy && !vm.busy, onClick = {
                pickFiles("上传到 PPT 图库", multi = false).firstOrNull()
                    ?.let { vm.uploadLibraryMaterial(it) }
            }) { Text(if (vm.materialLibraryBusy) "正在处理图片…" else "上传图库图片") }
        }
        // 视觉风格
        Spacer(Modifier.height(24.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            Text("视觉风格", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Ink)
            Spacer(Modifier.width(8.dp))
            Text("不选模板时使用自适应排版", fontSize = 11.sp, color = Muted)
            Spacer(Modifier.weight(1f))
            TextButton(onClick = onOpenTemplates) { Text("更多模板 →", fontSize = 12.sp) }
        }
        Spacer(Modifier.height(10.dp))
        Row(Modifier.fillMaxWidth().height(140.dp)
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            StyleCardAuto(Modifier.width(190.dp), selected = vm.templateId == null) {
                vm.templateId = null
            }
            vm.templates.forEachIndexed { i, t ->
                StyleCard(t, i, Modifier.width(190.dp),
                    selected = t["id"].str() == vm.templateId) {
                    vm.templateId = t["id"].str()
                }
            }
        }
        val selectedTemplateName = vm.templates.firstOrNull { it["id"].str() == vm.templateId }
            ?.get("name").str()
        Text(if (vm.templateId == null) "本次未套用模板，将使用自适应排版。"
             else "本次将套用「${selectedTemplateName.ifBlank { "所选模板" }}」的版式与配色。",
            fontSize = 11.sp, color = Muted, modifier = Modifier.padding(top = 8.dp))

        // 最近创建
        if (vm.documents.isNotEmpty()) {
            Spacer(Modifier.height(26.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("最近创建", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                Spacer(Modifier.weight(1f))
                TextButton(onClick = onOpenDocuments) { Text("查看全部 →", fontSize = 12.sp) }
            }
            vm.documents.take(3).forEach { d ->
                Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
                Row(
                    Modifier.fillMaxWidth().heightIn(min = 64.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        Modifier.size(36.dp)
                            .clip(RoundedCornerShape(8.dp))
                            .background(Surface)
                            .border(1.dp, Line, RoundedCornerShape(8.dp)),
                        contentAlignment = Alignment.Center,
                    ) { Text("PPT", fontSize = 9.5.sp, fontWeight = FontWeight.Bold, color = Primary) }
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(d["title"].str().ifBlank { "未命名 PPT" },
                            fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Ink,
                            maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(
                            listOf(
                                d["slide_count"].str().let { if (it.isNotBlank()) "$it 页" else "" },
                                d["template_name"].str(),
                                d["updated_at"].str().ifBlank { d["created_at"].str() },
                            ).filter { it.isNotBlank() }.joinToString(" · "),
                            fontSize = 11.sp, color = Muted, maxLines = 1)
                    }
                    TextButton(onClick = { vm.openDocument(d["id"].str()) }) {
                        Text("继续编辑 →", fontSize = 12.sp, color = Primary)
                    }
                }
            }
        }

        // 流程提示
        Spacer(Modifier.height(20.dp))
        Box(
            Modifier.fillMaxWidth()
                .clip(RoundedCornerShape(9.dp))
                .background(Primary.copy(alpha = 0.045f))
                .padding(horizontal = 15.dp, vertical = 12.dp),
        ) {
            Text(
                buildAnnotatedString {
                    withStyle(SpanStyle(color = Primary, fontWeight = FontWeight.SemiBold)) {
                        append("生成流程：")
                    }
                    append("AI 先根据你的需求、材料和知识库生成可编辑大纲；确认大纲后，再进入视觉设计与出片。")
                },
                fontSize = 11.5.sp, color = Ink2, lineHeight = 19.sp,
            )
        }
        Spacer(Modifier.height(12.dp))
    }
}

@Composable
private fun MaterialLibraryPanel(vm: PptViewModel) {
    var filter by remember { mutableStateOf("全部") }
    var search by remember { mutableStateOf("") }
    var publicFile by remember { mutableStateOf<java.io.File?>(null) }
    var publicCategory by remember { mutableStateOf("法治宣传") }
    var publicCaption by remember { mutableStateOf("") }
    var publicSource by remember { mutableStateOf("") }
    var publicLicense by remember { mutableStateOf("") }
      var editingImage by remember { mutableStateOf<PptLibraryMaterial?>(null) }
      var editingCaption by remember { mutableStateOf("") }
    val visible = vm.libraryMaterials.filter {
        (filter == "全部" || (filter == "我的" && it.source == "personal") ||
            (filter == "公共" && it.source == "library") || filter == it.category) &&
            (search.isBlank() || listOf(it.name, it.caption, it.category).any { field ->
                field.contains(search.trim(), ignoreCase = true) })
    }
    Column(
        Modifier.fillMaxWidth().background(Color(0xFFF7F9FC))
            .padding(horizontal = 20.dp, vertical = 12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("图片素材库", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                  Text(if (vm.autoImagesEnabled) "自动从我的图片和已上架公共图库配图"
                       else "仅使用本次勾选的图片；不勾选则不配图",
                       fontSize = 11.sp, color = SecondaryText)
            }
            TextButton(enabled = !vm.materialLibraryBusy, onClick = {
                pickFiles("选择图片素材", multi = false).firstOrNull()
                    ?.let { vm.uploadLibraryMaterial(it) }
            }) { Text(if (vm.materialLibraryBusy) "处理中…" else "＋ 上传图片", fontSize = 12.sp) }
        }
          TextButton(onClick = { vm.toggleAutoImages() }) {
              Text(if (vm.autoImagesEnabled) "✓ 自动配图（点击改为手选）"
                   else "手选图片（点击开启自动配图）", fontSize = 11.sp)
          }
        Row(Modifier.horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            (listOf("全部", "我的", "公共") + vm.libraryMaterials.map { it.category }
                .filter { it != "我的图片" }.distinct()).forEach { choice ->
                TextButton(onClick = { filter = choice }) {
                    Text(choice, color = if (filter == choice) Primary else SecondaryText,
                        fontSize = 11.sp)
                }
            }
            if (AppState.isAdmin) TextButton(onClick = {
                publicFile = pickFiles("选择已获授权的公共图片", multi = false).firstOrNull()
            }) { Text("＋ 上架公共图片", fontSize = 11.sp) }
        }
        OutlinedTextField(search, { search = it }, label = { Text("搜索图片名称或场景") },
            modifier = Modifier.fillMaxWidth(), singleLine = true)
        publicFile?.let { file ->
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("上架：${file.name}", fontSize = 11.sp, color = Ink)
                OutlinedTextField(publicCategory, { publicCategory = it },
                    label = { Text("分类") }, singleLine = true)
                OutlinedTextField(publicCaption, { publicCaption = it },
                    label = { Text("图片说明") }, singleLine = true)
                OutlinedTextField(publicSource, { publicSource = it },
                    label = { Text("来源") }, singleLine = true)
                OutlinedTextField(publicLicense, { publicLicense = it },
                    label = { Text("授权范围（须允许系统内重复使用）") }, singleLine = true)
                Row {
                    TextButton(onClick = { publicFile = null }) { Text("取消") }
                    Button(enabled = !vm.materialLibraryBusy && publicSource.isNotBlank() &&
                        publicLicense.isNotBlank(), onClick = {
                        vm.uploadPublicImage(file, publicCategory, publicCaption,
                            publicSource, publicLicense)
                        publicFile = null
                    }) { Text("确认上架") }
                }
            }
        }
          editingImage?.let { material ->
              Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                  Text("修正「${material.name}」的画面说明", fontSize = 11.sp, color = Ink)
                  OutlinedTextField(editingCaption, { editingCaption = it.take(500) },
                      label = { Text("描述图片中实际可见的内容") },
                      modifier = Modifier.fillMaxWidth(), maxLines = 3)
                  Row {
                      TextButton(onClick = { editingImage = null }) { Text("取消") }
                      TextButton(enabled = !vm.materialLibraryBusy, onClick = {
                          vm.updateImageCaption(material, editingCaption)
                          editingImage = null
                      }) { Text("保存说明") }
                  }
              }
          }
        if (visible.isEmpty()) {
            Text("暂无图片素材。上传后可在不同 PPT 中重复使用。",
                fontSize = 11.5.sp, color = Muted, modifier = Modifier.padding(vertical = 12.dp))
        } else {
            LazyColumn(Modifier.fillMaxWidth().heightIn(max = 220.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)) {
                items(visible, key = { it.id }) { material ->
                    val selected = material.id in vm.selectedMaterialIds
                    Row(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
                            .background(if (selected) Primary.copy(alpha = 0.10f) else Color.White)
                            .border(1.dp, if (selected) Primary else Line, RoundedCornerShape(8.dp))
                            .clickable { vm.toggleLibraryMaterial(material.id) }
                            .padding(8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        val image = rememberServerImage(AppState.api, material.url)
                        Box(Modifier.width(72.dp).height(42.dp).clip(RoundedCornerShape(5.dp))
                            .background(Line.copy(alpha = 0.5f))) {
                            if (image != null) Image(image, material.name,
                                Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
                        }
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(material.name, fontSize = 12.sp, color = Ink, maxLines = 1,
                                overflow = TextOverflow.Ellipsis)
                            Text(if (material.source == "library") "公共 · ${material.category}"
                                 else "我的图片", fontSize = 10.sp, color = Muted)
                            if (material.caption.isNotBlank()) Text(material.caption,
                                fontSize = 10.5.sp, color = SecondaryText, maxLines = 1,
                                overflow = TextOverflow.Ellipsis)
                              else Text("暂无画面说明，自动配图不会使用此图",
                                  fontSize = 10.sp, color = Muted, maxLines = 1)
                            if (material.credit.isNotBlank()) Text("来源：${material.credit}",
                                fontSize = 10.sp, color = Muted, maxLines = 1,
                                overflow = TextOverflow.Ellipsis)
                        }
                          Column(horizontalAlignment = Alignment.End) {
                              Text(if (selected) "✓ 已选" else "选择", fontSize = 11.sp,
                                  color = if (selected) Primary else SecondaryText)
                              if (material.source == "personal" || AppState.isAdmin) {
                                  TextButton(onClick = {
                                      editingImage = material
                                      editingCaption = material.caption
                                  }) { Text("改说明", fontSize = 10.sp) }
                              }
                          }
                    }
                }
            }
        }
    }
}

/** Composer 工具按钮（添加材料 / 知识库 / 页数 / 汇报信息） */
@Composable
private fun ComposerTool(
    label: String,
    active: Boolean,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    Text(
        label,
        fontSize = 12.sp,
        color = when {
            active -> Primary
            enabled -> Ink2
            else -> Muted
        },
        fontWeight = if (active) FontWeight.SemiBold else FontWeight.Normal,
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(if (active) Primary.copy(alpha = 0.07f) else Color.Transparent)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 8.dp),
    )
}

/** PPT 生成主按钮 */
@Composable
private fun GenerateButton(enabled: Boolean, label: String, onClick: () -> Unit) {
    Box(
        Modifier
            .alpha(if (enabled) 1f else 0.45f)
            .clip(RoundedCornerShape(10.dp))
            .background(Brush.horizontalGradient(listOf(PrimaryDeep, Primary)))
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 22.dp, vertical = 11.dp),
    ) {
        Text(label, color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
    }
}

/** 已分析材料芯片（图标块 + 文件名 + 状态 + 移除） */
@Composable
private fun MaterialChip(m: MaterialAnalysis, onRemove: () -> Unit) {
    Row(
        Modifier.fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(Color(0xFFF8F9FB))
            .border(1.dp, Line, RoundedCornerShape(8.dp))
            .padding(start = 9.dp, end = 4.dp, top = 7.dp, bottom = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(28.dp).clip(RoundedCornerShape(6.dp))
                .background(Primary.copy(alpha = 0.08f)),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                m.filename.substringAfterLast('.', "").uppercase().take(3).ifBlank { "文档" },
                fontSize = 8.5.sp, fontWeight = FontWeight.Bold, color = Primary)
        }
        Spacer(Modifier.width(9.dp))
        Column(Modifier.weight(1f)) {
            Text(m.filename, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Ink,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                if (m.summary.isNotBlank()) "✓ 已分析 · 可作为内容依据"
                else "✓ 已分析 · ${m.chars} 字",
                fontSize = 10.sp, color = ChipGreen, maxLines = 1)
        }
        Text(
            "×", fontSize = 15.sp, color = Muted,
            modifier = Modifier.clip(RoundedCornerShape(6.dp))
                .clickable(onClick = onRemove).padding(horizontal = 8.dp, vertical = 4.dp))
    }
}

/** 知识库面板（Composer 内展开） */
@Composable
private fun KbPanel(vm: PptViewModel) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 10.dp)) {
        when {
            vm.kbs.isNotEmpty() -> {
                vm.kbs.chunked(4).forEach { rowKbs ->
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        rowKbs.forEach { kb ->
                            val kbId = kb["id"].str()
                            val picked = kbId in vm.selectedKbIds
                            OutlinedButton(
                                onClick = { vm.toggleKb(kbId) },
                                colors = sel(picked),
                                modifier = Modifier.weight(1f).height(34.dp),
                            ) {
                                Text((if (picked) "✓ " else "") +
                                    kb["name"].str().ifBlank { "未命名知识库" },
                                    fontSize = 11.5.sp, maxLines = 1)
                            }
                        }
                        repeat(4 - rowKbs.size) { Spacer(Modifier.weight(1f)) }
                    }
                }
                Text("仅按当前主题语义检索相关片段，不会把整库内容直接灌入。",
                    fontSize = 10.5.sp, color = Muted, modifier = Modifier.padding(top = 6.dp))
            }
            vm.kbsError != null -> {
                Text(vm.kbsError ?: "知识库暂时加载失败",
                    fontSize = 11.5.sp, color = SecondaryText)
                TextButton(enabled = !vm.kbsLoading, onClick = { vm.loadKbs() }) {
                    Text(if (vm.kbsLoading) "重试中…" else "重新加载", fontSize = 12.sp)
                }
            }
            else -> Text(
                if (vm.kbsLoading) "知识库加载中…" else "暂无可用知识库",
                fontSize = 11.5.sp, color = Muted)
        }
    }
}

/** 页数面板（Composer 内展开） */
@Composable
private fun PagePanel(vm: PptViewModel) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 10.dp)) {
        OutlinedTextField(
            vm.slideCount,
            { vm.slideCount = it.filter(Char::isDigit).take(2) },
            label = { Text("期望页数（2–18，留空由 AI 安排）", fontSize = 11.5.sp) },
            isError = vm.slideCount.isNotBlank() &&
                (vm.slideCount.toIntOrNull()?.let { it !in 2..18 } != false),
            singleLine = true,
            modifier = Modifier.width(280.dp),
        )
    }
}

/** 汇报信息面板（年度 / 单位 / 汇报人 / 落款日期，Composer 内展开） */
@Composable
private fun MetaPanel(vm: PptViewModel) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(vm.generationYear,
                { vm.updateGenerationYear(it.filter(Char::isDigit).take(4)) },
                label = { Text("年度", fontSize = 11.5.sp) },
                singleLine = true, modifier = Modifier.weight(1f))
            OutlinedTextField(vm.location, { vm.updateLocation(it) },
                label = { Text("单位/地点", fontSize = 11.5.sp) },
                singleLine = true, modifier = Modifier.weight(1f))
            OutlinedTextField(vm.presenter, { vm.updatePresenter(it) },
                label = { Text("汇报人（可选）", fontSize = 11.5.sp) },
                singleLine = true, modifier = Modifier.weight(1f))
            OutlinedTextField(vm.reportDate, { vm.updateReportDate(it) },
                label = { Text("落款日期", fontSize = 11.5.sp) },
                singleLine = true, modifier = Modifier.weight(1f))
        }
        Text("这些信息会作为关键事实带入大纲，AI 不会替你编造。",
            fontSize = 10.5.sp, color = Muted)
    }
}

/** 风格卡：智能选择（templateId = null） */
@Composable
private fun StyleCardAuto(modifier: Modifier, selected: Boolean, onClick: () -> Unit) {
    Column(
        modifier
            .height(140.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(Surface)
            .border(
                if (selected) 1.5.dp else 1.dp,
                if (selected) Primary else Line,
                RoundedCornerShape(12.dp),
            )
            .clickable(onClick = onClick),
    ) {
        Box(
            Modifier.fillMaxWidth().height(97.dp)
                .background(Brush.linearGradient(
                    listOf(Color(0xFFF0F2F5), Color(0xFFE7EBF0)))),
            contentAlignment = Alignment.Center,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier.size(34.dp).clip(RoundedCornerShape(10.dp))
                        .background(Surface),
                    contentAlignment = Alignment.Center,
                ) { Text("AI", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = Primary) }
                Spacer(Modifier.width(9.dp))
                Text("根据内容智能匹配", fontSize = 12.sp, color = Ink2)
            }
        }
        StyleCardMeta("智能选择", recommend = true, selected = selected)
    }
}

/** 风格卡：真实模板（预览图优先，无图用渐变底 + 名称） */
@Composable
private fun StyleCard(
    t: JsonObject,
    index: Int,
    modifier: Modifier,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val colors = t["colors"].obj()
    fun color(key: String): Color? = colors?.get(key)?.str()
        ?.removePrefix("#")?.takeIf { it.matches(Regex("[0-9a-fA-F]{6}")) }
        ?.toLongOrNull(16)?.let { Color((0xFF000000L or it).toInt()) }
    val grad = if (color("primary") != null && color("dark") != null)
        listOf(color("primary")!!, color("dark")!!)
    else StyleGradients[index % StyleGradients.size]
    Column(
        modifier
            .height(140.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(Surface)
            .border(
                if (selected) 1.5.dp else 1.dp,
                if (selected) Primary else Line,
                RoundedCornerShape(12.dp),
            )
            .clickable(onClick = onClick),
    ) {
        Box(Modifier.fillMaxWidth().height(97.dp).background(Brush.linearGradient(grad))) {
            val img = rememberServerImage(AppState.api, t["preview_url"].str().ifBlank { null })
            if (img != null) {
                Image(img, contentDescription = t["name"].str(),
                    modifier = Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
            }
            Column(Modifier.align(Alignment.BottomStart).padding(12.dp)) {
                Text(t["name"].str(), fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                    color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text("AI DESIGN", fontSize = 8.sp, color = Color.White.copy(alpha = 0.72f))
            }
        }
        StyleCardMeta(t["name"].str(), recommend = false, selected = selected)
    }
}

@Composable
private fun StyleCardMeta(name: String, recommend: Boolean, selected: Boolean) {
    Row(
        Modifier.fillMaxWidth().height(43.dp).padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(name, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Ink,
            maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
        if (recommend) {
            Spacer(Modifier.width(6.dp))
            Text("推荐",
                fontSize = 9.sp, color = Primary,
                modifier = Modifier.clip(RoundedCornerShape(99.dp))
                    .background(Primary.copy(alpha = 0.07f))
                    .padding(horizontal = 6.dp, vertical = 2.dp))
        }
        if (selected) {
            Spacer(Modifier.weight(1f))
            Text("✓", fontSize = 14.sp, color = Primary, fontWeight = FontWeight.Bold)
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
                Text(if (vm.autoDesignAfterOutline) "正在生成 PPT" else "正在规划页面",
                    style = MaterialTheme.typography.subtitle2,
                    color = MaterialTheme.colors.primary)
                Spacer(Modifier.width(8.dp))
                Text(
                    vm.outlineStage.ifBlank { "正在整理内容与页面结构" },
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
                vm.confirmOutlineAndGenerate()
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
                        if (d["has_drawio"].str() == "true") {
                            OutlinedButton(enabled = vm.downloadingId != id, onClick = {
                                val target = pickSaveFile(
                                    d["title"].str().ifBlank { "演示文稿" } + "-图示.drawio")
                                    ?: return@OutlinedButton
                                vm.downloadDrawio(id, target)
                            }) { Text("图示源文件") }
                            Spacer(Modifier.width(4.dp))
                        }
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
    var sharedFile by remember { mutableStateOf<java.io.File?>(null) }
    var sharedLicense by remember { mutableStateOf("") }
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
            if (AppState.isAdmin) TextButton(enabled = !vm.busy, onClick = {
                pickFiles("选择已获授权的共享 PPTX 母版").firstOrNull()
                    ?.let { sharedFile = it }
            }) { Text("上传共享母版") }
        }
        Text("模板文字框可写 {{title}}、{{point1}}、{{card1_title}}、{{card1_body}}、{{time1}}、{{event1}} 等占位符；生成时按位置替换。",
            fontSize = 11.sp, color = Muted)
        sharedFile?.let { file ->
            OutlinedTextField(sharedLicense, { sharedLicense = it },
                label = { Text("${file.name} 的授权说明：须允许内网系统反复生成和改编") },
                modifier = Modifier.fillMaxWidth())
            Row {
                TextButton(onClick = { sharedFile = null }) { Text("取消") }
                Button(enabled = sharedLicense.isNotBlank() && !vm.busy, onClick = {
                    vm.uploadTemplate(file, shared = true, licenseNote = sharedLicense)
                    sharedFile = null
                    sharedLicense = ""
                }) { Text("确认发布给全员") }
            }
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
                                Text(if (t["is_learned"].bool()) "可编辑母版"
                                     else "配色主题", style = MaterialTheme.typography.caption,
                                     color = if (t["is_learned"].bool()) Primary else SecondaryText)
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
    val originalLayouts = t["layouts"].obj() ?: JsonObject(emptyMap())
    val library = t["layout_library"].arr().mapNotNull { it.obj() }

    var name by remember(id) { mutableStateOf(t["name"].str()) }
    var category by remember(id) { mutableStateOf(t["category"].str()) }
    var description by remember(id) { mutableStateOf(t["description"].str()) }
    // 与后端 app/core/fonts.py 的 DEFAULT_CJK_FONT 保持一致。
    // 原为「微软雅黑」，后端容器（只装了 fonts-noto-cjk）与麒麟 OS 均无此字体。
    var font by remember(id) { mutableStateOf(t["font"].str().ifBlank { "Noto Sans CJK SC" }) }

    var cover by remember(id) { mutableStateOf(originalLayouts["cover"].str()) }
    var toc by remember(id) { mutableStateOf(originalLayouts["toc"].str()) }
    var section by remember(id) { mutableStateOf(originalLayouts["section"].str()) }
    var content by remember(id) { mutableStateOf(originalLayouts["content"].str()) }
    var data by remember(id) { mutableStateOf(originalLayouts["data"].str()) }
    var chart by remember(id) { mutableStateOf(originalLayouts["chart"].str()) }
    var caseLayout by remember(id) { mutableStateOf(originalLayouts["case"].str()) }
    var timeline by remember(id) { mutableStateOf(originalLayouts["timeline"].str()) }
    var process by remember(id) { mutableStateOf(originalLayouts["process"].str()) }
    var summary by remember(id) { mutableStateOf(originalLayouts["summary"].str()) }
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
                    val mappings = mapOf(
                        "cover" to cover,
                        "toc" to toc,
                        "section" to section,
                        "content" to content,
                        "data" to data,
                        "chart" to chart,
                        "case" to caseLayout,
                        "timeline" to timeline,
                        "process" to process,
                        "summary" to summary,
                        "closing" to closing,
                    )
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
            Text("各页型版式骨架", style = MaterialTheme.typography.subtitle2)
            Text(
                if (library.isEmpty()) "该模板尚未识别到可编辑版式；可重新上传结构更完整的 PPTX。"
                else "系统已识别 ${library.size} 种实际页面版式。为核心页型指定来源页后，生成时会优先克隆对应骨架。",
                style = MaterialTheme.typography.caption, color = SecondaryText,
            )
            if (library.isNotEmpty()) {
                TemplateLayoutSelector("封面", cover, library) { cover = it }
                TemplateLayoutSelector("目录", toc, library) { toc = it }
                TemplateLayoutSelector("章节页", section, library) { section = it }
                TemplateLayoutSelector("正文", content, library) { content = it }
                TemplateLayoutSelector("数据页", data, library) { data = it }
                TemplateLayoutSelector("图表页", chart, library) { chart = it }
                TemplateLayoutSelector("案例页", caseLayout, library) { caseLayout = it }
                TemplateLayoutSelector("时间线", timeline, library) { timeline = it }
                TemplateLayoutSelector("流程页", process, library) { process = it }
                TemplateLayoutSelector("总结页", summary, library) { summary = it }
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
