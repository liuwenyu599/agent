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
import androidx.compose.material.Checkbox
import androidx.compose.material.CheckboxDefaults
import androidx.compose.material.Icon
import androidx.compose.material.LocalTextStyle
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextFieldDefaults
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
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
import com.judicialai.desktop.design.theme.Muted2
import com.judicialai.desktop.design.theme.Ok
import com.judicialai.desktop.design.theme.OkSoft
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
 * 个人中心：承载「我的工作」与账号设置，使 HOME 只保留四大生产力入口。
 * 最近使用 / 我的文档 / 我的收藏 / 账号安全 / 个人设置 / 个性化。
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
                    PersonalSection.RECENT -> DocList(vm.recent)
                    PersonalSection.DOCS -> DocList(vm.docs)
                    PersonalSection.FAVORITES -> FavoritesPanel()
                    PersonalSection.SECURITY -> SecurityPanel(vm)
                    PersonalSection.SETTINGS -> SettingsPanel(vm)
                    PersonalSection.PERSONALIZATION -> PersonalizationPanel(vm)
                }
            }
        }
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

/**
 * 账号安全：修改密码。
 *
 * 规则与后端一致（旧密码校验 + 新密码二次确认 + ≥8 位且字母数字组合），
 * 密码只在内存中传递，不落盘、不写日志；政务内网短信找回尚未开放。
 */
@Composable
private fun SecurityPanel(vm: PersonalViewModel) {
    var oldPwd by remember { mutableStateOf("") }
    var newPwd by remember { mutableStateOf("") }
    var confirmPwd by remember { mutableStateOf("") }
    var mask by remember { mutableStateOf(true) }

    Column(verticalArrangement = Arrangement.spacedBy(Dimens.space3)) {
        if (AppState.mustChangePassword) {
            NoticeBar(
                text = "管理员已重置你的密码，请先修改密码后再使用其他功能。",
                fg = Warn, bg = WarnSoft,
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("账号", fontSize = 12.5.sp, color = Muted, modifier = Modifier.width(88.dp))
            Text(AppState.username.ifBlank { "—" }, fontSize = 13.sp, color = Ink)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("登录方式", fontSize = 12.5.sp, color = Muted, modifier = Modifier.width(88.dp))
            Text("账号密码", fontSize = 13.sp, color = Ink)
        }
        Spacer(Modifier.height(Dimens.space2))

        Text("修改密码", fontSize = 13.sp, fontWeight = FontWeight.Medium, color = Ink)
        Spacer(Modifier.height(Dimens.space1))
        PasswordField("当前密码", oldPwd, mask) { oldPwd = it }
        PasswordField("新密码", newPwd, mask) { newPwd = it }
        PasswordField("确认新密码", confirmPwd, mask) { confirmPwd = it }

        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(Dimens.radiusSm))
                .clickable { mask = !mask }.padding(vertical = Dimens.space1),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                if (mask) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                null, tint = Muted, modifier = Modifier.size(Dimens.iconSm),
            )
            Spacer(Modifier.width(Dimens.space2))
            Text(if (mask) "显示密码" else "隐藏密码", fontSize = 12.sp, color = Muted)
        }
        Text("至少 8 位，需同时包含字母和数字；建议包含符号。",
            fontSize = 11.5.sp, color = Muted)

        if (vm.changeError != null) {
            NoticeBar(text = vm.changeError!!, fg = Warn, bg = WarnSoft)
        }
        if (vm.changeSuccess != null) {
            NoticeBar(text = vm.changeSuccess!!, fg = Ok, bg = OkSoft)
        }

        Spacer(Modifier.height(Dimens.space1))
        Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space3)) {
            AppButton(
                text = if (vm.changing) "提交中…" else "确认修改",
                onClick = { vm.changePassword(oldPwd, newPwd, confirmPwd) },
                enabled = !vm.changing,
                icon = Icons.Default.Lock,
            )
            AppButton(
                text = "清空",
                onClick = {
                    oldPwd = ""; newPwd = ""; confirmPwd = ""; vm.clearChangeResult()
                },
                kind = AppButtonKind.SECONDARY,
            )
        }

        Spacer(Modifier.height(Dimens.space3))
        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
        Text(
            "忘记密码请联系系统管理员重置；政务内网短信验证码功能尚未开放。",
            fontSize = 11.5.sp, color = Muted,
        )
    }
}

