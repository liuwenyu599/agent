package com.judicialai.desktop.features.department

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Button
import androidx.compose.material.Icon
import androidx.compose.material.OutlinedButton
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.material.TextFieldDefaults
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.LibraryBooks
import androidx.compose.material.icons.filled.Star
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.design.components.EmptyState
import com.judicialai.desktop.design.components.Hairline
import com.judicialai.desktop.design.components.LoadingBlock
import com.judicialai.desktop.design.components.PageHeader
import com.judicialai.desktop.design.components.SectionTitle
import com.judicialai.desktop.design.components.SoftPanel
import com.judicialai.desktop.design.components.StatusChip
import com.judicialai.desktop.design.components.SurfaceCard
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.FeatureTemplateSoft
import com.judicialai.desktop.design.theme.FeatureWriteInk
import com.judicialai.desktop.design.theme.FeatureWriteSoft
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Navy
import com.judicialai.desktop.design.theme.Ok
import com.judicialai.desktop.design.theme.OkSoft
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.Surface

/**
 * 科室空间（v3.2）：本科室的「资源空间」，不是 Agent 选择器。
 *
 * 进入即按所属科室自动绑定本科室智能助手，页面只聚合四块内容：
 * 本科室智能助手 / 常用业务 / 知识资源 / 本科室模板。
 * 知识管理员可在此维护本科室助手的「业务层」配置，并查看变更版本。
 * 界面不出现模型、检索范围、系统提示等技术概念。
 */
@Composable
fun DepartmentScreen(vm: DepartmentViewModel = remember { DepartmentViewModel() }) {
    Column(
        Modifier.fillMaxWidth().background(AppBg).verticalScroll(rememberScrollState())
            .padding(Dimens.space6),
    ) {
        if (vm.maintaining && vm.agent?.canManage == true) {
            MaintainPanel(vm)
            return@Column
        }

        PageHeader(
            title = "科室空间",
            subtitle = "${vm.deptName.ifBlank { "本科室" }} · 助手、常用业务、知识资源与模板",
            actions = {
                if (vm.agent?.canManage == true) {
                    OutlinedButton(onClick = { vm.openMaintain() }) {
                        Icon(Icons.Default.Edit, null, tint = Primary,
                            modifier = Modifier.size(Dimens.iconSm))
                        Spacer(Modifier.width(Dimens.space1))
                        Text("维护本科室助手", fontSize = 12.5.sp, color = Primary)
                    }
                }
            },
        )

        if (vm.loading && vm.agent == null) {
            LoadingBlock("加载本科室资源…")
            return@Column
        }
        vm.error?.let {
            EmptyState("科室空间暂不可用：$it")
            return@Column
        }
        if (vm.deptCode.isBlank()) {
            EmptyState("当前账号未归属科室",
                hint = "请联系系统管理员在「用户与组织」中设置所属科室")
            return@Column
        }

        AgentPanel(vm)
        Spacer(Modifier.height(Dimens.space5))
        BusinessPanel(vm)
        Spacer(Modifier.height(Dimens.space5))
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(Dimens.space5),
        ) {
            Column(Modifier.weight(1f)) { KnowledgePanel(vm) }
            Column(Modifier.weight(1f)) { TemplatePanel(vm) }
        }
        Spacer(Modifier.height(Dimens.space5))
    }
}

// ---------------- 本科室智能助手 ----------------

