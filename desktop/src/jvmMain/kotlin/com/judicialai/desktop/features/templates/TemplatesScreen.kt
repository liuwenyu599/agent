package com.judicialai.desktop.features.templates

import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Checkbox
import androidx.compose.material.Icon
import androidx.compose.material.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.LibraryBooks
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.bool
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.components.AppButton
import com.judicialai.desktop.design.components.AppButtonKind
import com.judicialai.desktop.design.components.AppDialog
import com.judicialai.desktop.design.components.AppIconButton
import com.judicialai.desktop.design.components.AppSearchField
import com.judicialai.desktop.design.components.AppTextField
import com.judicialai.desktop.design.components.ContextBlock
import com.judicialai.desktop.design.components.DocumentSurface
import com.judicialai.desktop.design.components.EmptyState
import com.judicialai.desktop.design.components.FieldError
import com.judicialai.desktop.design.components.FilterChip
import com.judicialai.desktop.design.components.InlineNotice
import com.judicialai.desktop.design.components.PageHeader
import com.judicialai.desktop.design.components.SectionTitle
import com.judicialai.desktop.design.components.TagChip
import com.judicialai.desktop.design.theme.AiIndigo
import com.judicialai.desktop.design.theme.AiSoft
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.EmeraldInk
import com.judicialai.desktop.design.theme.EmeraldSoft
import com.judicialai.desktop.design.theme.FeatureTemplateEnd
import com.judicialai.desktop.design.theme.FeatureTemplateInk
import com.judicialai.desktop.design.theme.FeatureTemplateSoft
import com.judicialai.desktop.design.theme.FeatureTemplateStart
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.LineSubtle
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Muted2
import com.judicialai.desktop.design.theme.OnPrimaryText
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.PrimarySoft
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.SurfaceTonal
import com.judicialai.desktop.design.theme.VioletInk
import com.judicialai.desktop.design.theme.VioletSoft
import kotlinx.serialization.json.JsonObject

/**
 * 模板中心（v4.0）
 *
 * 强化「系统模板 → 科室模板 → 我的模板」三层资产关系：
 * 三层用可点击的资产卡表达，列表行带类型 / 归属 / 说明 / 使用情况，
 * 右侧是真实模板结构预览，「AI 调整模板」是模板中心的重要能力而非重新生成。
 *
 * 「使用模板」不再弹窗出文：右侧内联填好要素后点「生成」，
 * 直接进入智能写作工作台（自动创建绑定该模板的任务并起草）。
 * 从写作工作台「返回模板重新填写要素」时自动重开该模板并回填已填要素。
 */
