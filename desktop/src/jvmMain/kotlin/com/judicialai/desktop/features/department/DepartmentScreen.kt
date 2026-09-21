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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Card
import androidx.compose.material.Icon
import androidx.compose.material.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Groups
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.design.components.EmptyState
import com.judicialai.desktop.design.components.Hairline
import com.judicialai.desktop.design.components.LoadingScreen
import com.judicialai.desktop.design.components.NoticeBar
import com.judicialai.desktop.design.components.PageHeader
import com.judicialai.desktop.design.components.SectionTitle
import com.judicialai.desktop.design.components.SoftPanel
import com.judicialai.desktop.design.components.StatusChip
import com.judicialai.desktop.design.components.SurfaceCard
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Navy
import com.judicialai.desktop.design.theme.Ok
import com.judicialai.desktop.design.theme.OkSoft
import com.judicialai.desktop.design.theme.PrimarySoft
import com.judicialai.desktop.design.theme.Surface

/**
 * 科室空间：科室 Agent 是组织知识与业务能力的载体。
 * - 卡片显示简称，正式名称在副标题与管理页面显示；
 * - 模型统一为后端模型服务，各科只是 system prompt / 知识权限 / 模板不同；
 * - 知识范围由后端下发并强隔离，前端仅展示。
 */
@Composable
fun DepartmentScreen(vm: DepartmentViewModel = remember { DepartmentViewModel() }) {
    Column(
        Modifier.fillMaxWidth().background(AppBg).verticalScroll(rememberScrollState())
            .padding(Dimens.space6),
    ) {
        PageHeader(
            title = "科室空间",
            subtitle = "统一由后端模型服务驱动，各科室 Agent 拥有独立知识权限、模板与业务上下文",
        )

        if (vm.loading && vm.departments.isEmpty()) {
            LoadingScreen("加载科室信息…")
            return@Column
        }
        if (vm.departments.isEmpty()) {
            EmptyState("后端暂未返回科室数据",
                hint = "需后端 /departments 接口（科室与 Agent 配置）上线后展示")
            return@Column
        }

        SectionTitle(title = "全部科室", more = null)
        Spacer(Modifier.height(Dimens.space3))
        DeptGrid(vm)

        Spacer(Modifier.height(Dimens.space6))
        Hairline()
        Spacer(Modifier.height(Dimens.space5))

        val agent = vm.selectedAgent
        if (agent == null) {
            SoftPanel {
                Text("该科室尚未配置 Agent", fontSize = 13.sp, color = Ink2)
                Text("由系统管理员或本科室知识管理员在管理后台配置后生效",
                    fontSize = 12.sp, color = Muted)
            }
        } else {
            AgentPanel(agent)
        }

        Spacer(Modifier.height(Dimens.space4))
        NoticeBar(
            text = "检索边界由后端强制：search(query, allowed_scope=[GLOBAL, 本部门])，" +
                "向量层按 scope 过滤，不会命中其他科室资料。",
            fg = Ink2, bg = Surface,
        )
    }
}

@Composable
private fun DeptGrid(vm: DepartmentViewModel) {
    val rows = vm.departments.chunked(5)
    Column(verticalArrangement = Arrangement.spacedBy(Dimens.space3)) {
        rows.forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space3)) {
                row.forEach { dept ->
                    DeptCard(
                        dept = dept,
                        selected = dept.code == vm.selectedCode,
                        modifier = Modifier.weight(1f),
                        onClick = { vm.select(dept.code) },
                    )
                }
                repeat(5 - row.size) { Spacer(Modifier.weight(1f)) }
            }
        }
    }
}

