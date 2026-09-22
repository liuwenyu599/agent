package com.judicialai.desktop.features.formatcheck

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Card
import androidx.compose.material.Checkbox
import androidx.compose.material.Divider
import androidx.compose.material.Icon
import androidx.compose.material.OutlinedButton
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Refresh
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.core.platform.pickFiles
import com.judicialai.desktop.core.platform.pickSaveFile
import com.judicialai.desktop.core.utils.bool
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.components.AppButton
import com.judicialai.desktop.design.components.AppButtonKind
import com.judicialai.desktop.design.components.AppButtonSize
import com.judicialai.desktop.design.components.AppDialog
import com.judicialai.desktop.design.components.AppIconButton
import com.judicialai.desktop.design.components.EmptyState
import com.judicialai.desktop.design.components.FilterChip
import com.judicialai.desktop.design.components.LoadingBlock
import com.judicialai.desktop.design.components.NoticeBar
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Danger
import com.judicialai.desktop.design.theme.DangerSoft
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.EpDanger
import com.judicialai.desktop.design.theme.EpPrimary
import com.judicialai.desktop.design.theme.EpWarning
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.LineSubtle
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Muted2
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
import kotlinx.coroutines.delay
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import java.io.File

/**
 * 公文格式审校工作台（三栏）
 *
 * 左：校验记录（上传 / 打开 / 删除）  中：文档预览（版本切换 / 缩放 / 定位高亮）
 * 右：校验结果（修改前后对照 / 应用 / 撤销 / 重新校验 / 导出）
 *
 * 红线：不虚构任何数据，不做页码分页（后端无页码数据，分页会是假功能）。
 */
@Composable
fun FormatCheckScreen() {
    val vm = remember { FormatCheckViewModel(Repositories.formatCheck) }
    var showRules by remember { mutableStateOf(false) }
    val docListState = rememberLazyListState()

    LaunchedEffect(Unit) { vm.loadRecords() }
    LaunchedEffect(showRules) { if (showRules) vm.loadRules() }

    Column(Modifier.fillMaxSize().background(AppBg)) {
        // ---------- 页头 ----------
        Row(
            Modifier.fillMaxWidth().background(Surface).padding(horizontal = Dimens.space5,
                vertical = Dimens.space3),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text("公文格式审校", fontSize = 18.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                Text("上传 Word 文档 → 定位原文 → 逐条应用修改 → 导出修正稿（原文件不变）",
                    fontSize = 12.sp, color = Muted)
            }
            FilterChip("审校工作台", selected = !showRules, onClick = { showRules = false })
            Spacer(Modifier.width(Dimens.space2))
            FilterChip("规则管理", selected = showRules, onClick = { showRules = true })
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))

        if (showRules) {
            RulesPanel(vm, Modifier.weight(1f).padding(Dimens.space5))
        } else {
            Row(Modifier.weight(1f).fillMaxWidth()) {
                RecordsColumn(vm, Modifier.width(260.dp).fillMaxHeight())
                Box(Modifier.width(1.dp).fillMaxHeight().background(Line))
                DocumentColumn(vm, docListState, Modifier.weight(0.55f).fillMaxHeight())
                Box(Modifier.width(1.dp).fillMaxHeight().background(Line))
                IssuesColumn(vm, Modifier.weight(0.35f).fillMaxHeight())
            }
        }
    }
}

// ============================================================
// 左栏：校验记录
// ============================================================