@Composable
fun TemplatesScreen() {
    val vm = remember { TemplatesViewModel(Repositories.templates) }
    LaunchedEffect(Unit) { vm.load() }

    // 写作工作台「返回模板重新填写要素」：模板加载完成后自动选中并打开填写面板
    LaunchedEffect(vm.templates) {
        val id = AppState.pendingTemplateUseId ?: return@LaunchedEffect
        val t = vm.templates.firstOrNull { it["id"].str() == id } ?: return@LaunchedEffect
        AppState.pendingTemplateUseId = null
        vm.select(t)
        vm.startUse(t)
    }

    var search by remember { mutableStateOf("") }
    var showCreate by remember { mutableStateOf(false) }
    var showAdapt by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<JsonObject?>(null) }
    var pendingDelete by remember { mutableStateOf<JsonObject?>(null) }

    val all = vm.shown()
    val filtered = all.filter { t ->
        search.isBlank() || t["name"].str().contains(search, true) ||
            t["description"].str().contains(search, true) ||
            t["category"].str().contains(search, true)
    }

    Box(Modifier.fillMaxSize().background(AppBg)) {
        Column(
            Modifier.fillMaxSize()
                .padding(horizontal = Dimens.space6, vertical = Dimens.space5),
        ) {
            PageHeader(
                title = "模板中心",
                subtitle = "系统模板为统一口径，科室模板按本科室写作习惯调整，我的模板为个人常用",
                eyebrow = "写作资产",
                actions = {
                    Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space2)) {
                        AppButton("初始化内置模板", onClick = { vm.initBuiltin() },
                            kind = AppButtonKind.SECONDARY)
                        AppButton("新建模板", onClick = { showCreate = true },
                            kind = AppButtonKind.PRIMARY)
                    }
                },
            )

            // 三层资产关系
            TierRow(vm)

            Spacer(Modifier.height(Dimens.space4))

            Row(Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(Dimens.space4)) {
                // 左：模板列表
                Column(Modifier.weight(1f).fillMaxHeight()) {
                    Row(
                        Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(Dimens.space2),
                    ) {
                        AppSearchField(
                            value = search,
                            onValueChange = { search = it },
                            placeholder = "搜索模板名称 / 类型 / 说明",
                            modifier = Modifier.weight(1f),
                        )
                    }
                    Spacer(Modifier.height(Dimens.space3))
                    if (vm.categories.isNotEmpty()) {
                        Row(
                            Modifier.fillMaxWidth().verticalScroll(rememberScrollState()),
                            horizontalArrangement = Arrangement.spacedBy(Dimens.space2),
                        ) {
                            FilterChip("全部类型", vm.filterCat == null, onClick = { vm.filterCat = null })
                            vm.categories.forEach { c ->
                                FilterChip(c, vm.filterCat == c, onClick = { vm.filterCat = c })
                            }
                        }
                        Spacer(Modifier.height(Dimens.space3))
                    }
                    if (filtered.isEmpty()) {
                        EmptyState(
                            text = "没有符合条件的模板",
                            hint = "换个类型或关键词，或从内置模板初始化",
                            icon = Icons.Default.LibraryBooks,
                        )
                    } else {
                        Column(
                            Modifier.fillMaxWidth().weight(1f)
                                .verticalScroll(rememberScrollState()),
                            verticalArrangement = Arrangement.spacedBy(Dimens.space3),
                        ) {
                            filtered.forEach { t ->
                                TemplateRow(
                                    vm = vm,
                                    t = t,
                                    onAdapt = { showAdapt = true },
                                    onEdit = { editing = t },
                                    onDelete = { pendingDelete = t },
                                )
                            }
                            Spacer(Modifier.height(Dimens.space4))
                        }
                    }
                }

                // 右：填表使用（内联）或结构预览
                val using = vm.usingTemplate
                if (using != null) {
                    UsePanel(vm, using, Modifier.width(420.dp).fillMaxHeight())
                } else {
                    PreviewPane(vm, Modifier.width(420.dp).fillMaxHeight(),
                        onAdapt = { showAdapt = true })
                }
            }
        }
    }

    vm.status?.let {
        Box(Modifier.padding(horizontal = Dimens.space6)) { FieldError(it) }
    }

    if (showCreate || editing != null) {
        TemplateEditDialog(
            editing = editing,
            onDismiss = { showCreate = false; editing = null },
            onSubmit = { body ->
                vm.save(editing, body)
                showCreate = false
                editing = null
            },
        )
    }

    if (showAdapt) {
        AdaptDialog(
            vm = vm,
            onDismiss = { showAdapt = false; vm.cancelDraft() },
        )
    }

    pendingDelete?.let { t ->
        AppDialog(
            onDismissRequest = { pendingDelete = null },
            title = "删除模板",
            subtitle = "删除后无法恢复，请确认该模板不再使用。",
            width = 460.dp,
            actions = {
                AppButton("取消", onClick = { pendingDelete = null }, kind = AppButtonKind.SECONDARY)
                Spacer(Modifier.width(Dimens.space2))
                AppButton("确认删除", onClick = {
                    vm.delete(t["id"].str())
                    pendingDelete = null
                })
            },
        ) {
            Text("模板：${t["name"].str().ifBlank { "未命名模板" }}",
                fontSize = 13.sp, color = Ink2)
        }
    }
}

// ---------------- 三层资产 ----------------

