package com.judicialai.desktop.features.department

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
import androidx.compose.material.icons.filled.Badge
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.LibraryBooks
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Task
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.design.components.AppButton
import com.judicialai.desktop.design.components.AppButtonKind
import com.judicialai.desktop.design.components.AppDialog
import com.judicialai.desktop.design.components.AppLinkButton
import com.judicialai.desktop.design.components.AppTextField
import com.judicialai.desktop.design.components.ContextBlock
import com.judicialai.desktop.design.components.EmptyLine
import com.judicialai.desktop.design.components.Eyebrow
import com.judicialai.desktop.design.components.FieldError
import com.judicialai.desktop.design.components.Hairline
import com.judicialai.desktop.design.components.InlineNotice
import com.judicialai.desktop.design.components.LoadingBlock
import com.judicialai.desktop.design.components.PageHeader
import com.judicialai.desktop.design.components.SectionTitle
import com.judicialai.desktop.design.components.TagChip
import com.judicialai.desktop.design.theme.AiIndigo
import com.judicialai.desktop.design.theme.AiSoft
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.BrandEnd
import com.judicialai.desktop.design.theme.BrandStart
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.EmeraldInk
import com.judicialai.desktop.design.theme.EmeraldSoft
import com.judicialai.desktop.design.theme.FeatureCheckInk
import com.judicialai.desktop.design.theme.FeatureCheckSoft
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.LineSubtle
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Muted2
import com.judicialai.desktop.design.theme.OnDarkMuted
import com.judicialai.desktop.design.theme.OnPrimaryText
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.PrimarySoft
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.SurfaceTonal

/**
 * 科室空间（v4.0）
 *
 * 普通用户进入即本科室：身份 → 智能助手 → 常用业务 → 知识资源 → 科室模板 → 工作流程。
 * 不复制 HOME 的四大功能，也不让用户选择其他科室。
 * 科室管理员在此基础上多一个「维护智能助手」入口（仅业务层）。
 */
@Composable
fun DepartmentScreen() {
    val vm = remember { DepartmentViewModel() }

    if (vm.loading) {
        LoadingBlock("正在载入本科室空间…")
        return
    }
    vm.error?.let {
        Box(Modifier.fillMaxSize().background(AppBg).padding(Dimens.space6)) { FieldError(it) }
        return
    }

    Box(Modifier.fillMaxSize().background(AppBg)) {
        Column(
            Modifier.fillMaxSize()
                .padding(horizontal = Dimens.space6, vertical = Dimens.space5)
                .verticalScroll(rememberScrollState()),
        ) {
            PageHeader(
                title = vm.deptName.ifBlank { "本科室空间" },
                subtitle = "常用业务、知识资源、科室模板与工作流程",
                eyebrow = "科室空间",
                actions = {
                    if (vm.agent?.canManage == true) {
                        AppButton("维护智能助手配置", onClick = { vm.openMaintain() },
                            kind = AppButtonKind.PRIMARY, icon = Icons.Default.Settings)
                    }
                },
            )

            IdentityStrip(vm)

            Spacer(Modifier.height(Dimens.space5))

            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Dimens.space4),
            ) {
                AgentCard(vm, Modifier.weight(1.15f))
                BusinessCard(vm, Modifier.weight(1f))
            }

            Spacer(Modifier.height(Dimens.space4))

            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Dimens.space4),
            ) {
                KnowledgeCard(vm, Modifier.weight(1f))
                TemplateCard(vm, Modifier.weight(1f))
            }

            // 工作流程：放在科室空间最下面，展示本科室工作流程列表，点进去进入工作流程平台
            Spacer(Modifier.height(Dimens.space4))
            WorkflowCard(vm)

            vm.status?.let {
                Spacer(Modifier.height(Dimens.space4))
                InlineNotice(it)
            }
            Spacer(Modifier.height(Dimens.space6))
        }
    }

    if (vm.maintaining) MaintainDialog(vm)
}

// ---------------- 本科室身份 ----------------