@Composable
private fun RecordsColumn(vm: FormatCheckViewModel, modifier: Modifier = Modifier) {
    var pendingDelete by remember { mutableStateOf<JsonObject?>(null) }

    Column(modifier.background(SurfaceDeep)) {
        Row(
            Modifier.fillMaxWidth().background(Surface).padding(horizontal = Dimens.space4,
                vertical = Dimens.space3),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("校验记录", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Ink,
                modifier = Modifier.weight(1f))
            AppIconButton(Icons.Default.Refresh, "刷新记录", onClick = { vm.loadRecords() },
                tint = Ink2, size = 28.dp)
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))

        Column(Modifier.fillMaxWidth().padding(Dimens.space3),
            verticalArrangement = Arrangement.spacedBy(Dimens.space2)) {
            AppButton(
                text = if (vm.busy) "处理中…" else "上传并校验",
                onClick = {
                    val f = pickFiles("选择 Word 文档（.docx）").firstOrNull()
                    when {
                        f == null -> vm.onSaveCancelled()
                        !f.name.endsWith(".docx", ignoreCase = true) ->
                            vm.error = "只支持 .docx 文件"
                        else -> vm.check(f)
                    }
                },
                icon = Icons.Default.Add,
                kind = AppButtonKind.PRIMARY,
                size = AppButtonSize.SM,
                enabled = !vm.busy,
                loading = vm.busy,
                fill = true,
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = vm.useAi, onCheckedChange = { vm.useAi = it })
                Text("AI 辅助判断", fontSize = 12.sp, color = Ink2)
            }
        }

        if (vm.records.isEmpty()) {
            EmptyState(
                text = "还没有校验记录",
                hint = "点上方「上传并校验」上传 .docx 开始",
                icon = Icons.Default.Description,
                modifier = Modifier.padding(Dimens.space4),
            )
        } else {
            LazyColumn(
                Modifier.fillMaxWidth().weight(1f)
                    .padding(horizontal = Dimens.space3, vertical = Dimens.space2),
                verticalArrangement = Arrangement.spacedBy(Dimens.space2),
            ) {
                items(vm.records, key = { recIdOf(it) }) { rec ->
                    RecordRow(
                        rec = rec,
                        selected = vm.currentRecordId == recIdOf(rec),
                        onOpen = { vm.openRecord(recIdOf(rec)) },
                        onDelete = { pendingDelete = rec },
                    )
                }
            }
        }
    }

    pendingDelete?.let { rec ->
        AppDialog(
            onDismissRequest = { pendingDelete = null },
            title = "删除校验记录",
            subtitle = rec["filename"].str().ifBlank { "未命名文档" },
            width = 440.dp,
            actions = {
                AppButton("取消", onClick = { pendingDelete = null },
                    kind = AppButtonKind.SECONDARY)
                Spacer(Modifier.width(Dimens.space2))
                AppButton("删除", onClick = {
                    vm.deleteRecord(recIdOf(rec))
                    pendingDelete = null
                }, kind = AppButtonKind.DANGER)
            },
        ) {
            Text("删除后该记录及其问题清单不可恢复，源文件不受影响。",
                fontSize = 13.sp, color = Ink2)
        }
    }
}

@Composable
private fun RecordRow(
    rec: JsonObject,
    selected: Boolean,
    onOpen: () -> Unit,
    onDelete: () -> Unit,
) {
    val shape = RoundedCornerShape(Dimens.radiusMd)
    Row(
        Modifier.fillMaxWidth().clip(shape)
            .background(if (selected) PrimarySoft else Surface)
            .border(1.dp, if (selected) Primary else Line, shape)
            .clickable { onOpen() }
            .padding(horizontal = Dimens.space3, vertical = Dimens.space2),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(rec["filename"].str().ifBlank { "未命名文档" }, fontSize = 12.5.sp,
                fontWeight = FontWeight.Medium, color = Ink, maxLines = 1,
                overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.height(2.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("${rec["issue_count"].int()} 项问题", fontSize = 11.sp, color = Muted)
                Spacer(Modifier.width(Dimens.space2))
                Text(rec["created_at"].str().take(16).replace("T", " "),
                    fontSize = 11.sp, color = Muted2)
            }
        }
        AppIconButton(Icons.Default.Delete, "删除记录", onClick = onDelete, tint = Danger,
            size = 26.dp)
    }
}

// ============================================================
// 中栏：文档预览
// ============================================================