@Composable
private fun TierRow(vm: TemplatesViewModel) {
    val all = vm.templates
    val counts = mapOf(
        null to all.size,
        "system" to all.count { vm.tierOf(it) == "system" },
        "department" to all.count { vm.tierOf(it) == "department" },
        "mine" to all.count { vm.tierOf(it) == "mine" },
    )
    Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space3)) {
        TierCard(
            title = "系统模板", hint = "全局统一口径，所有科室可用",
            count = counts["system"] ?: 0,
            start = FeatureTemplateStart, end = FeatureTemplateEnd,
            selected = vm.tier == "system",
            modifier = Modifier.weight(1f),
        ) { vm.tier = if (vm.tier == "system") null else "system" }
        TierCard(
            title = "科室模板", hint = "按${AppState.departmentName.ifBlank { "本科室" }}写作习惯调整",
            count = counts["department"] ?: 0,
            start = AiIndigo, end = Primary,
            selected = vm.tier == "department",
            modifier = Modifier.weight(1f),
        ) { vm.tier = if (vm.tier == "department") null else "department" }
        TierCard(
            title = "我的模板", hint = "个人常用，仅本人可见",
            count = counts["mine"] ?: 0,
            start = VioletInk, end = VioletInk,
            selected = vm.tier == "mine",
            modifier = Modifier.weight(1f),
        ) { vm.tier = if (vm.tier == "mine") null else "mine" }
    }
    if (vm.tier != null) {
        Spacer(Modifier.height(Dimens.space2))
        InlineNotice(
            text = "已按「${
                when (vm.tier) {
                    "system" -> "系统模板"; "department" -> "科室模板"; else -> "我的模板"
                }
            }」筛选，点击该卡可取消",
        )
    }
}

@Composable
private fun TierCard(
    title: String,
    hint: String,
    count: Int,
    start: Color,
    end: Color,
    selected: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(Dimens.radiusLg)
    Column(
        modifier.clip(shape)
            .background(if (selected) FeatureTemplateSoft else Surface)
            .border(
                1.dp,
                if (selected) start.copy(alpha = 0.35f) else LineSubtle,
                shape,
            )
            .clickable { onClick() }
            .padding(Dimens.space4),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(30.dp).clip(RoundedCornerShape(Dimens.radiusSm))
                    .background(Brush.linearGradient(listOf(start, end))),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Default.LibraryBooks, null, tint = OnPrimaryText,
                    modifier = Modifier.size(Dimens.iconSm))
            }
            Spacer(Modifier.width(Dimens.space2))
            Text(title, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold, color = Ink,
                modifier = Modifier.weight(1f))
            Text("$count", fontSize = 15.sp, fontWeight = FontWeight.Bold,
                color = if (selected) FeatureTemplateInk else Ink)
        }
        Spacer(Modifier.height(Dimens.space2))
        Text(hint, fontSize = 11.5.sp, color = Muted, lineHeight = 17.sp)
    }
}

// ---------------- 列表行 ----------------

@Composable
private fun TemplateRow(
    vm: TemplatesViewModel,
    t: JsonObject,
    onAdapt: () -> Unit,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
) {
    val tier = vm.tierOf(t)
    val selected = vm.selectedId == t["id"].str()
    val (tierFg, tierBg, tierText) = when (tier) {
        "department" -> Triple(AiIndigo, AiSoft, "科室模板")
        "mine" -> Triple(VioletInk, VioletSoft, "我的模板")
        else -> Triple(EmeraldInk, EmeraldSoft, "系统模板")
    }
    val shape = RoundedCornerShape(Dimens.radiusLg)

    Column(
        Modifier.fillMaxWidth().clip(shape)
            .background(if (selected) PrimarySoft else Surface)
            .border(1.dp, if (selected) Primary.copy(alpha = 0.4f) else LineSubtle, shape)
            .clickable { vm.select(t) }
            .padding(Dimens.space4),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(t["name"].str(), fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                    color = Ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(3.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TagChip(tierText, fg = tierFg, bg = tierBg)
                    val cat = t["category"].str()
                    if (cat.isNotBlank()) {
                        Spacer(Modifier.width(Dimens.space1))
                        TagChip(cat, fg = Ink2, bg = SurfaceTonal)
                    }
                    val base = t["base_type"].str()
                    if (base.isNotBlank()) {
                        Spacer(Modifier.width(Dimens.space1))
                        TagChip(base, fg = Muted, bg = SurfaceTonal)
                    }
                }
            }
            Spacer(Modifier.width(Dimens.space2))
            AppButton("使用", onClick = { vm.startUse(t) }, kind = AppButtonKind.PRIMARY)
        }

        val desc = t["description"].str()
        if (desc.isNotBlank()) {
            Spacer(Modifier.height(Dimens.space2))
            Text(desc, fontSize = 12.sp, color = Ink2, lineHeight = 18.sp, maxLines = 2,
                overflow = TextOverflow.Ellipsis)
        }

        Spacer(Modifier.height(Dimens.space3))
        Row(verticalAlignment = Alignment.CenterVertically) {
            MetaText("使用 ${t["use_count"].int()} 次")
            Spacer(Modifier.width(Dimens.space3))
            t["created_by_name"].str().takeIf { it.isNotBlank() }?.let {
                MetaText("创建：$it")
                Spacer(Modifier.width(Dimens.space3))
            }
            t["created_at"].str().takeIf { it.length >= 10 }?.let {
                MetaText("更新：${it.substring(0, 10)}")
            }
            Spacer(Modifier.weight(1f))
            AppButton("AI 调整", onClick = { vm.select(t); onAdapt() },
                kind = AppButtonKind.SECONDARY, icon = Icons.Default.AutoAwesome)
            if (AppState.isAdmin || tier == "mine") {
                Spacer(Modifier.width(Dimens.space1))
                AppIconButton(Icons.Default.Edit, "编辑", onClick = onEdit)
                Spacer(Modifier.width(Dimens.space1))
                AppIconButton(Icons.Default.Delete, "删除", onClick = onDelete)
            }
        }
    }
}