@Composable
private fun DeptCard(
    dept: DepartmentViewModel.Dept,
    selected: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    Card(
        modifier = modifier,
        shape = RoundedCornerShape(Dimens.radiusMd),
        elevation = Dimens.elevCard,
        backgroundColor = Surface,
    ) {
        Column(
            Modifier.fillMaxWidth()
                .clickable(onClick = onClick)
                .background(if (selected) PrimarySoft else Surface)
                .padding(Dimens.space4),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(dept.shortName, fontSize = 13.5.sp, fontWeight = FontWeight.SemiBold,
                    color = Ink, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f))
                if (dept.isMine) {
                    StatusChip(text = "我的科室", fg = Ok, bg = OkSoft)
                }
            }
            Spacer(Modifier.height(Dimens.space2))
            Text(dept.name, fontSize = 11.sp, color = Muted, maxLines = 2,
                overflow = TextOverflow.Ellipsis, lineHeight = 15.sp)
            Spacer(Modifier.height(Dimens.space3))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("${dept.memberCount} 人", fontSize = 11.sp, color = Muted)
                Spacer(Modifier.width(Dimens.space2))
                Text("·", fontSize = 11.sp, color = Muted)
                Spacer(Modifier.width(Dimens.space2))
                Text("${dept.kbCount} 知识库", fontSize = 11.sp, color = Muted)
            }
        }
    }
}

@Composable
private fun AgentPanel(agent: DepartmentViewModel.Agent) {
    SurfaceCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(40.dp).clip(CircleShape).background(Navy),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Default.Groups, null, tint = Surface,
                    modifier = Modifier.size(Dimens.iconLg))
            }
            Spacer(Modifier.width(Dimens.space3))
            Column(Modifier.weight(1f)) {
                Text(agent.name, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                Text(agent.deptName.ifBlank { agent.deptCode }, fontSize = 11.5.sp, color = Muted)
            }
            StatusChip(text = agent.model.ifBlank { "统一模型服务" }, fg = Ink2, bg = AppBg)
        }

        Spacer(Modifier.height(Dimens.space4))
        if (agent.intro.isNotBlank()) {
            Text(agent.intro, fontSize = 12.5.sp, color = Ink2, lineHeight = 20.sp)
            Spacer(Modifier.height(Dimens.space4))
        }

        Row {
            Column(Modifier.weight(1f)) {
                SectionTitle(title = "知识范围")
                Spacer(Modifier.height(Dimens.space2))
                agent.scopes.forEach { s ->
                    Text(s, fontSize = 12.sp, color = Ink2,
                        modifier = Modifier.padding(vertical = 2.dp))
                }
                if (agent.scopes.isEmpty()) Text("—", fontSize = 12.sp, color = Muted)
                Spacer(Modifier.height(Dimens.space4))
                SectionTitle(title = "配置维护")
                Spacer(Modifier.height(Dimens.space2))
                Text(agent.manager.ifBlank { "未指定" }, fontSize = 12.sp, color = Ink2)
            }
            Spacer(Modifier.width(Dimens.space5))
            Column(Modifier.weight(1f)) {
                SectionTitle(title = "推荐任务")
                Spacer(Modifier.height(Dimens.space2))
                agent.recommendedTasks.forEach { t ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clip(RoundedCornerShape(Dimens.radiusSm))
                            .clickable {
                                AppState.pendingWritingIntent = t
                                AppState.navigate(com.judicialai.desktop.app.AppScreen.WRITING)
                            }
                            .padding(vertical = Dimens.space1 + 2.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(t, fontSize = 12.5.sp, color = Ink, modifier = Modifier.weight(1f))
                        Text("→", fontSize = 12.sp, color = Muted)
                    }
                }
                if (agent.recommendedTasks.isEmpty()) Text("—", fontSize = 12.sp, color = Muted)
                Spacer(Modifier.height(Dimens.space4))
                SectionTitle(title = "专属模板")
                Spacer(Modifier.height(Dimens.space2))
                agent.templates.forEach { t ->
                    Text(t, fontSize = 12.sp, color = Ink2,
                        modifier = Modifier.padding(vertical = 2.dp))
                }
                if (agent.templates.isEmpty()) Text("—", fontSize = 12.sp, color = Muted)
            }
        }
    }
}