@Composable
private fun DocumentColumn(
    vm: FormatCheckViewModel,
    listState: androidx.compose.foundation.lazy.LazyListState,
    modifier: Modifier = Modifier,
) {
    val paragraphs = if (vm.version == DocVersion.ORIGINAL) vm.paragraphsOriginal
    else vm.paragraphsCurrent
    var flashIndex by remember { mutableStateOf<Int?>(null) }

    /** 段落下标 → 命中的问题下标列表（用于段落上的问题徽标） */
    val issuesByPara: Map<Int, List<Int>> = remember(vm.issues) {
        val map = mutableMapOf<Int, MutableList<Int>>()
        vm.issues.forEachIndexed { i, issue ->
            val pi = paraIndexOf(issue)
            if (pi != null) map.getOrPut(pi) { mutableListOf() }.add(i)
        }
        map
    }

    // 选中问题 → 滚动到对应段落并短暂高亮；无 paragraph_index 时不滚动（由右栏提示）
    LaunchedEffect(vm.selectedIssueId) {
        val idx = vm.selectedIssueId?.let { paraIndexOf(vm.issues.getOrNull(it)) }
        if (idx == null) {
            flashIndex = null
            return@LaunchedEffect
        }
        listState.animateScrollToItem(idx)
        flashIndex = idx
        delay(2500)
        flashIndex = null
    }

    Column(modifier.background(Surface)) {
        // 工具条
        Row(
            Modifier.fillMaxWidth().background(Surface).padding(horizontal = Dimens.space4,
                vertical = Dimens.space3),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            DocVersion.values().forEach { v ->
                FilterChip(v.label, selected = vm.version == v, onClick = { vm.version = v })
                Spacer(Modifier.width(Dimens.space2))
            }
            Spacer(Modifier.weight(1f))
            DocZoom.values().forEach { z ->
                FilterChip(z.label, selected = vm.zoom == z, onClick = { vm.zoom = z })
                Spacer(Modifier.width(Dimens.space1))
            }
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))

        Row(
            Modifier.fillMaxWidth().background(SurfaceTonal)
                .padding(horizontal = Dimens.space4, vertical = Dimens.space2),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(vm.currentRecord?.get("filename")?.str().orEmpty().ifBlank { "未选择文档" },
                fontSize = 12.sp, color = Ink2, modifier = Modifier.weight(1f),
                maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text("已修改 ${vm.appliedCount} 处", fontSize = 12.sp, color = Ok,
                fontWeight = FontWeight.Medium)
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(LineSubtle))

        when {
            vm.currentRecordId == null -> {
                EmptyState(
                    text = "还没有打开文档",
                    hint = "从左侧选择一条校验记录，或上传新的 .docx",
                    icon = Icons.Default.Description,
                    modifier = Modifier.padding(Dimens.space5),
                )
            }
            vm.busy && paragraphs.isEmpty() -> LoadingBlock("正在读取文档内容…")
            paragraphs.isEmpty() -> {
                EmptyState(
                    text = "没有读到文档内容",
                    hint = "服务端未返回段落数据，可能是源文件已过期，请重新上传校验",
                    icon = Icons.Default.Description,
                    modifier = Modifier.padding(Dimens.space5),
                )
            }
            else -> SelectionContainer(
                modifier = Modifier.fillMaxWidth().weight(1f),
            ) {
                LazyColumn(
                    state = listState,
                    modifier = Modifier.fillMaxWidth().background(Surface)
                        .padding(horizontal = Dimens.space6, vertical = Dimens.space4),
                    verticalArrangement = Arrangement.spacedBy(Dimens.space2),
                ) {
                    itemsIndexed(paragraphs) { index, p ->
                        ParagraphBlock(
                            vm = vm,
                            p = p,
                            index = index,
                            zoom = vm.zoom,
                            flashing = flashIndex == index,
                            issueIndexesOnPara = issuesByPara[index] ?: emptyList(),
                        )
                    }
                }
            }
        }
    }
}