@Composable
private fun MetaText(text: String) {
    Text(text, fontSize = 11.sp, color = Muted)
}

// ---------------- 右侧：使用模板（内联填表 → 进入写作工作台） ----------------

@Composable
private fun UsePanel(vm: TemplatesViewModel, t: JsonObject, modifier: Modifier) {
    val fields = t["params_schema"].arr().mapNotNull { it.obj() }
    // 从写作工作台「返回模板重新填写要素」回来时，回填上次已填的要素值
    var values by remember {
        mutableStateOf(fields.associate {
            val n = it["name"].str()
            val label = it["label"].str().ifBlank { n }
            val preset = if (AppState.lastTemplateUseId == t["id"].str())
                AppState.lastTemplateUseValues[n].orEmpty() else ""
            n to (label to preset)
        })
    }
    // 必填要素未填时的拦截提示（点「生成」时校验）
    var requiredError by remember { mutableStateOf<String?>(null) }

    Column(
        modifier.fillMaxHeight()
            .clip(RoundedCornerShape(Dimens.radiusLg))
            .background(Surface)
            .border(1.dp, LineSubtle, RoundedCornerShape(Dimens.radiusLg))
            .padding(Dimens.space5)
            .verticalScroll(rememberScrollState()),
    ) {
        SectionTitle("使用模板", icon = Icons.Default.Description)
        Spacer(Modifier.height(Dimens.space2))
        Text(t["name"].str(), fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Ink)
        t["description"].str().takeIf { it.isNotBlank() }?.let {
            Spacer(Modifier.height(Dimens.space1))
            Text(it, fontSize = 12.sp, color = Ink2, lineHeight = 18.sp)
        }

        Spacer(Modifier.height(Dimens.space3))
        InlineNotice("填好要素后点「生成」，将进入智能写作工作台自动起草，可继续对话修改、保存版本与导出")

        Spacer(Modifier.height(Dimens.space3))
        if (fields.isEmpty()) {
            InlineNotice("该模板无需填写要素，可直接生成")
        } else {
            fields.forEach { f ->
                val n = f["name"].str()
                val label = f["label"].str().ifBlank { n }
                AppTextField(
                    value = values[n]?.second.orEmpty(),
                    onValueChange = { values = values + (n to (label to it)) },
                    label = label,
                    placeholder = f["placeholder"].str().ifBlank { "请填写$label" },
                )
                Spacer(Modifier.height(Dimens.space2))
            }
        }

        Spacer(Modifier.height(Dimens.space3))
        AppButton("生成，进入写作工作台", onClick = {
            // 必填要素（params_schema 中 required=true）不允许留空，否则主送机关等
            // 排版字段缺失会直接导致生成公文漏掉标题/主送，必须先在表单层强制。
            val missing = fields.filter { f ->
                f["required"].bool() &&
                values[f["name"].str()]?.second?.trim().orEmpty().isEmpty()
            }.map { f -> f["label"].str().ifBlank { f["name"].str() } }
            if (missing.isNotEmpty()) {
                requiredError = "请先填写必填要素：${missing.joinToString("、")}"
            } else {
                requiredError = null
                vm.launchWorkspace(values)
            }
        }, kind = AppButtonKind.AI, fill = true, icon = Icons.Default.AutoAwesome)
        Spacer(Modifier.height(Dimens.space2))
        AppButton("返回预览", onClick = { vm.cancelUse() },
            kind = AppButtonKind.SECONDARY, fill = true)
        requiredError?.let {
            Spacer(Modifier.height(Dimens.space2))
            FieldError(it)
        }
        vm.status?.let {
            Spacer(Modifier.height(Dimens.space2))
            FieldError(it)
        }
    }
}

