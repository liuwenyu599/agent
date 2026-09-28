package com.judicialai.desktop.features.ppt

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.DropdownMenu
import androidx.compose.material.DropdownMenuItem
import androidx.compose.material.LinearProgressIndicator
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedButton
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.material.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.platform.pickSaveFile
import com.judicialai.desktop.core.platform.rememberServerImage
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.design.components.AppButton
import com.judicialai.desktop.design.components.AppButtonKind
import com.judicialai.desktop.design.components.AppDialog
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.SecondaryText
import com.judicialai.desktop.design.theme.Surface

/** 右侧 AI 面板底色（参考规范：浅灰 #F9FAFB） */
private val AiPanelBg = Color(0xFFF9FAFB)
/** 底部状态栏进度条浅蓝填充 */
private val ProgressBlue = Color(0xFF64A8F0)
/** 骨架屏浅蓝 */
private val SkeletonBlue = Color(0xFFDCE9FA)

/** 骨架屏呼吸闪烁（浅蓝），生成中/渲染中替代空白 */
@Composable
private fun skeletonColor(): Color {
    val transition = rememberInfiniteTransition(label = "skeleton")
    val alpha by transition.animateFloat(
        initialValue = 0.45f, targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(900), RepeatMode.Reverse),
        label = "skeletonAlpha",
    )
    return SkeletonBlue.copy(alpha = alpha)
}

@Composable
internal fun SkeletonBar(modifier: Modifier = Modifier) {
    Box(modifier.clip(RoundedCornerShape(4.dp)).background(skeletonColor()))
}

/**
 * PPT 编辑工作台：顶部文档操作栏 + 三栏编辑区 + 底部状态栏。
 * 顶部把关闭文档和 AI 生成设为明确的一级操作，避免用户被困在已打开的文档中。
 */
@Composable
fun PptWorkbench(vm: PptViewModel) {
    var showGenConfirm by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize()) {
        WorkbenchTopBar(
            vm = vm,
            onClose = { vm.closeDocument() },
            onGenerate = { showGenConfirm = true },
        )
        Row(Modifier.weight(1f).fillMaxWidth()) {
            ThumbRail(vm)
            Box(Modifier.width(1.dp).fillMaxHeight().background(Line))
            PreviewPane(vm)
            Box(Modifier.width(1.dp).fillMaxHeight().background(Line))
            AiPanel(vm)
        }
        StatusBar(vm)
    }

    if (showGenConfirm) {
        GenerateConfirmDialog(vm, onDismiss = { showGenConfirm = false })
    }
}

/** 顶部文档标题栏：显示当前文档，并提供显式关闭与 AI 设计入口。 */
@Composable
private fun WorkbenchTopBar(
    vm: PptViewModel,
    onClose: () -> Unit,
    onGenerate: () -> Unit,
) {
    Column(Modifier.fillMaxWidth().background(Surface)) {
        Row(
            Modifier.fillMaxWidth().height(56.dp).padding(horizontal = 16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    text = vm.outlineTitle.ifBlank { "未命名演示文稿" },
                    style = MaterialTheme.typography.subtitle1,
                    color = Ink,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    text = "共 ${vm.slides.size} 页",
                    style = MaterialTheme.typography.caption,
                    color = SecondaryText,
                )
            }
            OutlinedButton(onClick = onClose) {
                Text("关闭", fontSize = 12.5.sp)
            }
            Spacer(Modifier.width(10.dp))
            Button(
                enabled = !vm.busy && vm.docId != null,
                onClick = onGenerate,
                colors = ButtonDefaults.buttonColors(backgroundColor = Primary),
                shape = RoundedCornerShape(8.dp),
            ) {
                Text("AI 生成 PPT", color = Color.White, fontSize = 13.sp)
            }
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
    }
}

// ================= 左栏：页面缩略图 =================