@Composable
private fun IdentityStrip(vm: DepartmentViewModel) {
    val shape = RoundedCornerShape(Dimens.radiusXl)
    val canManage = vm.agent?.canManage == true
    Box(
        Modifier.fillMaxWidth().clip(shape)
            .background(Brush.horizontalGradient(listOf(BrandStart, BrandEnd))),
    ) {
        Row(
            Modifier.fillMaxWidth().padding(Dimens.space6),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier.size(52.dp).clip(RoundedCornerShape(Dimens.radiusLg))
                    .background(OnPrimaryText.copy(alpha = 0.14f)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Default.Badge, null, tint = OnPrimaryText,
                    modifier = Modifier.size(Dimens.iconLg))
            }
            Spacer(Modifier.width(Dimens.space4))
            Column(Modifier.weight(1f)) {
                Text(vm.deptName.ifBlank { "本科室" }, fontSize = 19.sp,
                    fontWeight = FontWeight.SemiBold, color = OnPrimaryText)
                Spacer(Modifier.height(4.dp))
                Text(
                    buildString {
                        append("已绑定智能助手")
                        vm.agent?.name?.takeIf { it.isNotBlank() }?.let { append("：$it") }
                        val v = vm.agent?.version ?: 0
                        if (v > 0) append(" · 配置版本 v$v")
                    },
                    fontSize = 12.5.sp, color = OnDarkMuted, lineHeight = 18.sp,
                )
            }
            Spacer(Modifier.width(Dimens.space4))
            Box(
                Modifier.clip(RoundedCornerShape(Dimens.radiusPill))
                    .background(OnPrimaryText.copy(alpha = 0.16f))
                    .padding(horizontal = 12.dp, vertical = 6.dp),
            ) {
                Text(if (canManage) "科室管理员" else "本科室成员", fontSize = 12.sp,
                    color = OnPrimaryText)
            }
        }
    }
}

// ---------------- 智能助手 ----------------

@Composable
private fun AgentCard(vm: DepartmentViewModel, modifier: Modifier) {
    val a = vm.agent
    Column(
        modifier.fillMaxHeight()
            .clip(RoundedCornerShape(Dimens.radiusLg))
            .background(Surface)
            .border(1.dp, LineSubtle, RoundedCornerShape(Dimens.radiusLg))
            .padding(Dimens.space5),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(34.dp).clip(RoundedCornerShape(Dimens.radiusMd))
                    .background(Brush.linearGradient(listOf(AiIndigo, Primary))),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Default.AutoAwesome, null, tint = OnPrimaryText,
                    modifier = Modifier.size(Dimens.iconMd))
            }
            Spacer(Modifier.width(Dimens.space3))
            Column(Modifier.weight(1f)) {
                Text("智能助手", fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold,
                    color = Ink)
                Text(a?.name.orEmpty().ifBlank { "智能助手" }, fontSize = 11.5.sp,
                    color = Muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }

        Spacer(Modifier.height(Dimens.space4))
        a?.intro?.takeIf { it.isNotBlank() }?.let {
            Text(it, fontSize = 12.5.sp, color = Ink2, lineHeight = 20.sp)
            Spacer(Modifier.height(Dimens.space3))
        }
        a?.manager?.takeIf { it.isNotBlank() }?.let {
            Row(verticalAlignment = Alignment.CenterVertically) {
                TagChip("维护人", fg = Primary, bg = PrimarySoft)
                Spacer(Modifier.width(Dimens.space2))
                Text(it, fontSize = 12.sp, color = Ink2)
            }
            Spacer(Modifier.height(Dimens.space3))
        }

        Hairline()
        Spacer(Modifier.height(Dimens.space3))
        SectionTitle("推荐任务", icon = Icons.Default.Task)
        Spacer(Modifier.height(Dimens.space2))
        val tasks = a?.recommendedTasks.orEmpty()
        if (tasks.isEmpty()) {
            EmptyLine("暂未配置推荐任务")
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(Dimens.space2)) {
                tasks.forEach { t ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clip(RoundedCornerShape(Dimens.radiusMd))
                            .background(AiSoft)
                            .clickable {
                                AppState.pendingWritingIntent = t
                                AppState.navigate(AppScreen.WRITING)
                            }
                            .padding(horizontal = 12.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(Modifier.size(5.dp)
                            .clip(RoundedCornerShape(Dimens.radiusPill))
                            .background(AiIndigo))
                        Spacer(Modifier.width(Dimens.space2))
                        Text(t, fontSize = 12.5.sp, color = Ink, modifier = Modifier.weight(1f),
                            maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text("开始 →", fontSize = 11.5.sp, color = AiIndigo)
                    }
                }
            }
        }
    }
}