// ---------------- 右侧预览 ----------------

@Composable
private fun PreviewPane(
    vm: TemplatesViewModel,
    modifier: Modifier,
    onAdapt: () -> Unit,
) {
    val t = vm.preview
    Column(
        modifier.fillMaxHeight()
            .clip(RoundedCornerShape(Dimens.radiusLg))
            .background(Surface)
            .border(1.dp, LineSubtle, RoundedCornerShape(Dimens.radiusLg))
            .padding(Dimens.space5)
            .verticalScroll(rememberScrollState()),
    ) {
        if (t == null) {
            EmptyState(
                text = "选择左侧模板查看结构",
                hint = "预览会展示模板的章节结构、要素与正文骨架，可直接用于写作",
                icon = Icons.Default.Description,
            )
            return
        }

        SectionTitle(t["name"].str(), icon = Icons.Default.Description)
        Spacer(Modifier.height(Dimens.space2))
        t["description"].str().takeIf { it.isNotBlank() }?.let {
            Text(it, fontSize = 12.5.sp, color = Ink2, lineHeight = 19.sp)
            Spacer(Modifier.height(Dimens.space3))
        }

        Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space1)) {
            TagChip(
                when (vm.tierOf(t)) {
                    "department" -> "科室模板"; "mine" -> "我的模板"; else -> "系统模板"
                },
                fg = FeatureTemplateInk, bg = FeatureTemplateSoft,
            )
            t["category"].str().takeIf { it.isNotBlank() }?.let {
                TagChip(it, fg = Ink2, bg = SurfaceTonal)
            }
            t["writing_style"].str().takeIf { it.isNotBlank() }?.let {
                TagChip(it, fg = Muted, bg = SurfaceTonal)
            }
            t["format_profile"].str().takeIf { it.isNotBlank() }?.let {
                TagChip(if (it == "GBT_RULES") "GB/T 公文格式" else it,
                    fg = EmeraldInk, bg = EmeraldSoft)
            }
            val wc = t["word_count"].int()
            if (wc > 0) TagChip("约 $wc 字", fg = Muted, bg = SurfaceTonal)
        }

        Spacer(Modifier.height(Dimens.space4))

        // 章节结构
        val structure = t["structure"].arr().mapNotNull { node ->
            val item = node.obj()
            (item?.get("name").str().ifBlank { node.str() }).takeIf { it.isNotBlank() }
        }
        if (structure.isNotEmpty()) {
            ContextBlock(title = "章节结构") {
                structure.forEachIndexed { i, s ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp),
                        verticalAlignment = Alignment.Top) {
                        Box(
                            Modifier.size(18.dp).clip(RoundedCornerShape(Dimens.radiusXs))
                                .background(FeatureTemplateSoft),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text("${i + 1}", fontSize = 10.sp, color = FeatureTemplateInk,
                                fontWeight = FontWeight.SemiBold)
                        }
                        Spacer(Modifier.width(Dimens.space2))
                        Text(s, fontSize = 12.5.sp, color = Ink, lineHeight = 19.sp)
                    }
                }
            }
            Spacer(Modifier.height(Dimens.space3))
        }

        val skeleton = t["body_skeleton"].arr().mapNotNull { node ->
            node.obj()?.get("name").str().takeIf { it.isNotBlank() }
        }
        if (skeleton.isNotEmpty()) {
            ContextBlock(title = "正文段落顺序") {
                skeleton.forEachIndexed { i, name ->
                    Text("${i + 1}. $name", fontSize = 12.5.sp, color = Ink,
                        lineHeight = 19.sp, modifier = Modifier.padding(vertical = 2.dp))
                }
            }
            Spacer(Modifier.height(Dimens.space3))
        }

        // 待填要素
        val params = t["params_schema"].arr().mapNotNull { it.obj() }
        if (params.isNotEmpty()) {
            ContextBlock(title = "待填要素（${params.size}）") {
                params.forEach { f ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
                        Text(f["label"].str().ifBlank { f["name"].str() }, fontSize = 12.sp,
                            color = Ink2, modifier = Modifier.weight(1f), maxLines = 1,
                            overflow = TextOverflow.Ellipsis)
                        Text("待填写", fontSize = 11.sp, color = Muted2)
                    }
                }
            }
            Spacer(Modifier.height(Dimens.space3))
        }

        // 正文骨架
        val content = t["content_template"].str()
        if (content.isNotBlank()) {
            SectionTitle("正文骨架")
            Spacer(Modifier.height(Dimens.space2))
            DocumentSurface(padding = Dimens.space4) {
                Text(content, fontSize = 12.5.sp, color = Ink, lineHeight = 22.sp)
            }
        } else {
            EmptyState("暂无正文骨架", hint = "该模板仅提供要素与结构，正文由助手生成",
                icon = Icons.Default.Description)
        }

        Spacer(Modifier.height(Dimens.space4))
        AppButton("使用此模板生成公文", onClick = { vm.startUse(t) },
            kind = AppButtonKind.AI, fill = true, icon = Icons.Default.AutoAwesome)
        Spacer(Modifier.height(Dimens.space2))
        AppButton("AI 调整此模板", onClick = onAdapt, kind = AppButtonKind.SECONDARY, fill = true)
    }
}