@Composable
private fun AgentPanel(vm: DepartmentViewModel) {
    val agent = vm.agent
    SurfaceCard {
        Column(Modifier.padding(Dimens.space5)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier.size(44.dp).clip(CircleShape).background(Navy),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(Icons.Default.AutoAwesome, null, tint = Surface,
                        modifier = Modifier.size(Dimens.iconLg))
                }
                Spacer(Modifier.width(Dimens.space3))
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(agent?.name ?: "${vm.deptName}智能助手", fontSize = 16.sp,
                            fontWeight = FontWeight.SemiBold, color = Ink)
                        Spacer(Modifier.width(Dimens.space2))
                        StatusChip(
                            text = if (agent == null) "未配置" else "已启用",
                            fg = if (agent == null) Muted else Ok,
                            bg = if (agent == null) AppBg else OkSoft,
                        )
                        if (agent != null && agent.version > 0) {
                            Spacer(Modifier.width(Dimens.space2))
                            StatusChip(text = "v${agent.version}", fg = Ink2, bg = AppBg)
                        }
                    }
                    Spacer(Modifier.height(Dimens.space1))
                    Text("${vm.deptName} · 已按所属科室自动绑定", fontSize = 12.sp, color = Muted)
                }
            }

            if (!agent?.intro.isNullOrBlank()) {
                Spacer(Modifier.height(Dimens.space3))
                Text(agent!!.intro, fontSize = 13.sp, color = Ink2, lineHeight = 21.sp)
            }

            if (!agent?.recommendedTasks.isNullOrEmpty()) {
                Spacer(Modifier.height(Dimens.space4))
                SectionTitle(title = "本科室常用任务")
                Spacer(Modifier.height(Dimens.space2))
                Column(verticalArrangement = Arrangement.spacedBy(Dimens.space1)) {
                    agent!!.recommendedTasks.forEach { task ->
                        Row(
                            Modifier.fillMaxWidth()
                                .clip(RoundedCornerShape(Dimens.radiusSm))
                                .clickable {
                                    AppState.pendingWritingIntent = task
                                    AppState.navigate(AppScreen.WRITING)
                                }
                                .padding(horizontal = Dimens.space2,
                                    vertical = Dimens.space2),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Box(
                                Modifier.size(6.dp).clip(CircleShape).background(FeatureWriteInk),
                            )
                            Spacer(Modifier.width(Dimens.space2))
                            Text(task, fontSize = 13.sp, color = Ink,
                                modifier = Modifier.weight(1f), maxLines = 1,
                                overflow = TextOverflow.Ellipsis)
                            Text("开始 →", fontSize = 11.5.sp, color = Muted)
                        }
                    }
                }
            }

            if (!agent?.manager.isNullOrBlank()) {
                Spacer(Modifier.height(Dimens.space3))
                Hairline()
                Spacer(Modifier.height(Dimens.space2))
                Text("本科室维护人：${agent!!.manager}", fontSize = 12.sp, color = Muted)
            }
        }
    }
}

// ---------------- 常用业务 ----------------

@Composable
private fun BusinessPanel(vm: DepartmentViewModel) {
    SurfaceCard {
        Column(Modifier.padding(Dimens.space5)) {
            SectionTitle(title = "常用业务",
                more = if (vm.business.isEmpty()) null else "进入智能写作",
                onMore = if (vm.business.isEmpty()) null else {
                    { AppState.navigate(AppScreen.WRITING) }
                })
            Spacer(Modifier.height(Dimens.space3))
            if (vm.business.isEmpty()) {
                Text("本科室助手尚未配置常用业务。可由本科室知识管理员在「维护本科室助手」中添加。",
                    fontSize = 12.5.sp, color = Muted)
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(Dimens.space2)) {
                    vm.business.chunked(2).forEach { row ->
                        Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space2)) {
                            row.forEach { item ->
                                Box(
                                    Modifier.weight(1f)
                                        .clip(RoundedCornerShape(Dimens.radiusMd))
                                        .background(FeatureWriteSoft)
                                        .clickable {
                                            AppState.pendingWritingIntent = item.title
                                            AppState.navigate(AppScreen.WRITING)
                                        }
                                        .padding(Dimens.space4),
                                ) {
                                    Column {
                                        Text(item.title, fontSize = 13.5.sp,
                                            fontWeight = FontWeight.Medium,
                                            color = FeatureWriteInk, maxLines = 2,
                                            overflow = TextOverflow.Ellipsis)
                                        if (item.hint.isNotBlank()) {
                                            Spacer(Modifier.height(Dimens.space1))
                                            Text(item.hint, fontSize = 11.5.sp, color = Ink2,
                                                maxLines = 2, overflow = TextOverflow.Ellipsis)
                                        }
                                    }
                                }
                            }
                            if (row.size == 1) Spacer(Modifier.weight(1f))
                        }
                    }
                }
            }
        }
    }
}

