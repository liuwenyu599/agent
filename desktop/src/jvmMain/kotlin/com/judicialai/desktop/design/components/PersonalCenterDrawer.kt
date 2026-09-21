package com.judicialai.desktop.design.components

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
import androidx.compose.material.Icon
import androidx.compose.material.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Star
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppScreen
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.OnPrimaryText
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.PrimarySoft
import com.judicialai.desktop.design.theme.Scrim
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.Warn
import com.judicialai.desktop.design.theme.WarnSoft
import com.judicialai.desktop.features.personal.PersonalSection
import com.judicialai.desktop.features.personal.PersonalViewModel

/**
 * 个人中心：承载全部「我的工作」，使 HOME 只保留四大生产力入口。
 * 我的待办 / 最近使用 / 我的文档 / 我的审批 / 我的收藏 / 个人设置。
 */
@Composable
fun PersonalCenterDrawer(vm: PersonalViewModel, onDismiss: () -> Unit) {
    Box(
        Modifier.fillMaxSize().background(Scrim)
            .clickable(
                interactionSource = androidx.compose.runtime.remember { androidx.compose.foundation.interaction.MutableInteractionSource() },
                indication = null, onClick = onDismiss,
            ),
    ) {
        Row(
            Modifier.align(Alignment.CenterEnd).width(640.dp).fillMaxHeight()
                .background(AppBg)
                .clickable(
                    interactionSource = androidx.compose.runtime.remember { androidx.compose.foundation.interaction.MutableInteractionSource() },
                    indication = null, onClick = {},
                ),
        ) {
            // 左：分区菜单
            Column(Modifier.width(184.dp).fillMaxHeight().background(Surface).padding(Dimens.space4)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        Modifier.size(34.dp).clip(CircleShape).background(Primary),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(AppState.displayName.take(1), color = OnPrimaryText,
                            fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                    }
                    Spacer(Modifier.width(Dimens.space2))
                    Column(Modifier.weight(1f)) {
                        Text(AppState.displayName, fontSize = 13.sp, color = Ink,
                            fontWeight = FontWeight.Medium, maxLines = 1,
                            overflow = TextOverflow.Ellipsis)
                        Text(AppState.roleText, fontSize = 11.sp, color = Muted)
                    }
                }
                Spacer(Modifier.height(Dimens.space4))
                PersonalSection.values().forEach { s ->
                    val selected = vm.section == s
                    Row(
                        Modifier.fillMaxWidth()
                            .clip(RoundedCornerShape(Dimens.radiusSm))
                            .background(if (selected) PrimarySoft else Color.Transparent)
                            .clickable { vm.select(s) }
                            .padding(horizontal = Dimens.space3, vertical = Dimens.space2 + 2.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(s.title, fontSize = 13.sp,
                            color = if (selected) Primary else Ink2,
                            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                            modifier = Modifier.weight(1f))
                        if (s == PersonalSection.TODO && vm.todoCount > 0) {
                            Text("${vm.todoCount}", fontSize = 11.sp, color = Muted)
                        }
                    }
                    Spacer(Modifier.height(Dimens.space1))
                }
                Spacer(Modifier.weight(1f))
                Row(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(Dimens.radiusSm))
                        .clickable { onDismiss() }
                        .padding(horizontal = Dimens.space3, vertical = Dimens.space2),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Default.Close, null, tint = Muted,
                        modifier = Modifier.size(Dimens.iconSm))
                    Spacer(Modifier.width(Dimens.space2))
                    Text("关闭", fontSize = 12.5.sp, color = Muted)
                }
            }
            Box(Modifier.width(1.dp).fillMaxHeight().background(Line))

            // 右：分区内容
            Column(Modifier.weight(1f).fillMaxHeight().padding(Dimens.space5)
                .verticalScroll(rememberScrollState())) {
                SectionTitle(title = vm.section.title)
                Spacer(Modifier.height(Dimens.space3))
                when (vm.section) {
                    PersonalSection.TODO -> TodoList(vm.todos, "当前没有待你审批的公文",
                        "公文送审后会在这里出现")
                    PersonalSection.MY_APPROVALS -> TodoList(vm.mine, "你还没有发起过审批",
                        "在智能写作工作台提交审批后会出现在这里")
                    PersonalSection.RECENT -> DocList(vm.recent)
                    PersonalSection.DOCS -> DocList(vm.docs)
                    PersonalSection.FAVORITES -> FavoritesPanel()
                    PersonalSection.SETTINGS -> SettingsPanel()
                }
            }
        }
    }
}