// ---------------- 常用业务 / 知识 / 模板 / 工作流程 ----------------

@Composable
private fun BusinessCard(vm: DepartmentViewModel, modifier: Modifier) {
    PanelCard(modifier, title = "常用业务", icon = Icons.Default.Task) {
        if (vm.business.isEmpty()) {
            EmptyLine("本科室暂未配置常用业务")
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(Dimens.space2)) {
                vm.business.forEach { b ->
                    Column(
                        Modifier.fillMaxWidth()
                            .clip(RoundedCornerShape(Dimens.radiusMd))
                            .background(SurfaceTonal)
                            .padding(horizontal = 12.dp, vertical = 10.dp),
                    ) {
                        Text(b.title, fontSize = 12.5.sp, color = Ink,
                            fontWeight = FontWeight.Medium, maxLines = 1,
                            overflow = TextOverflow.Ellipsis)
                        if (b.hint.isNotBlank()) {
                            Spacer(Modifier.height(2.dp))
                            Text(b.hint, fontSize = 11.5.sp, color = Muted, lineHeight = 17.sp)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun KnowledgeCard(vm: DepartmentViewModel, modifier: Modifier) {
    PanelCard(modifier, title = "知识资源", icon = Icons.Default.LibraryBooks,
        tint = EmeraldInk) {
        AppButton(
            "知识库问答",
            onClick = { AppState.navigate(AppScreen.KNOWLEDGE_QA) },
            kind = AppButtonKind.AI,
            fill = true,
        )
        Text(
            "自动检索公共知识库 + 本科室知识库 + 本人知识库；答案附可点击引用。",
            fontSize = 11.5.sp,
            color = Muted,
            lineHeight = 17.sp,
        )
        Spacer(Modifier.height(Dimens.space2))
        AppButton(
            "知识库问答",
            onClick = { AppState.navigate(AppScreen.KNOWLEDGE_QA) },
            kind = AppButtonKind.PRIMARY,
            fill = true,
        )
        Spacer(Modifier.height(Dimens.space2))
        Text("回答范围自动限定为公共库 + 本科室库 + 本人库，答案附可追溯引用。",
            fontSize = 11.5.sp, color = Muted, lineHeight = 17.sp)
        Spacer(Modifier.height(Dimens.space3))
        if (vm.knowledge.isEmpty()) {
            EmptyLine("本科室暂无可用知识资源")
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(Dimens.space2)) {
                vm.knowledge.forEach { k ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clip(RoundedCornerShape(Dimens.radiusMd))
                            .background(EmeraldSoft)
                            .clickable { AppState.navigate(AppScreen.KNOWLEDGE) }
                            .padding(horizontal = 12.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(k.name, fontSize = 12.5.sp, color = Ink,
                                fontWeight = FontWeight.Medium, maxLines = 1,
                                overflow = TextOverflow.Ellipsis)
                            if (k.description.isNotBlank()) {
                                Text(k.description, fontSize = 11.5.sp, color = Muted,
                                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                        }
                        Spacer(Modifier.width(Dimens.space2))
                        TagChip("${k.docCount} 篇 · 查看 →", fg = EmeraldInk, bg = Surface)
                    }
                }
            }
        }
    }
}

@Composable
private fun TemplateCard(vm: DepartmentViewModel, modifier: Modifier) {
    PanelCard(modifier, title = "科室模板", icon = Icons.Default.Description,
        tint = FeatureCheckInk) {
        if (vm.templates.isEmpty()) {
            EmptyLine("本科室暂无专属模板，可在模板中心用 AI 调整生成")
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(Dimens.space2)) {
                vm.templates.forEach { t ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clip(RoundedCornerShape(Dimens.radiusMd))
                            .background(FeatureCheckSoft)
                            .clickable { AppState.navigate(AppScreen.TEMPLATES) }
                            .padding(horizontal = 12.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(t.name, fontSize = 12.5.sp, color = Ink,
                                fontWeight = FontWeight.Medium, maxLines = 1,
                                overflow = TextOverflow.Ellipsis)
                            if (t.category.isNotBlank()) {
                                Text(t.category, fontSize = 11.sp, color = Muted)
                            }
                        }
                        Text("去使用 →", fontSize = 11.5.sp, color = FeatureCheckInk)
                    }
                }
            }
        }
    }
}

/**
 * 本科室工作流程：科室空间最底部的通栏卡片。
 * 展示本科室可用工作流程列表；点击任意流程或底部入口进入工作流程平台。
 * 不用 PanelCard（其内部 fillMaxHeight 不适配滚动列里的通栏卡片）。
 */
@Composable
private fun WorkflowCard(vm: DepartmentViewModel) {
    Column(
        Modifier.fillMaxWidth()
            .clip(RoundedCornerShape(Dimens.radiusLg))
            .background(Surface)
            .border(1.dp, LineSubtle, RoundedCornerShape(Dimens.radiusLg))
            .padding(Dimens.space5),
    ) {
        SectionTitle("工作流程", icon = Icons.Default.Share)
        Spacer(Modifier.height(Dimens.space3))
        if (vm.workflows.isEmpty()) {
            EmptyLine("暂无工作流程，可进入工作流程平台创建")
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(Dimens.space2)) {
                vm.workflows.forEach { w ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clip(RoundedCornerShape(Dimens.radiusMd))
                            .background(SurfaceTonal)
                            .clickable { AppState.navigate(AppScreen.WORKFLOW) }
                            .padding(horizontal = 12.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(w.name, fontSize = 12.5.sp, color = Ink,
                                fontWeight = FontWeight.Medium, maxLines = 1,
                                overflow = TextOverflow.Ellipsis)
                            if (w.description.isNotBlank()) {
                                Text(w.description, fontSize = 11.5.sp, color = Muted,
                                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                        }
                        if (w.nodeCount > 0) {
                            TagChip("${w.nodeCount} 个节点", fg = Primary, bg = PrimarySoft)
                            Spacer(Modifier.width(Dimens.space2))
                        }
                        Text("进入 →", fontSize = 11.5.sp, color = Primary)
                    }
                }
            }
        }
        Spacer(Modifier.height(Dimens.space3))
        AppLinkButton("进入工作流程平台 →",
            onClick = { AppState.navigate(AppScreen.WORKFLOW) })
    }
}

@Composable
private fun PanelCard(
    modifier: Modifier,
    title: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    tint: Color = Primary,
    content: @Composable () -> Unit,
) {
    Column(
        modifier.fillMaxHeight()
            .clip(RoundedCornerShape(Dimens.radiusLg))
            .background(Surface)
            .border(1.dp, LineSubtle, RoundedCornerShape(Dimens.radiusLg))
            .padding(Dimens.space5),
    ) {
        SectionTitle(title, icon = icon, tint = tint)
        Spacer(Modifier.height(Dimens.space3))
        content()
    }
}

// ---------------- 维护面板（科室管理员）----------------

/** 勾选项：value 为提交值，label 为展示文案。注意：不可嵌套滚动（对话框内容区已自带滚动）。 */
@Composable
private fun MultiSelectField(
    label: String,
    options: List<Pair<String, String>>,
    selected: Set<String>,
    onToggle: (String) -> Unit,
) {
    Column(Modifier.fillMaxWidth()) {
        Text(label, fontSize = 12.5.sp, color = Ink2, fontWeight = FontWeight.Medium)
        Spacer(Modifier.height(Dimens.space2))
        if (options.isEmpty()) {
            EmptyLine("暂无可选项")
        } else {
            Column(
                Modifier.fillMaxWidth()
                    .clip(RoundedCornerShape(Dimens.radiusMd))
                    .border(1.dp, LineSubtle, RoundedCornerShape(Dimens.radiusMd))
                    .background(Surface)
                    .padding(vertical = Dimens.space1),
            ) {
                options.forEach { (value, text) ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clickable { onToggle(value) }
                            .padding(horizontal = 12.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Checkbox(checked = value in selected, onCheckedChange = null)
                        Spacer(Modifier.width(Dimens.space2))
                        Text(text, fontSize = 12.5.sp, color = Ink,
                            maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
    }
}

@Composable
private fun MaintainDialog(vm: DepartmentViewModel) {
    val editable = vm.agent?.editableFields.orEmpty()
    AppDialog(
        onDismissRequest = { vm.closeMaintain() },
        title = "维护智能助手",
        subtitle = "仅可维护本科室业务配置；系统基础与安全权限由平台统一控制",
        icon = Icons.Default.Settings,
        width = 760.dp,
        actions = {
            AppButton("关闭", onClick = { vm.closeMaintain() }, kind = AppButtonKind.SECONDARY)
            Spacer(Modifier.width(Dimens.space2))
            AppButton("保存并生效", onClick = { vm.save() }, kind = AppButtonKind.PRIMARY,
                enabled = !vm.saving, loading = vm.saving)
        },
    ) {
        InlineNotice("保存后将生成新的配置版本，本科室所有成员立即按新配置使用")
        AppTextField(value = vm.formManager, onValueChange = { vm.formManager = it },
            label = "维护人")
        AppTextField(value = vm.formIntro, onValueChange = { vm.formIntro = it },
            label = "助手简介", singleLine = false, minLines = 2)

        if (editable.isEmpty() || editable.contains("business_prompt")) {
            AppTextField(value = vm.formBusinessPrompt,
                onValueChange = { vm.formBusinessPrompt = it },
                label = "本科室业务要求（业务层）",
                placeholder = "例如：本室负责行政复议与应诉，报告须包含案件办理数据与问题分析",
                singleLine = false, minLines = 4)
        }
        if (editable.isEmpty() || editable.contains("work_requirements")) {
            AppTextField(value = vm.formRequirements,
                onValueChange = { vm.formRequirements = it },
                label = "工作要求", singleLine = false, minLines = 3)
        }
        if (editable.isEmpty() || editable.contains("tasks")) {
            // 可选项 = 常用业务标题 + 当前已选（兼容历史值，便于取消勾选）
            val options = (vm.business.map { it.title to it.title } +
                vm.formTasksSel.map { it to it }).distinctBy { it.first }
            MultiSelectField(label = "推荐任务（勾选）", options = options,
                selected = vm.formTasksSel, onToggle = { vm.toggleTask(it) })
        }
        if (editable.isEmpty() || editable.contains("templates")) {
            val options = (vm.templates.map { it.name to it.name } +
                vm.formTemplatesSel.map { it to it }).distinctBy { it.first }
            MultiSelectField(label = "关联模板（勾选）", options = options,
                selected = vm.formTemplatesSel, onToggle = { vm.toggleTemplate(it) })
        }
        if (editable.isEmpty() || editable.contains("kb_ids")) {
            val options = (vm.knowledge.map { it.id to "${it.name}（${it.docCount} 篇）" } +
                vm.formKbIdsSel.map { it to it }).distinctBy { it.first }
            MultiSelectField(label = "关联知识资源（勾选）", options = options,
                selected = vm.formKbIdsSel, onToggle = { vm.toggleKb(it) })
        }

        vm.status?.let { FieldError(it) }

        if (vm.versions.isNotEmpty()) {
            Spacer(Modifier.height(Dimens.space2))
            SectionTitle("配置版本记录")
            Spacer(Modifier.height(Dimens.space2))
            Column(
                Modifier.fillMaxWidth()
                    .clip(RoundedCornerShape(Dimens.radiusMd))
                    .background(SurfaceTonal)
                    .padding(Dimens.space4),
                verticalArrangement = Arrangement.spacedBy(Dimens.space2),
            ) {
                vm.versions.take(8).forEach { v ->
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
                        Text("v${v.version}", fontSize = 12.sp, color = Primary,
                            fontWeight = FontWeight.SemiBold,
                            modifier = Modifier.width(38.dp))
                        Column(Modifier.weight(1f)) {
                            Text(v.note.ifBlank { "更新业务配置" }, fontSize = 12.sp,
                                color = Ink)
                            Text("${v.operator.ifBlank { "系统" }} · ${v.createdAt}",
                                fontSize = 11.sp, color = Muted)
                        }
                    }
                }
            }
        }
    }
}