/** 单段渲染：只按后端真实属性呈现，属性缺失则按默认，不伪造排版 */
@Composable
private fun ParagraphBlock(
    vm: FormatCheckViewModel,
    p: JsonObject,
    index: Int,
    zoom: DocZoom,
    flashing: Boolean,
    issueIndexesOnPara: List<Int>,
) {
    val text = p["text"].str()
    val fontPt = doubleOf(p["font_pt"]) ?: 16.0
    val fontSize = (zoom.baseSp * (fontPt / 16.0)).toFloat().coerceIn(8f, 40f).sp
    // pt → dp：1pt = 160/72 dp（与 Android 的 pt→dp 换算一致）
    val spaceBefore = (doubleOf(p["space_before_pt"]) ?: 0.0) * 160f / 72f
    val spaceAfter = (doubleOf(p["space_after_pt"]) ?: 0.0) * 160f / 72f
    val lineSpacing = doubleOf(p["line_spacing"])
    val indentChars = doubleOf(p["indent_chars"]) ?: 0.0
    val bold = p["bold"].bool(false)
    val align = when (p["align"].str().lowercase()) {
        "center" -> TextAlign.Center
        "right" -> TextAlign.Right
        "justify" -> TextAlign.Justify
        else -> TextAlign.Start
    }
    val isHeading = p["is_heading"].bool(false)
    val shape = RoundedCornerShape(Dimens.radiusSm)

    Row(
        Modifier.fillMaxWidth()
            .clip(shape)
            .background(if (flashing) PrimarySoft else Color.Transparent)
            .border(1.dp, if (flashing) Primary else Color.Transparent, shape)
            .padding(
                top = spaceBefore.dp,
                bottom = spaceAfter.dp,
                start = Dimens.space2,
                end = Dimens.space2,
            )
            .padding(vertical = 2.dp),
    ) {
        // 段落序号（朴素灰，与「有问题」的彩色徽标在视觉上明确区分）
        Text(
            "${index + 1}",
            fontSize = 11.sp,
            color = if (flashing) Primary else Muted2,
            fontWeight = if (flashing) FontWeight.SemiBold else FontWeight.Normal,
            modifier = Modifier.width(26.dp).padding(top = 2.dp),
            textAlign = TextAlign.End,
        )
        Spacer(Modifier.width(Dimens.space2))
        Column(Modifier.weight(1f)) {
            if (issueIndexesOnPara.isNotEmpty()) {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(Dimens.space1),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    issueIndexesOnPara.forEach { issueIndex ->
                        val sev = severityOf(vm.issues.getOrNull(issueIndex) ?: JsonObject(emptyMap()))
                        // 已修正 → ✓✓；已应用 → ✓；未处理 → !
                        val mark = when {
                            vm.isResolved(issueIndex) -> "✓✓"
                            vm.isApplied(issueIndex) -> "✓"
                            else -> "!"
                        }
                        Box(
                            Modifier.clip(RoundedCornerShape(Dimens.radiusPill))
                                .background(severityBg(sev))
                                .padding(horizontal = 6.dp, vertical = 1.dp),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                mark,
                                fontSize = 10.sp, fontWeight = FontWeight.SemiBold,
                                color = severityFg(sev),
                            )
                        }
                    }
                }
            }
            if (text.isBlank()) {
                // 空段落保留占位高度，避免正文结构看起来塌陷
                Text("", fontSize = fontSize, modifier = Modifier.fillMaxWidth().height(8.dp))
            } else {
                Text(
                    text,
                    fontSize = fontSize,
                    fontWeight = if (bold || isHeading) FontWeight.Bold else FontWeight.Normal,
                    color = Ink,
                    textAlign = align,
                    // line_spacing 缺失时不设 lineHeight，交给字体默认行高（不伪造行距）
                    lineHeight = if (lineSpacing != null && lineSpacing > 0.0)
                        (fontSize.value * lineSpacing).toFloat().sp else TextUnit.Unspecified,
                    modifier = Modifier.fillMaxWidth()
                        .padding(start = (indentChars * fontSize.value).dp),
                )
            }
        }
    }
}

// ============================================================
// 右栏：校验结果
// ============================================================

private val SEVERITY_GROUPS = listOf(
    "error" to "错误",
    "warning" to "警告",
    "info" to "建议",
)