@Composable
private fun ThumbRail(vm: PptViewModel) {
    Column(
        Modifier.width(196.dp).fillMaxHeight().background(Surface).padding(10.dp),
    ) {
        Text("页面（${vm.slides.size}）", fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
            color = Ink)
        Spacer(Modifier.height(8.dp))
        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            itemsIndexed(vm.slides, key = { i, _ -> i }) { i, s ->
                val selected = i == vm.selected
                val img = rememberServerImage(AppState.api,
                    vm.previewPages.getOrNull(i))
                Box(
                    Modifier.fillMaxWidth()
                        .clickable { vm.selected = i },
                ) {
                    // 缩略图本体：16:9、圆角 6dp、选中描边深蓝
                    Box(
                        Modifier.fillMaxWidth()
                            .aspectRatio(16f / 9f)
                            .clip(RoundedCornerShape(6.dp))
                            .background(Color.White)
                            .border(1.dp, if (selected) Primary else Line,
                                RoundedCornerShape(6.dp)),
                    ) {
                        if (img != null) {
                            Image(img, contentDescription = s.title,
                                modifier = Modifier.fillMaxSize(),
                                contentScale = ContentScale.Fit)
                        } else {
                            Column(
                                Modifier.fillMaxSize().padding(8.dp),
                                verticalArrangement = Arrangement.Center,
                            ) {
                                Text("${i + 1}", fontSize = 13.sp,
                                    fontWeight = FontWeight.SemiBold, color = Primary)
                                Text(s.title.ifBlank { slideTypeLabel(s.type) },
                                    fontSize = 10.5.sp, color = Ink2,
                                    maxLines = 2, lineHeight = 14.sp)
                            }
                        }
                    }
                    // 选中态：左侧 3dp 深蓝竖条
                    if (selected) {
                        Box(
                            Modifier.align(Alignment.CenterStart)
                                .width(3.dp).height(56.dp)
                                .clip(RoundedCornerShape(topEnd = 2.dp, bottomEnd = 2.dp))
                                .background(Primary),
                        )
                    }
                }
            }
        }
    }
}

// ================= 中栏：预览 + 直接编辑 =================

@Composable
private fun PreviewPane(vm: PptViewModel) {
    val i = vm.selected.coerceIn(0, (vm.slides.size - 1).coerceAtLeast(0))
    val slide = vm.slides.getOrNull(i)
    // 切换模板 / 手动刷新时递增，避免同一 URL 的预览图被缓存成旧版
    var previewTick by remember { mutableStateOf(0) }

    Column(
        Modifier.fillMaxHeight().verticalScroll(rememberScrollState())
            .background(AppBg).padding(32.dp), // 规范：预览周围留白 32dp
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (slide == null) {
            Text("暂无页面", color = SecondaryText)
            return@Column
        }

        // 顶行：返回大纲 / 模板切换 / 刷新预览 / 撤销
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { vm.backToOutline() }) {
                Text("← 返回大纲", color = Primary, fontSize = 12.5.sp)
            }
            Spacer(Modifier.weight(1f))
            Text("模板", fontSize = 12.sp, color = Muted)
            Spacer(Modifier.width(6.dp))
            var tplOpen by remember { mutableStateOf(false) }
            val curName = vm.templates
                .firstOrNull { it["id"].str() == vm.templateId }
                ?.get("name").str().ifBlank { "默认模板" }
            Box {
                OutlinedButton(onClick = { tplOpen = true }, colors = sel(false)) {
                    Text("$curName ▾", fontSize = 12.sp)
                }
                DropdownMenu(tplOpen, { tplOpen = false }) {
                    vm.templates.forEach { t ->
                        DropdownMenuItem(onClick = {
                            vm.templateId = t["id"].str()
                            tplOpen = false
                            previewTick++
                            vm.refreshPreview()
                        }) { Text(t["name"].str()) }
                    }
                }
            }
            Spacer(Modifier.width(6.dp))
            TextButton(enabled = !vm.previewBusy, onClick = {
                previewTick++
                vm.refreshPreview()
            }) { Text(if (vm.previewBusy) "渲染中…" else "刷新预览", fontSize = 12.sp, color = Primary) }
            if (vm.canUndo) {
                TextButton(onClick = { vm.undo() }) {
                    Text("撤销", fontSize = 12.sp, color = Ink2)
                }
            }
        }

        // 预览：16:9 白色卡片、圆角 8dp、轻投影；渲染中显示浅蓝骨架屏而不是空白
        androidx.compose.material.Card(
            modifier = Modifier.fillMaxWidth().aspectRatio(16f / 9f),
            shape = RoundedCornerShape(8.dp),
            elevation = 4.dp,
            backgroundColor = Color.White,
        ) {
            val rawUrl = vm.previewPages.getOrNull(i)
            val pageUrl = rawUrl?.let {
                it + (if (it.contains("?")) "&" else "?") + "_=" + previewTick
            }
            val img = rememberServerImage(AppState.api, pageUrl)
            when {
                img != null -> Image(img, contentDescription = slide.title,
                    modifier = Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
                vm.previewBusy -> PreviewSkeleton()
                else -> StructuredFallback(slide)
            }
        }
        Text(
            when {
                vm.previewPages.getOrNull(i) != null -> "预览由所选模板真实渲染，与导出效果一致"
                vm.previewBusy -> "正在按模板渲染预览…"
                else -> "模板渲染预览暂不可用，当前为结构示意（不影响导出效果）"
            },
            fontSize = 11.5.sp, color = SecondaryText)
        if (slide.sources.isNotEmpty()) {
            Text("内容依据：" + slide.sources.joinToString("、"),
                fontSize = 11.5.sp, color = SecondaryText)
        }

        // 直接编辑
        OutlinedTextField(slide.title, { slide.title = it },
            label = { Text("本页标题") }, modifier = Modifier.fillMaxWidth(),
            colors = TextFieldDefaults.outlinedTextFieldColors(
                backgroundColor = Color.White,
                focusedBorderColor = Primary, unfocusedBorderColor = Line))
        OutlinedTextField(slide.pointsText, { slide.pointsText = it },
            label = { Text("要点（一行一条）") },
            modifier = Modifier.fillMaxWidth().heightIn(min = 100.dp, max = 220.dp),
            colors = TextFieldDefaults.outlinedTextFieldColors(
                backgroundColor = Color.White,
                focusedBorderColor = Primary, unfocusedBorderColor = Line))
    }
}