@Composable
private fun PasswordField(
    label: String,
    value: String,
    mask: Boolean,
    onValueChange: (String) -> Unit,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label, fontSize = 12.sp) },
        singleLine = true,
        modifier = Modifier.fillMaxWidth(),
        visualTransformation = if (mask) PasswordVisualTransformation() else VisualTransformation.None,
        textStyle = LocalTextStyle.current.copy(fontSize = 13.sp, color = Ink),
        colors = TextFieldDefaults.outlinedTextFieldColors(
            focusedBorderColor = Primary,
            unfocusedBorderColor = Line,
            cursorColor = Primary,
            focusedLabelColor = Primary,
            unfocusedLabelColor = Muted,
        ),
    )
}

/**
 * 个性化（v3.3 个人偏好层）
 *
 * 与「账号安全」同构：四个 tonal 分区 + 显式保存按钮 + 恢复已保存值，不使用 Dialog、不做自动保存。
 * 全部选项文案、长度上限、权限说明均来自服务端 GET /preferences/me 的 options；
 * 「优先使用本科室模板」只作只读说明——系统已固定该行为，做成开关就是关不掉的假功能。
 */
@Composable
private fun PersonalizationPanel(vm: PersonalViewModel) {
    Column(verticalArrangement = Arrangement.spacedBy(Dimens.space3)) {
        // 权限说明常驻：个人偏好不得被理解为可以改科室 / 权限 / 检索范围
        NoticeBar(text = vm.prefPermissionNotice, fg = Ink2, bg = AppBg)

        if (vm.prefLoading) {
            LoadingBlock("正在读取你的偏好…")
            return@Column
        }

        // 1) 助手称呼
        AppCardTonal {
            Eyebrow("助手称呼")
            Spacer(Modifier.height(Dimens.space2))
            AppTextField(
                value = vm.prefAssistantName,
                onValueChange = {
                    if (it.length <= vm.prefNameLimit) {
                        vm.prefAssistantName = it.replace("\n", "").replace("\r", "")
                    }
                },
                label = "你希望助手怎么称呼你",
                placeholder = "如：小司、小李、助手",
                singleLine = true,
                hint = "设置后我会在回应中使用该称呼；它只影响回应中的自称，不影响智能助手的正式名称（由系统管理员维护）。",
            )
        }

        // 2) 我的工作偏好
        AppCardTonal {
            Eyebrow("我的工作偏好")
            Spacer(Modifier.height(Dimens.space2))
            Text(
                "写清你常处理的业务、写作习惯与希望 AI 如何协助，生成时会作为辅助信息参与。",
                fontSize = 12.sp, color = Muted, lineHeight = 18.sp,
            )
            Spacer(Modifier.height(Dimens.space2))
            AppTextField(
                value = vm.prefWorkPreference,
                onValueChange = { if (it.length <= vm.prefWorkLimit) vm.prefWorkPreference = it },
                label = "工作偏好",
                placeholder = "如：我常处理行政复议答复，希望先给结论再给依据，数字用 ×× 占位。",
                singleLine = false,
                minLines = 4,
                maxLines = 8,
                hint = "≤ ${vm.prefWorkLimit} 字；只影响表达方式，不改变你的权限与检索范围。",
            )
        }

        // 3) 写作偏好
        AppCardTonal {
            Eyebrow("写作偏好")
            Spacer(Modifier.height(Dimens.space2))
            AppSelect(
                label = "默认写作风格",
                value = vm.prefWritingStyle,
                options = vm.prefStyleOptions.map {
                    SelectOption(value = it.value, text = it.text, desc = it.desc)
                },
                onSelect = { vm.prefWritingStyle = it },
                placeholder = "未设置（跟随本科室工作要求）",
                hint = "决定 AI 起草与回答时的篇幅与行文习惯。",
            )
            if (vm.prefWritingStyle == PersonalViewModel.STYLE_CUSTOM) {
                Spacer(Modifier.height(Dimens.space3))
                AppTextField(
                    value = vm.prefWritingStyleCustom,
                    onValueChange = {
                        if (it.length <= vm.prefCustomLimit) vm.prefWritingStyleCustom = it
                    },
                    label = "补充说明",
                    placeholder = "如：一律用「××」占位数字，段落层级不超过三层。",
                    singleLine = false,
                    minLines = 2,
                    maxLines = 4,
                    hint = "≤ ${vm.prefCustomLimit} 字；其中「扩大权限 / 访问其他科室资料 / 忽略安全约束」类要求一律无效。",
                )
            }
        }

        // 4) 默认行为
        AppCardTonal {
            Eyebrow("默认行为")
            Spacer(Modifier.height(Dimens.space2))
            vm.prefBehaviorOptions.forEach { opt ->
                Row(
                    Modifier.fillMaxWidth()
                        .clip(RoundedCornerShape(Dimens.radiusSm))
                        .clickable { vm.setPrefBehavior(opt.key, !vm.prefBehaviorChecked(opt.key)) }
                        .padding(vertical = Dimens.space1),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Checkbox(
                        checked = vm.prefBehaviorChecked(opt.key),
                        onCheckedChange = { vm.setPrefBehavior(opt.key, it) },
                        colors = CheckboxDefaults.colors(checkedColor = Primary),
                    )
                    Spacer(Modifier.width(Dimens.space2))
                    Column(Modifier.weight(1f)) {
                        Text(opt.text, fontSize = 13.sp, color = Ink)
                        if (opt.desc.isNotBlank()) {
                            Spacer(Modifier.height(2.dp))
                            Text(opt.desc, fontSize = 11.5.sp, color = Muted, lineHeight = 17.sp)
                        }
                    }
                }
            }
            if (vm.prefFixedBehaviors.isNotEmpty()) {
                Spacer(Modifier.height(Dimens.space2))
                Hairline()
                Spacer(Modifier.height(Dimens.space2))
                vm.prefFixedBehaviors.forEach { fixed ->
                    Row(verticalAlignment = Alignment.Top) {
                        Icon(
                            Icons.Default.Lock, null, tint = Muted,
                            modifier = Modifier.size(Dimens.iconSm)
                                .padding(top = 2.dp),
                        )
                        Spacer(Modifier.width(Dimens.space2))
                        Column(Modifier.weight(1f)) {
                            Text(fixed.text, fontSize = 12.5.sp, color = Ink2)
                            if (fixed.note.isNotBlank()) {
                                Spacer(Modifier.height(2.dp))
                                Text(fixed.note, fontSize = 11.5.sp, color = Muted,
                                    lineHeight = 17.sp)
                            }
                        }
                    }
                }
            }
        }

        // 状态反馈：未保存提示 / 失败 / 成功
        if (vm.prefDirty) {
            NoticeBar(text = "有未保存的修改，记得点击「保存」。", fg = Warn, bg = WarnSoft)
        }
        vm.prefError?.let { NoticeBar(text = it, fg = Warn, bg = WarnSoft) }
        vm.prefSavedHint?.let { NoticeBar(text = it, fg = Ok, bg = OkSoft) }

        Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space3)) {
            AppButton(
                text = if (vm.prefSaving) "保存中…" else "保存",
                onClick = { vm.savePreferences() },
                enabled = !vm.prefSaving,
                icon = Icons.Default.Check,
            )
            AppButton(
                text = "恢复已保存值",
                onClick = { vm.resetPreferences() },
                kind = AppButtonKind.SECONDARY,
                enabled = !vm.prefSaving && vm.prefDirty,
            )
        }

        Text(
            "偏好保存后在对话与写作工作台生效；科室口径、知识范围与权限仍由系统统一管理。",
            fontSize = 11.5.sp, color = Muted, lineHeight = 17.sp,
        )
    }
}