@Composable
private fun IssuesColumn(vm: FormatCheckViewModel, modifier: Modifier = Modifier) {
    Column(modifier.background(SurfaceDeep)) {
        Row(
            Modifier.fillMaxWidth().background(Surface).padding(horizontal = Dimens.space4,
                vertical = Dimens.space3),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text("校验结果", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                Text("共 ${vm.issues.size} 项 · 已修改 ${vm.appliedCount} 项 · 未解决 ${vm.openIssueCount} 项",
                    fontSize = 11.5.sp, color = Muted)
            }
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))

        Row(
            Modifier.fillMaxWidth().background(Surface)
                .padding(horizontal = Dimens.space4, vertical = Dimens.space2),
            horizontalArrangement = Arrangement.spacedBy(Dimens.space2),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            AppButton("重新校验", onClick = { vm.recheck() }, kind = AppButtonKind.SECONDARY,
                size = AppButtonSize.SM, enabled = !vm.busy && vm.currentRecordId != null,
                icon = Icons.Default.Refresh, modifier = Modifier.weight(1f))
            AppButton("导出修正稿", onClick = {
                val t = pickSaveFile("修正稿.docx")
                if (t == null) vm.onSaveCancelled() else vm.export(t)
            }, kind = AppButtonKind.PRIMARY, size = AppButtonSize.SM,
                enabled = !vm.busy && vm.currentRecordId != null,
                icon = Icons.Default.Download, modifier = Modifier.weight(1f))
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))

        vm.error?.let {
            NoticeBar(it, Danger, DangerSoft,
                Modifier.fillMaxWidth().padding(Dimens.space3))
        }
        // 中性提示（如纯 AI 记录跳过规则复检）：不是错误，用中性色而不是红条
        vm.notice?.let {
            NoticeBar(it, Ink2, SurfaceTonal,
                Modifier.fillMaxWidth().padding(Dimens.space3))
        }
        vm.status?.let {
            NoticeBar(it, Ok, OkSoft, Modifier.fillMaxWidth().padding(Dimens.space3))
        }

        if (vm.currentRecordId == null) {
            EmptyState(
                text = "还没有校验结果",
                hint = "打开或上传一条记录后，这里会按错误 / 警告 / 建议分组显示",
                modifier = Modifier.padding(Dimens.space4),
            )
        } else if (vm.issues.isEmpty()) {
            EmptyState(
                text = "没有发现问题",
                hint = "可点「重新校验」再跑一次",
                modifier = Modifier.padding(Dimens.space4),
            )
        } else {
            LazyColumn(
                Modifier.fillMaxWidth().weight(1f)
                    .padding(horizontal = Dimens.space3, vertical = Dimens.space2),
                verticalArrangement = Arrangement.spacedBy(Dimens.space2),
            ) {
                SEVERITY_GROUPS.forEach { (sev, label) ->
                    val group = vm.issues.mapIndexed { i, issue -> i to issue }
                        .filter { severityOf(it.second) == sev }
                    if (group.isEmpty()) return@forEach
                    item(key = "hdr:$sev") {
                        Row(
                            Modifier.fillMaxWidth().padding(vertical = Dimens.space2),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Box(Modifier.size(6.dp).clip(RoundedCornerShape(3.dp))
                                .background(severityFg(sev)))
                            Spacer(Modifier.width(Dimens.space2))
                            Text("$label ${group.size}", fontSize = 12.sp,
                                fontWeight = FontWeight.SemiBold, color = Ink2)
                        }
                    }
                    items(group, key = { "issue:${it.first}" }) { (index, issue) ->
                        IssueCard(
                            vm = vm,
                            index = index,
                            issue = issue,
                            selected = vm.selectedIssueId == index,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun IssueCard(
    vm: FormatCheckViewModel,
    index: Int,
    issue: JsonObject,
    selected: Boolean,
) {
    val sev = severityOf(issue)
    val resolved = vm.isResolved(index)
    val applied = vm.isApplied(index)
    val shape = RoundedCornerShape(Dimens.radiusMd)
    Column(
        Modifier.fillMaxWidth()
            .clip(shape)
            .background(if (selected) PrimarySoft else Surface)
            .border(1.dp, if (selected) Primary else Line, shape)
            .clickable { vm.selectedIssueId = index }
            .padding(Dimens.space3),
        verticalArrangement = Arrangement.spacedBy(Dimens.space1),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.clip(RoundedCornerShape(Dimens.radiusPill))
                    .background(severityBg(sev))
                    .padding(horizontal = 7.dp, vertical = 2.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    when (sev) { "error" -> "错误"; "warning" -> "警告"; else -> "建议" },
                    fontSize = 10.5.sp, fontWeight = FontWeight.SemiBold, color = severityFg(sev),
                )
            }
            Spacer(Modifier.width(Dimens.space2))
            Text(issue["element"].str().ifBlank { "格式项" }, fontSize = 12.5.sp,
                fontWeight = FontWeight.Medium, color = Ink,
                modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Text(issue["location"].str().ifBlank { "全文" }, fontSize = 11.5.sp, color = Muted)

        // 修改前 → 修改后（数据来自后端 current / expected，不自行编造文案）
        val current = issue["current"].str()
        val expected = issue["expected"].str()
        if (current.isNotBlank() || expected.isNotBlank()) {
            Spacer(Modifier.height(Dimens.space1))
            Column(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(Dimens.radiusSm))
                    .background(SurfaceTonal).padding(Dimens.space2),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                CompareRow("修改前", current, Danger)
                CompareRow("修改后", expected, Ok)
            }
        }
        val suggestion = issue["suggestion"].str()
        if (suggestion.isNotBlank()) {
            Text(suggestion, fontSize = 11.5.sp, color = Ink2, lineHeight = 17.sp)
        }

        Spacer(Modifier.height(Dimens.space1))
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (paraIndexOf(issue) == null) {
                Text("该问题无段落定位", fontSize = 11.sp, color = Muted2,
                    modifier = Modifier.weight(1f))
            } else {
                Text("定位第 ${paraIndexOf(issue)!! + 1} 段", fontSize = 11.sp, color = Primary,
                    modifier = Modifier.weight(1f))
            }
            if (!hasFixHint(issue)) {
                // fix_hint 缺失（AI 类 / 页面级问题）：无法自动修复，不给按钮
                Text("需人工修改", fontSize = 11.5.sp, color = Muted)
            } else if (resolved) {
                // 已修正：重新校验确认已写入文档，不可撤销
                Text("已修正 ✓", fontSize = 12.sp, color = Ok, fontWeight = FontWeight.Medium)
            } else if (applied) {
                // 已应用但尚未复检：可撤销
                Text("已应用 ✓", fontSize = 12.sp, color = Primary,
                    fontWeight = FontWeight.Medium)
                Spacer(Modifier.width(Dimens.space2))
                AppButton("撤销", onClick = { vm.undoIssue(index) },
                    kind = AppButtonKind.SECONDARY, size = AppButtonSize.SM,
                    enabled = !vm.busy)
            } else {
                AppButton("应用修改", onClick = { vm.applyIssue(index) },
                    kind = AppButtonKind.PRIMARY, size = AppButtonSize.SM,
                    enabled = !vm.busy, loading = vm.busy)
            }
        }
    }
}

@Composable
private fun CompareRow(label: String, value: String, color: Color) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
        Text(label, fontSize = 11.sp, color = Muted, modifier = Modifier.width(48.dp))
        Text(value.ifBlank { "—" }, fontSize = 11.5.sp, color = if (value.isBlank()) Muted2 else color,
            modifier = Modifier.weight(1f), lineHeight = 17.sp)
    }
}

// ============================================================
// 工具函数
// ============================================================

/** 记录 id：check 响应与历史列表项字段名不一致，两个都认 */
private fun recIdOf(rec: JsonObject): String =
    (rec["id"] ?: rec["record_id"])?.str()?.trim().orEmpty()

private fun severityOf(issue: JsonObject): String = when (issue["severity"].str()) {
    "error" -> "error"
    "warning" -> "warning"
    else -> "info"
}

private fun severityFg(sev: String): Color = when (sev) {
    "error" -> Danger
    "warning" -> Warn
    else -> Ok
}

private fun severityBg(sev: String): Color = when (sev) {
    "error" -> DangerSoft
    "warning" -> WarnSoft
    else -> OkSoft
}

/** 段落下标；页面级 / AI 级问题没有段落定位时为 null */
private fun paraIndexOf(issue: JsonObject?): Int? =
    (issue?.get("paragraph_index") as? JsonPrimitive)?.intOrNull

/** fix_hint 缺失或为 null 的问题无法自动修复，不给「应用修改」按钮 */
private fun hasFixHint(issue: JsonObject): Boolean {
    val v = issue["fix_hint"]
    return v != null && v !is JsonNull
}

private fun doubleOf(el: kotlinx.serialization.json.JsonElement?): Double? =
    (el as? JsonPrimitive)?.content?.toDoubleOrNull()

// ============================================================
// 规则管理（沿用既有实现，不在三栏内）
// ============================================================

private val RULE_TARGETS = listOf(
    "page" to "页面设置", "title" to "标题", "body" to "正文",
    "heading1" to "一级标题", "heading2" to "二级标题",
    "signature" to "落款", "date" to "成文日期", "general" to "全文通用",
)
private val RULE_SEVERITIES = listOf("error" to "严重", "warning" to "警告", "info" to "提示")

@Composable
private fun RulesPanel(vm: FormatCheckViewModel, modifier: Modifier = Modifier) {
    val form = vm.editingRule
    if (form != null) {
        RuleEditor(vm, form, modifier)
        return
    }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("格式规则（为空时校验自动降级为 AI 全面审查）", fontSize = 12.sp,
                color = TextSecondary, modifier = Modifier.weight(1f))
            Button(onClick = { vm.openRuleEditor(null) },
                colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary)) {
                Text("新建规则", color = Color.White, fontSize = 13.sp)
            }
        }
        Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp,
            modifier = Modifier.weight(1f).fillMaxWidth()) {
            Column {
                Row(Modifier.fillMaxWidth().background(Color(0xFFFAFAFA))
                    .padding(horizontal = 16.dp, vertical = 10.dp)) {
                    Text("名称", Modifier.weight(1.4f), fontSize = 12.sp, color = TextSecondary)
                    Text("对象", Modifier.width(100.dp), fontSize = 12.sp, color = TextSecondary)
                    Text("程度", Modifier.width(70.dp), fontSize = 12.sp, color = TextSecondary)
                    Text("默认", Modifier.width(60.dp), fontSize = 12.sp, color = TextSecondary)
                    Text("启用", Modifier.width(60.dp), fontSize = 12.sp, color = TextSecondary)
                    Text("操作", Modifier.width(130.dp), fontSize = 12.sp, color = TextSecondary)
                }
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    if (vm.rules.isEmpty()) {
                        Box(Modifier.fillMaxWidth().padding(40.dp),
                            contentAlignment = Alignment.Center) {
                            Text("尚未配置规则，上传文档时将使用 AI 全面审查",
                                color = TextSecondary, fontSize = 13.sp)
                        }
                    }
                    vm.rules.forEach { rule ->
                        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Text(rule["name"].str(), Modifier.weight(1.4f), fontSize = 13.sp,
                                color = TextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(RULE_TARGETS.firstOrNull { it.first == rule["target"].str() }?.second
                                ?: rule["target"].str(),
                                Modifier.width(100.dp), fontSize = 12.sp, color = TextRegular)
                            Box(Modifier.width(70.dp)) {
                                SevTag(RULE_SEVERITIES.firstOrNull {
                                    it.first == rule["severity"].str() }?.second ?: "提示",
                                    when (rule["severity"].str()) {
                                        "error" -> EpDanger; "warning" -> EpWarning; else -> EpPrimary
                                    })
                            }
                            Text(if (rule["is_default"].bool()) "是" else "否",
                                Modifier.width(60.dp), fontSize = 12.sp, color = TextRegular)
                            Text(if (rule["is_active"].bool(true)) "启用" else "停用",
                                Modifier.width(60.dp), fontSize = 12.sp, color = TextRegular)
                            Row(Modifier.width(130.dp)) {
                                TextButton(onClick = { vm.openRuleEditor(rule) }) {
                                    Text("编辑", color = EpPrimary, fontSize = 12.sp)
                                }
                                TextButton(onClick = { vm.deleteRule(rule["id"].str()) }) {
                                    Text("删除", color = EpDanger, fontSize = 12.sp)
                                }
                            }
                        }
                        Divider(color = Color(0xFFF2F4F8))
                    }
                }
            }
        }
    }
}