// ---------------- AI 调整模板 ----------------

@Composable
private fun AdaptDialog(vm: TemplatesViewModel, onDismiss: () -> Unit) {
    val base = vm.preview
    var hints by remember { mutableStateOf("") }
    val draft = vm.draft
    var name by remember { mutableStateOf(draft?.get("name").str()) }
    var content by remember { mutableStateOf(draft?.get("content_template").str()) }
    // 科室管理员 / 系统管理员保存为科室模板，普通用户保存为我的模板
    val asDept = vm.canSaveDeptTemplate

    LaunchedEffect(draft?.get("content_template")) {
        name = draft?.get("name").str()
        content = draft?.get("content_template").str()
    }

    AppDialog(
        onDismissRequest = onDismiss,
        title = "AI 调整模板",
        subtitle = if (asDept)
            "基于当前模板，按${AppState.departmentName.ifBlank { "本科室" }}写作习惯给出修改结果，确认后保存为科室模板"
        else "基于当前模板给出修改结果，确认后保存为我的模板（仅本人可见）",
        icon = Icons.Default.AutoAwesome,
        width = 720.dp,
        actions = {
            if (draft == null) {
                AppButton("取消", onClick = onDismiss, kind = AppButtonKind.SECONDARY)
                Spacer(Modifier.width(Dimens.space2))
                AppButton("生成调整结果", onClick = {
                    base?.let { vm.adaptForDepartment(it, hints) }
                }, kind = AppButtonKind.AI, enabled = !vm.adapting && base != null,
                    loading = vm.adapting)
            } else {
                AppButton("放弃", onClick = { vm.cancelDraft() }, kind = AppButtonKind.TEXT)
                Spacer(Modifier.width(Dimens.space2))
                AppButton(if (asDept) "保存为科室模板" else "保存为我的模板",
                    onClick = { vm.saveAdaptedTemplate(name, content) },
                    kind = AppButtonKind.PRIMARY)
            }
        },
    ) {
        InlineNotice(
            text = "当前模板：${base?.get("name").str().ifBlank { "未选择" }}",
            icon = Icons.Default.Description,
        )
        if (draft == null) {
            AppTextField(
                value = hints,
                onValueChange = { hints = it },
                label = "调整要求",
                placeholder = "例如：把报送对象改为区政府，篇幅压到 1200 字，增加存在问题与下一步措施",
                singleLine = false,
                minLines = 3,
            )
            vm.adaptError?.let { FieldError(it) }
        } else {
            AppTextField(value = name, onValueChange = { name = it }, label = "模板名称")
            AppTextField(
                value = content,
                onValueChange = { content = it },
                label = "模板正文（可继续手工调整）",
                placeholder = "AI 调整结果",
                singleLine = false,
                minLines = 10,
                maxLines = 24,
            )
            InlineNotice(
                if (asDept) "确认无误后保存；科室归属由服务端写入，不会保存到其他科室"
                else "确认无误后保存为我的模板，仅本人可见"
            )
        }
    }
}

// ---------------- 新建 / 编辑 ----------------