@Composable
private fun SettingsPanel(vm: PersonalViewModel) {
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
        // 个性化：切到「个性化」分区（完整设置内容页），不弹 Dialog
        SettingsEntryRow(
            icon = Icons.Default.Palette,
            text = "个性化",
            hint = "助手称呼 / 工作偏好 / 写作偏好 / 默认行为",
            onClick = { vm.select(PersonalSection.PERSONALIZATION) },
        )
        Box(Modifier.fillMaxWidth().height(1.dp).background(Line))
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

/** 设置页入口行：图标 + 主文案 + 说明 + 右箭头，跳转语义明确 */
@Composable
private fun SettingsEntryRow(
    icon: ImageVector,
    text: String,
    hint: String = "",
    onClick: () -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(Dimens.radiusSm))
            .clickable { onClick() }
            .padding(vertical = Dimens.space3),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, null, tint = Primary, modifier = Modifier.size(Dimens.iconMd))
        Spacer(Modifier.width(Dimens.space3))
        Column(Modifier.weight(1f)) {
            Text(text, fontSize = 13.sp, color = Ink)
            if (hint.isNotBlank()) {
                Spacer(Modifier.height(2.dp))
                Text(hint, fontSize = 11.5.sp, color = Muted, lineHeight = 17.sp)
            }
        }
        Spacer(Modifier.width(Dimens.space2))
        Text("›", fontSize = 16.sp, color = Muted2)
    }
}