@Composable
private fun RuleEditor(vm: FormatCheckViewModel, form: RuleForm, modifier: Modifier = Modifier) {
    var name by remember { mutableStateOf(form.name) }
    var target by remember { mutableStateOf(form.target) }
    var severity by remember { mutableStateOf(form.severity) }
    var checksJson by remember { mutableStateOf(form.checksJson) }
    var remark by remember { mutableStateOf(form.remark) }
    var isDefault by remember { mutableStateOf(form.isDefault) }
    var isActive by remember { mutableStateOf(form.isActive) }

    Card(modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), elevation = 0.dp) {
        Column(Modifier.padding(16.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(if (form.id.isBlank()) "新建规则" else "编辑规则",
                fontSize = 16.sp, fontWeight = FontWeight.Bold, color = TextPrimary)
            androidx.compose.material.OutlinedTextField(
                name, { name = it }, label = { Text("规则名称") },
                modifier = Modifier.fillMaxWidth(), singleLine = true)
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Column(Modifier.weight(1f)) {
                    Text("校验对象", fontSize = 12.sp, color = TextSecondary)
                    Row(Modifier.verticalScroll(rememberScrollState()).heightIn(max = 120.dp)) {
                        Column {
                            RULE_TARGETS.forEach { (key, label) ->
                                Row(verticalAlignment = Alignment.CenterVertically,
                                    modifier = Modifier.clickable { target = key }) {
                                    androidx.compose.material.RadioButton(
                                        selected = target == key, onClick = { target = key })
                                    Text(label, fontSize = 12.sp)
                                }
                            }
                        }
                    }
                }
                Column(Modifier.weight(1f)) {
                    Text("严重程度", fontSize = 12.sp, color = TextSecondary)
                    RULE_SEVERITIES.forEach { (key, label) ->
                        Row(verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.clickable { severity = key }) {
                            androidx.compose.material.RadioButton(
                                selected = severity == key, onClick = { severity = key })
                            Text(label, fontSize = 12.sp)
                        }
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(isDefault, { isDefault = it })
                        Text("默认规则", fontSize = 12.sp)
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(isActive, { isActive = it })
                        Text("启用", fontSize = 12.sp)
                    }
                }
            }
            androidx.compose.material.OutlinedTextField(
                checksJson, { checksJson = it },
                label = { Text("校验项（JSON，如 {\"font_name\":\"仿宋_GB2312\",\"font_size_pt\":16}）") },
                modifier = Modifier.fillMaxWidth().height(120.dp))
            androidx.compose.material.OutlinedTextField(
                remark, { remark = it }, label = { Text("备注") },
                modifier = Modifier.fillMaxWidth(), singleLine = true)
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(enabled = !vm.busy, onClick = {
                    vm.editingRule = form.copy(name = name, target = target, severity = severity,
                        checksJson = checksJson, remark = remark,
                        isDefault = isDefault, isActive = isActive)
                    vm.saveRule()
                }, colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary)) {
                    Text("保存", color = Color.White)
                }
                OutlinedButton(onClick = { vm.editingRule = null }) { Text("取消") }
            }
        }
    }
}

@Composable
private fun SevTag(text: String, color: Color) {
    Box(
        Modifier.clip(RoundedCornerShape(4.dp)).background(color.copy(alpha = 0.12f))
            .padding(horizontal = 6.dp, vertical = 2.dp),
        contentAlignment = Alignment.Center,
    ) { Text(text, fontSize = 11.sp, color = color) }
}