// ---------------- 知识资源 ----------------

@Composable
private fun KnowledgePanel(vm: DepartmentViewModel) {
    SurfaceCard {
        Column(Modifier.padding(Dimens.space5)) {
            SectionTitle(title = "知识资源",
                more = "进入知识库",
                onMore = { AppState.navigate(AppScreen.KNOWLEDGE) })
            Spacer(Modifier.height(Dimens.space3))
            if (vm.knowledge.isEmpty()) {
                Text("本科室暂无知识库。可由本科室知识管理员在知识库中创建。",
                    fontSize = 12.5.sp, color = Muted)
            } else {
                vm.knowledge.forEach { k ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clip(RoundedCornerShape(Dimens.radiusSm))
                            .clickable { AppState.navigate(AppScreen.KNOWLEDGE) }
                            .padding(vertical = Dimens.space2),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            Modifier.size(32.dp).clip(RoundedCornerShape(Dimens.radiusSm))
                                .background(AppBg),
                            contentAlignment = Alignment.Center,
                        ) {
                            Icon(Icons.Default.LibraryBooks, null, tint = Ink2,
                                modifier = Modifier.size(Dimens.iconMd))
                        }
                        Spacer(Modifier.width(Dimens.space3))
                        Column(Modifier.weight(1f)) {
                            Text(k.name, fontSize = 13.sp, color = Ink, maxLines = 1,
                                overflow = TextOverflow.Ellipsis)
                            Text("${k.docCount} 份资料", fontSize = 11.5.sp, color = Muted)
                        }
                    }
                    Hairline()
                }
            }
        }
    }
}

// ---------------- 本科室模板 ----------------

@Composable
private fun TemplatePanel(vm: DepartmentViewModel) {
    SurfaceCard {
        Column(Modifier.padding(Dimens.space5)) {
            SectionTitle(title = "本科室模板",
                more = "进入模板中心",
                onMore = { AppState.navigate(AppScreen.TEMPLATES) })
            Spacer(Modifier.height(Dimens.space3))
            if (vm.templates.isEmpty()) {
                Text("本科室暂无专属模板。可在模板中心把系统模板调整为本科室版本。",
                    fontSize = 12.5.sp, color = Muted)
            } else {
                vm.templates.forEach { t ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clip(RoundedCornerShape(Dimens.radiusSm))
                            .clickable { AppState.navigate(AppScreen.TEMPLATES) }
                            .padding(vertical = Dimens.space2),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            Modifier.size(32.dp).clip(RoundedCornerShape(Dimens.radiusSm))
                                .background(FeatureTemplateSoft),
                            contentAlignment = Alignment.Center,
                        ) {
                            Icon(Icons.Default.Star, null, tint = Ink2,
                                modifier = Modifier.size(Dimens.iconMd))
                        }
                        Spacer(Modifier.width(Dimens.space3))
                        Column(Modifier.weight(1f)) {
                            Text(t.name, fontSize = 13.sp, color = Ink, maxLines = 1,
                                overflow = TextOverflow.Ellipsis)
                            Text(t.category.ifBlank { "科室模板" }, fontSize = 11.5.sp,
                                color = Muted)
                        }
                    }
                    Hairline()
                }
            }
        }
    }
}

// ---------------- 本科室助手维护（知识管理员） ----------------