@Composable
private fun TemplateEditDialog(
    editing: JsonObject?,
    onDismiss: () -> Unit,
    onSubmit: (Map<String, Any?>) -> Unit,
) {
    var name by remember { mutableStateOf(editing?.get("name").str()) }
    var category by remember { mutableStateOf(editing?.get("category").str()) }
    var description by remember { mutableStateOf(editing?.get("description").str()) }
    var content by remember { mutableStateOf(editing?.get("content_template").str()) }
    var writingStyle by remember {
        mutableStateOf(editing?.get("writing_style").str().ifBlank { "正式公文" })
    }
    var wordCount by remember {
        mutableStateOf(editing?.get("word_count").int().let { if (it > 0) it.toString() else "1000" })
    }
    var structureText by remember {
        mutableStateOf(
            editing?.get("structure").arr().mapNotNull { it.obj() }.joinToString("\n") {
                val n = it["name"].str()
                val g = it["guide"].str()
                if (g.isBlank()) n else "$n｜$g"
            }
        )
    }
    var needRedHeader by remember { mutableStateOf(editing?.get("need_red_header")?.toString() == "true") }
    var needSignature by remember { mutableStateOf(editing == null || editing["need_signature"]?.toString() != "false") }
    var needDate by remember { mutableStateOf(editing == null || editing["need_date"]?.toString() != "false") }
    var needDocNumber by remember { mutableStateOf(editing?.get("need_doc_number")?.toString() == "true") }

    AppDialog(
        onDismissRequest = onDismiss,
        title = if (editing == null) "新建模板" else "编辑模板",
        subtitle = "保存后按归属进入系统 / 科室 / 我的模板",
        icon = Icons.Default.Edit,
        actions = {
            AppButton("取消", onClick = onDismiss, kind = AppButtonKind.SECONDARY)
            Spacer(Modifier.width(Dimens.space2))
            AppButton("保存", onClick = {
                onSubmit(
                    mapOf(
                        "name" to name,
                        "category" to category,
                        "description" to description,
                        "content_template" to content,
                        "writing_style" to writingStyle,
                        "word_count" to (wordCount.toIntOrNull() ?: 1000),
                        "structure" to structureText.lines().mapNotNull { raw ->
                            val line = raw.trim()
                            if (line.isBlank()) null else {
                                val parts = line.split("｜", limit = 2)
                                mapOf("name" to parts[0].trim(), "guide" to parts.getOrElse(1) { "" }.trim())
                            }
                        },
                        "need_red_header" to needRedHeader,
                        "need_signature" to needSignature,
                        "need_date" to needDate,
                        "need_doc_number" to needDocNumber,
                    )
                )
            }, kind = AppButtonKind.PRIMARY, enabled = name.isNotBlank())
        },
    ) {
        SectionTitle("第 1 步 · 基本信息")
        AppTextField(value = name, onValueChange = { name = it }, label = "模板名称",
            placeholder = "例如：行政复议工作情况报告")
        AppTextField(value = category, onValueChange = { category = it }, label = "类型",
            placeholder = "例如：报告")
        AppTextField(value = description, onValueChange = { description = it },
            label = "简短说明", singleLine = false, minLines = 2)

        Spacer(Modifier.height(Dimens.space2))
        SectionTitle("第 2 步 · 初始格式设计")
        Text("先确定文种结构与成文格式，再保存正文骨架；后续 AI 起草按这些约束生成。",
            fontSize = 11.5.sp, color = Muted, lineHeight = 17.sp)
        AppTextField(value = writingStyle, onValueChange = { writingStyle = it },
            label = "写作风格", placeholder = "例如：正式公文")
        AppTextField(value = wordCount, onValueChange = { wordCount = it.filter(Char::isDigit).take(6) },
            label = "建议字数", placeholder = "例如：1000")
        AppTextField(
            value = structureText,
            onValueChange = { structureText = it },
            label = "章节结构",
            placeholder = "每行一项：一、总体情况｜概述工作背景和总体成效",
            singleLine = false,
            minLines = 4,
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(needRedHeader, { needRedHeader = it }); Text("红头")
            Spacer(Modifier.width(Dimens.space2))
            Checkbox(needDocNumber, { needDocNumber = it }); Text("发文字号")
            Spacer(Modifier.width(Dimens.space2))
            Checkbox(needSignature, { needSignature = it }); Text("落款")
            Spacer(Modifier.width(Dimens.space2))
            Checkbox(needDate, { needDate = it }); Text("日期")
        }
        AppTextField(value = content, onValueChange = { content = it }, label = "正文骨架",
            placeholder = "可用占位符，如 {{时间范围}}", singleLine = false, minLines = 8)
    }
}