/** 预览骨架屏：浅蓝呼吸块，示意标题区 + 要点区（异步生成的中栏也复用） */
@Composable
internal fun PreviewSkeleton() {
    Column(Modifier.fillMaxSize().padding(28.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        SkeletonBar(Modifier.fillMaxWidth(0.45f).height(22.dp))
        SkeletonBar(Modifier.fillMaxWidth(0.9f).height(10.dp))
        SkeletonBar(Modifier.fillMaxWidth(0.8f).height(10.dp))
        SkeletonBar(Modifier.fillMaxWidth(0.85f).height(10.dp))
        SkeletonBar(Modifier.fillMaxWidth(0.6f).height(10.dp))
    }
}

/** 结构化回退预览（服务端未渲染成功时） */
@Composable
private fun StructuredFallback(slide: SlideEdit) {
    Column(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxWidth().height(6.dp).background(Primary))
        Column(Modifier.padding(20.dp)) {
            Text(slide.title.ifBlank { "（无标题）" },
                style = MaterialTheme.typography.h6)
            Spacer(Modifier.height(10.dp))
            slide.points().take(6).forEach { p ->
                Text("• $p", style = MaterialTheme.typography.body2,
                    modifier = Modifier.padding(vertical = 2.dp))
            }
            if (slide.points().size > 6) {
                Text("……共 ${slide.points().size} 条要点",
                    style = MaterialTheme.typography.caption, color = SecondaryText)
            }
        }
    }
}

// ================= 右栏：AI 面板 =================

/** 右栏 AI 面板（异步生成工作台复用同一套） */
@Composable
internal fun AiPanel(vm: PptViewModel) {
    val i = vm.selected.coerceIn(0, (vm.slides.size - 1).coerceAtLeast(0))
    val slide = vm.slides.getOrNull(i)
    Column(
        Modifier.width(280.dp).fillMaxHeight().background(AiPanelBg).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("AI 助手", fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold, color = Ink)
        Text("当前：第 ${i + 1} 页（${slideTypeLabel(slide?.type ?: "")}）",
            fontSize = 11.5.sp, color = SecondaryText)

        Text("修改本页", fontSize = 11.5.sp, color = SecondaryText)
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            OutlinedButton(enabled = !vm.aiBusy,
                onClick = { vm.aiSlide("rewrite") }) { Text("重写", fontSize = 12.sp) }
            OutlinedButton(enabled = !vm.aiBusy,
                onClick = { vm.aiSlide("expand") }) { Text("扩写", fontSize = 12.sp) }
            OutlinedButton(enabled = !vm.aiBusy,
                onClick = { vm.aiSlide("condense") }) { Text("精简", fontSize = 12.sp) }
        }
        OutlinedButton(enabled = !vm.aiBusy, modifier = Modifier.fillMaxWidth(),
            onClick = {
                vm.aiSlide("custom", "润色本页文字：保持事实、数字与来源不变，表达更流畅正式")
            }) { Text("润色本页", fontSize = 12.sp) }

        // 白底圆角输入框（规范）
        OutlinedTextField(vm.aiInstruction, { vm.aiInstruction = it },
            label = { Text("对 AI 说怎么改这一页", fontSize = 12.sp) },
            modifier = Modifier.fillMaxWidth().heightIn(min = 70.dp, max = 140.dp),
            shape = RoundedCornerShape(10.dp),
            colors = TextFieldDefaults.outlinedTextFieldColors(
                backgroundColor = Color.White,
                focusedBorderColor = Primary, unfocusedBorderColor = Line,
                cursorColor = Primary))
        // 深蓝发送按钮（规范）
        Button(
            enabled = !vm.aiBusy && vm.aiInstruction.isNotBlank(),
            modifier = Modifier.fillMaxWidth(),
            onClick = {
                vm.aiSlide("custom", vm.aiInstruction.trim())
                vm.aiInstruction = ""
            },
            colors = ButtonDefaults.buttonColors(backgroundColor = Primary),
            shape = RoundedCornerShape(8.dp),
        ) { Text(if (vm.aiBusy) "AI 处理中…" else "发送", color = Color.White, fontSize = 13.sp) }

        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
        Text("页面结构", fontSize = 11.5.sp, color = SecondaryText)
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            TextButton(enabled = !vm.aiBusy,
                onClick = { vm.aiStructure("add") }) { Text("后增一页", fontSize = 12.sp, color = Primary) }
            TextButton(enabled = !vm.aiBusy,
                onClick = { vm.aiStructure("split") }) { Text("拆分本页", fontSize = 12.sp, color = Primary) }
            TextButton(enabled = !vm.aiBusy,
                onClick = { vm.aiStructure("merge") }) { Text("合并下页", fontSize = 12.sp, color = Primary) }
        }

        vm.aiNote?.let {
            Text(it, fontSize = 11.5.sp,
                color = if (it.contains("已")) Primary else MaterialTheme.colors.error)
        }
    }
}