@Composable
private fun MaintainPanel(vm: DepartmentViewModel) {
    Column {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { vm.closeMaintain() }) {
                Icon(Icons.Default.ArrowBack, null, tint = Primary,
                    modifier = Modifier.size(Dimens.iconSm))
                Spacer(Modifier.width(Dimens.space1))
                Text("返回科室空间", color = Primary, fontSize = 13.sp)
            }
            Spacer(Modifier.weight(1f))
            Text("本科室助手 · 业务配置", fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold, color = Ink)
        }
        Spacer(Modifier.height(Dimens.space2))
        Text("只维护本科室的业务口径与工作要求；系统级安全与权限约束由系统统一控制，不可修改。",
            fontSize = 12.5.sp, color = Muted)
        Spacer(Modifier.height(Dimens.space4))

        SurfaceCard {
            Column(Modifier.padding(Dimens.space5)) {
                MaintainField("助手简介", vm.formIntro, { vm.formIntro = it },
                    "一句话说明本科室助手负责哪些工作")
                MaintainField("维护人", vm.formManager, { vm.formManager = it },
                    "本科室负责维护该助手的人员")
                MaintainField("业务口径", vm.formBusinessPrompt, { vm.formBusinessPrompt = it },
                    "本科室职责、常用文种、表述习惯与业务边界", singleLine = false)
                MaintainField("工作要求", vm.formRequirements, { vm.formRequirements = it },
                    "成稿必须满足的规范与质量口径", singleLine = false)
                MaintainField("推荐任务", vm.formTasks, { vm.formTasks = it },
                    "每行一条，作为本科室常用业务与智能写作推荐目标", singleLine = false)
                MaintainField("关联模板", vm.formTemplates, { vm.formTemplates = it },
                    "每行一个模板名称，优先用于本科室写作", singleLine = false)
                MaintainField("关联知识", vm.formKbIds, { vm.formKbIds = it },
                    "每行一个知识库标识；检索范围仍由后端按科室权限强制", singleLine = false)

                Spacer(Modifier.height(Dimens.space3))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Button(onClick = { vm.save() }, enabled = !vm.saving) {
                        Text(if (vm.saving) "保存中…" else "保存并生效", fontSize = 13.sp)
                    }
                    Spacer(Modifier.width(Dimens.space3))
                    vm.status?.let {
                        Text(it, fontSize = 12.5.sp, color = Ok)
                    }
                }
            }
        }

        Spacer(Modifier.height(Dimens.space5))
        SurfaceCard {
            Column(Modifier.padding(Dimens.space5)) {
                SectionTitle(title = "变更版本记录")
                Spacer(Modifier.height(Dimens.space3))
                if (vm.versions.isEmpty()) {
                    Text("暂无变更记录", fontSize = 12.5.sp, color = Muted)
                } else {
                    vm.versions.forEach { v ->
                        Row(Modifier.fillMaxWidth().padding(vertical = Dimens.space2),
                            verticalAlignment = Alignment.CenterVertically) {
                            StatusChip(text = "v${v.version}", fg = Ink2, bg = AppBg)
                            Spacer(Modifier.width(Dimens.space3))
                            Column(Modifier.weight(1f)) {
                                Text(v.note.ifBlank { "配置更新" }, fontSize = 12.5.sp,
                                    color = Ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                Text(v.createdAt.take(16).replace("T", " "),
                                    fontSize = 11.sp, color = Muted)
                            }
                            if (v.operator.isNotBlank()) {
                                Text(v.operator, fontSize = 12.sp, color = Muted)
                            }
                        }
                        Hairline()
                    }
                }
            }
        }
        Spacer(Modifier.height(Dimens.space5))
    }
}

@Composable
private fun MaintainField(
    label: String,
    value: String,
    onChange: (String) -> Unit,
    hint: String,
    singleLine: Boolean = true,
) {
    Column(Modifier.fillMaxWidth().padding(bottom = Dimens.space3)) {
        Text(label, fontSize = 12.5.sp, fontWeight = FontWeight.Medium, color = Ink)
        Spacer(Modifier.height(Dimens.space1))
        OutlinedTextField(
            value = value,
            onValueChange = onChange,
            placeholder = { Text(hint, fontSize = 12.sp, color = Muted) },
            modifier = Modifier.fillMaxWidth()
                .then(if (singleLine) Modifier else Modifier.heightIn(min = 88.dp)),
            singleLine = singleLine,
            maxLines = if (singleLine) 1 else 6,
            colors = TextFieldDefaults.outlinedTextFieldColors(
                focusedBorderColor = Primary, cursorColor = Primary,
                unfocusedBorderColor = Line),
        )
    }
}