@Composable
private fun TodoList(items: List<PersonalViewModel.TodoItem>, emptyText: String, hint: String) {
    if (items.isEmpty()) {
        EmptyState(emptyText, hint = hint, modifier = Modifier.padding(vertical = Dimens.space8))
        return
    }
    items.forEach { t ->
        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(Dimens.radiusSm))
                .clickable { AppState.navigate(AppScreen.APPROVAL) }
                .padding(vertical = Dimens.space2 + 2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(t.title, fontSize = 13.sp, color = Ink, maxLines = 1,
                    overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(2.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (t.stepName.isNotBlank()) {
                        Text(t.stepName, fontSize = 11.5.sp, color = Ink2)
                        Spacer(Modifier.width(Dimens.space2))
                    }
                    Text(t.submitter.ifBlank { t.submittedAt }, fontSize = 11.5.sp, color = Muted)
                    Spacer(Modifier.width(Dimens.space2))
                    Text(t.submittedAt, fontSize = 11.5.sp, color = Muted)
                }
            }
            Spacer(Modifier.width(Dimens.space3))
            StatusChip(text = t.statusName.ifBlank { "流转中" }, fg = Warn, bg = WarnSoft)
        }
        Spacer(Modifier.height(Dimens.space1))
        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
    }
}

@Composable
private fun DocList(items: List<PersonalViewModel.DocItem>) {
    if (items.isEmpty()) {
        EmptyState("暂无文档", hint = "从「智能写作」开始第一篇",
            modifier = Modifier.padding(vertical = Dimens.space8))
        return
    }
    items.forEach { d ->
        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(Dimens.radiusSm))
                .clickable { AppState.navigate(AppScreen.DOCUMENTS) }
                .padding(vertical = Dimens.space2 + 2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Default.Description, null, tint = Muted,
                modifier = Modifier.size(Dimens.iconMd))
            Spacer(Modifier.width(Dimens.space3))
            Column(Modifier.weight(1f)) {
                Text(d.title, fontSize = 13.sp, color = Ink, maxLines = 1,
                    overflow = TextOverflow.Ellipsis)
                Text(d.updatedAt.ifBlank { "—" }, fontSize = 11.5.sp, color = Muted)
            }
        }
        Spacer(Modifier.height(Dimens.space1))
        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
    }
}

@Composable
private fun FavoritesPanel() {
    Column(verticalArrangement = Arrangement.spacedBy(Dimens.space3)) {
        NoticeBar(
            text = "收藏能力后端目前仅覆盖 PPT 模板与 PPT 文档，暂无通用收藏接口；" +
                "为避免伪造数据，这里不做占位列表。",
            fg = Ink2, bg = AppBg,
        )
        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(Dimens.radiusSm))
                .clickable { AppState.navigate(AppScreen.PPT) }
                .padding(vertical = Dimens.space3),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Default.Star, null, tint = Warn, modifier = Modifier.size(Dimens.iconMd))
            Spacer(Modifier.width(Dimens.space3))
            Text("查看 PPT 收藏（模板 / 材料）", fontSize = 13.sp, color = Ink)
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
    }
}

@Composable
private fun SettingsPanel() {
    Column(verticalArrangement = Arrangement.spacedBy(Dimens.space3)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("账号", fontSize = 12.5.sp, color = Muted, modifier = Modifier.width(88.dp))
            Text(AppState.username.ifBlank { "—" }, fontSize = 13.sp, color = Ink)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("姓名", fontSize = 12.5.sp, color = Muted, modifier = Modifier.width(88.dp))
            Text(AppState.displayName, fontSize = 13.sp, color = Ink)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("角色", fontSize = 12.5.sp, color = Muted, modifier = Modifier.width(88.dp))
            Text(AppState.roleText, fontSize = 13.sp, color = Ink)
        }
        Spacer(Modifier.height(Dimens.space2))
        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(Dimens.radiusSm))
                .clickable { AppState.navigate(AppScreen.SETTINGS) }
                .padding(vertical = Dimens.space3),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Default.Settings, null, tint = Muted,
                modifier = Modifier.size(Dimens.iconMd))
            Spacer(Modifier.width(Dimens.space3))
            Text("服务器连接设置", fontSize = 13.sp, color = Ink)
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(Dimens.radiusSm))
                .clickable { AppState.logout() }
                .padding(vertical = Dimens.space3),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("退出登录", fontSize = 13.sp, color = Warn)
        }
    }
}