// ================= 底部状态栏 =================

@Composable
private fun StatusBar(vm: PptViewModel) {
    val exporting = AppState.pptExporting
    Column {
        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
        Row(
            Modifier.fillMaxWidth().height(56.dp).background(Surface)
                .padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // 左：阶段 / 状态文案
            val msg = vm.exportStage.ifBlank { vm.status ?: "就绪" }
            Text(msg, fontSize = 12.5.sp,
                color = if (msg.contains("失败") || msg.contains("错误"))
                    MaterialTheme.colors.error else Ink2)
            Spacer(Modifier.width(16.dp))
            // 中：浅蓝进度条 + 取消（导出中可见）
            if (exporting) {
                LinearProgressIndicator(
                    modifier = Modifier.width(220.dp).height(4.dp)
                        .clip(RoundedCornerShape(2.dp)),
                    color = ProgressBlue, backgroundColor = Line,
                )
                Spacer(Modifier.width(10.dp))
                TextButton(onClick = { vm.cancelExport() }) {
                    Text("取消", fontSize = 12.sp, color = Ink2)
                }
            }
            Spacer(Modifier.weight(1f))
            // AI 生成入口已提升到顶部；底部仅保留草稿操作，避免两个主按钮重复。
            OutlinedButton(enabled = !vm.busy,
                onClick = { vm.saveDraft() }) { Text("保存草稿", fontSize = 12.5.sp) }
        }
    }
}

/** 生成前确认：说明将真实调用 PPTAgent 渲染并下载 pptx，确认后选择保存位置 */
@Composable
private fun GenerateConfirmDialog(vm: PptViewModel, onDismiss: () -> Unit) {
    val curName = vm.templates
        .firstOrNull { it["id"].str() == vm.templateId }
        ?.get("name").str().ifBlank { "默认模板" }
    AppDialog(
        onDismissRequest = onDismiss,
        title = "AI 生成 PPT",
        subtitle = "将根据当前大纲与所选视觉风格生成可编辑的 .pptx 文件。",
        width = 480.dp,
        actions = {
            AppButton("再改改", onClick = onDismiss, kind = AppButtonKind.SECONDARY)
            Spacer(Modifier.width(8.dp))
            AppButton("确认生成", onClick = {
                onDismiss()
                val target = pickSaveFile(
                    (vm.outlineTitle.ifBlank { "演示文稿" }) + ".pptx") ?: return@AppButton
                // 异步：提交即返回，逐页出图，跑完自动落盘（服务端没部署 /ppt/jobs 时自动回退同步）
                vm.startGenerateAsync(target)
            })
        },
    ) {
        Text("共 ${vm.slides.size} 页 · 模板：$curName", fontSize = 13.sp, color = Ink)
        Spacer(Modifier.height(6.dp))
        Text(
            "AI 会结合当前大纲和所选视觉风格逐页设计并排版，" +
                "不是简单套用本地模板。预计需要 5–15 分钟。底部的“保存草稿”仅保存当前内容，" +
                "不会触发 AI 设计。",
            fontSize = 12.sp, color = Ink2, lineHeight = 18.sp,
        )
        Spacer(Modifier.height(6.dp))
        Text("提交后可立刻切到其他页面，每生成完一页就能在这里看到缩略图；" +
            "全部完成后自动保存到刚才选择的位置。期间可随时取消。",
            fontSize = 12.sp, color = Ink2, lineHeight = 18.sp)
    }
}
