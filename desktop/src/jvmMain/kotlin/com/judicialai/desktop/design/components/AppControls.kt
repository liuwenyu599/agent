package com.judicialai.desktop.design.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.DropdownMenu
import androidx.compose.material.Icon
import androidx.compose.material.LocalContentAlpha
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextFieldDefaults
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Search
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.design.theme.AiSoft
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.Danger
import com.judicialai.desktop.design.theme.DangerSoft
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.LineStrong
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Muted2
import com.judicialai.desktop.design.theme.OnPrimaryText
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.PrimarySoft
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.SurfaceDeep
import com.judicialai.desktop.design.theme.SurfaceTonal

/** 下拉选项：value 为提交值，text 为主文案，desc 为可选副文案 */
data class SelectOption(val value: String, val text: String, val desc: String = "")

/**
 * 统一 Select（ExposedDropdown 风格）
 *
 * 与 OutlinedTextField + DropdownMenu 拼装的区别：
 * - 整个字段区域是一个可点击 Surface，点击任意位置即展开；
 * - 右侧始终有展开/收起箭头（展开时旋转 180°）；
 * - hover / expanded / disabled 有明确边框与底色差异；
 * - 弹层宽度与字段等宽，选项显示完整，当前项带勾选标记与 tonal 底；
 * - 只读，禁止自由输入。
 */
@Composable
fun AppSelect(
    label: String,
    value: String,
    options: List<SelectOption>,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String = "请选择",
    enabled: Boolean = true,
    error: Boolean = false,
    hint: String? = null,
    leadingIcon: ImageVector? = null,
) {
    var expanded by remember { mutableStateOf(false) }
    var fieldWidth by remember { mutableStateOf(androidx.compose.ui.unit.IntSize.Zero) }
    val interaction = remember { MutableInteractionSource() }
    val hovered by interaction.collectIsHoveredAsState()

    val selected = options.firstOrNull { it.value == value }
    val shape = RoundedCornerShape(Dimens.radiusControl)

    val borderColor = when {
        error -> Danger
        expanded -> Primary
        hovered && enabled -> LineStrong
        else -> Line
    }
    val background = when {
        !enabled -> SurfaceDeep
        expanded -> PrimarySoft
        hovered -> SurfaceTonal
        else -> Surface
    }

    val arrowRotation by animateFloatAsState(if (expanded) 180f else 0f)

    Column(modifier) {
        FieldLabel(label)

        Box {
            Row(
                Modifier.fillMaxWidth()
                    .heightIn(min = Dimens.hControl)
                    .clip(shape)
                    .background(background)
                    .border(1.dp, borderColor, shape)
                    .then(
                        if (enabled) Modifier.clickable(
                            interactionSource = interaction,
                            indication = null,
                        ) { expanded = true } else Modifier
                    )
                    .onSizeChangedSafe { fieldWidth = it }
                    .padding(horizontal = 12.dp, vertical = 9.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (leadingIcon != null) {
                    Icon(leadingIcon, contentDescription = null,
                        tint = if (enabled) Primary else Muted2,
                        modifier = Modifier.size(Dimens.iconMd))
                    Spacer(Modifier.width(Dimens.space2))
                }
                Column(Modifier.weight(1f)) {
                    Text(
                        selected?.text ?: placeholder,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Medium,
                        color = if (selected != null) Ink else Muted2,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (selected != null && selected.desc.isNotBlank()) {
                        Text(selected.desc, fontSize = 11.5.sp, color = Muted,
                            maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                }
                Spacer(Modifier.width(Dimens.space2))
                Icon(
                    Icons.Default.ArrowDropDown,
                    contentDescription = if (expanded) "收起" else "展开",
                    tint = if (enabled) Ink2 else Muted2,
                    modifier = Modifier.size(Dimens.iconLg).rotate(arrowRotation),
                )
            }

            val widthDp = with(LocalDensity.current) { fieldWidth.width.toDp() }
            DropdownMenu(
                expanded = expanded && enabled,
                onDismissRequest = { expanded = false },
                modifier = Modifier
                    .then(if (widthDp > 0.dp) Modifier.width(widthDp) else Modifier)
                    .heightIn(max = 320.dp),
            ) {
                if (options.isEmpty()) {
                    Box(
                        Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 12.dp),
                        contentAlignment = Alignment.CenterStart,
                    ) { Text("暂无可选项", fontSize = 13.sp, color = Muted) }
                }
                // 注意：DropdownMenu 自身已是纵向可滚动容器，内部不能再嵌套 verticalScroll，
                // 否则会以无限最大高度约束测量，直接抛 IllegalStateException。
                options.forEach { opt ->
                    val isSelected = opt.value == value
                    Row(
                        Modifier.fillMaxWidth()
                            .clip(RoundedCornerShape(Dimens.radiusSm))
                            .background(if (isSelected) AiSoft else Color.Transparent)
                            .clickable {
                                onSelect(opt.value)
                                expanded = false
                            }
                            .padding(horizontal = 12.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(
                                opt.text,
                                fontSize = 13.5.sp,
                                fontWeight = if (isSelected) FontWeight.SemiBold
                                else FontWeight.Normal,
                                color = if (isSelected) Primary else Ink,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            if (opt.desc.isNotBlank()) {
                                Text(opt.desc, fontSize = 11.5.sp, color = Muted,
                                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                        }
                        if (isSelected) {
                            Spacer(Modifier.width(Dimens.space2))
                            Icon(Icons.Default.Check, contentDescription = "已选中",
                                tint = Primary, modifier = Modifier.size(Dimens.iconSm))
                        }
                    }
                }
            }
        }

        if (hint != null) {
            Spacer(Modifier.height(Dimens.space1))
            Text(hint, fontSize = 11.5.sp, color = if (error) Danger else Muted)
        }
    }
}

/** 字段标签：所有表单控件共用，保证标签层级一致 */
@Composable
fun FieldLabel(text: String, modifier: Modifier = Modifier) {
    Column(modifier) {
        Text(text, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = Ink2)
        Spacer(Modifier.height(Dimens.space1))
    }
}

/**
 * 统一输入框：标签在上、控件在下，hover / focus / error 状态明确。
 * 与 [AppSelect] 共用同一套字段节奏。
 */
@Composable
fun AppTextField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    modifier: Modifier = Modifier,
    placeholder: String = "",
    singleLine: Boolean = true,
    minLines: Int = 1,
    maxLines: Int = if (singleLine) 1 else 8,
    enabled: Boolean = true,
    error: Boolean = false,
    hint: String? = null,
    leadingIcon: ImageVector? = null,
) {
    Column(modifier) {
        FieldLabel(label)
        OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            placeholder = {
                if (placeholder.isNotBlank()) Text(placeholder, fontSize = 13.sp, color = Muted2)
            },
            leadingIcon = leadingIcon?.let {
                { Icon(it, contentDescription = null, tint = Muted,
                    modifier = Modifier.size(Dimens.iconMd)) }
            },
            enabled = enabled,
            singleLine = singleLine,
            minLines = minLines,
            // 防御：minLines > maxLines 会让 Compose 直接抛
            // IllegalArgumentException（heightInLines 校验），整页崩掉。
            // 调用方只传 minLines 时默认 maxLines=8，很容易踩到，这里兜底保证 min <= max。
            maxLines = maxOf(maxLines, minLines),
            modifier = Modifier.fillMaxWidth()
                .heightIn(min = Dimens.hControl),
            shape = RoundedCornerShape(Dimens.radiusControl),
            textStyle = androidx.compose.ui.text.TextStyle(fontSize = 14.sp, color = Ink),
            colors = TextFieldDefaults.outlinedTextFieldColors(
                textColor = Ink,
                backgroundColor = if (enabled) Surface else SurfaceDeep,
                cursorColor = Primary,
                focusedBorderColor = if (error) Danger else Primary,
                unfocusedBorderColor = if (error) Danger else Line,
                disabledBorderColor = Line,
                leadingIconColor = Muted,
                placeholderColor = Muted2,
            ),
        )
        if (hint != null) {
            Spacer(Modifier.height(Dimens.space1))
            Text(hint, fontSize = 11.5.sp, color = if (error) Danger else Muted)
        }
    }
}

/** 全局搜索：胶囊形、弱底，不抢主操作权重 */
@Composable
fun AppSearchField(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String = "搜索",
    onFocusOpen: (() -> Unit)? = null,
) {
    val shape = RoundedCornerShape(Dimens.radiusPill)
    Row(
        modifier.height(Dimens.hControl)
            .clip(shape)
            .background(SurfaceDeep)
            .border(1.dp, Line, shape)
            .clickable { onFocusOpen?.invoke() }
            .padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Default.Search, contentDescription = null, tint = Muted,
            modifier = Modifier.size(Dimens.iconMd))
        Spacer(Modifier.width(Dimens.space2))
        androidx.compose.material.TextField(
            value = value,
            onValueChange = {
                onValueChange(it)
                onFocusOpen?.invoke()
            },
            placeholder = { Text(placeholder, fontSize = 12.5.sp, color = Muted2) },
            singleLine = true,
            modifier = Modifier.weight(1f),
            textStyle = androidx.compose.ui.text.TextStyle(fontSize = 13.sp, color = Ink),
            colors = TextFieldDefaults.textFieldColors(
                backgroundColor = Color.Transparent,
                cursorColor = Primary,
                focusedIndicatorColor = Color.Transparent,
                disabledIndicatorColor = Color.Transparent,
                unfocusedIndicatorColor = Color.Transparent,
            ),
        )
    }
}

/** 表单错误条 */
@Composable
fun FieldError(text: String?) {
    if (text == null) return
    Row(
        Modifier.fillMaxWidth()
            .clip(RoundedCornerShape(Dimens.radiusSm))
            .background(DangerSoft)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text, fontSize = 12.sp, color = Danger)
    }
}

/** 内联提示条 */
@Composable
fun InlineNotice(
    text: String,
    modifier: Modifier = Modifier,
    container: Color = AiSoft,
    content: Color = Primary,
    icon: ImageVector? = null,
) {
    Row(
        modifier.fillMaxWidth()
            .clip(RoundedCornerShape(Dimens.radiusSm))
            .background(container)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = content,
                modifier = Modifier.size(Dimens.iconSm))
            Spacer(Modifier.width(Dimens.space2))
        }
        Text(text, fontSize = 12.sp, color = content, lineHeight = 18.sp)
    }
}

/** 顶部小标题（区块的 eyebrow） */
@Composable
fun Eyebrow(text: String, modifier: Modifier = Modifier, color: Color = Muted) {
    Text(text, modifier, fontSize = 11.5.sp, fontWeight = FontWeight.SemiBold,
        color = color, letterSpacing = 0.4.sp)
}

private fun Modifier.onSizeChangedSafe(block: (androidx.compose.ui.unit.IntSize) -> Unit): Modifier =
    this.onGloballyPositioned { block(it.size) }

/** 主操作按钮条：用于对话框底部 */
@Composable
fun PrimaryActionRow(
    confirmText: String,
    onConfirm: () -> Unit,
    onCancel: (() -> Unit)?,
    modifier: Modifier = Modifier,
    cancelText: String = "取消",
    enabled: Boolean = true,
) {
    Row(modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(Dimens.space2)) {
        Spacer(Modifier.weight(1f))
        if (onCancel != null) {
            AppButton(cancelText, onClick = onCancel, kind = AppButtonKind.SECONDARY)
        }
        AppButton(confirmText, onClick = onConfirm, kind = AppButtonKind.PRIMARY,
            enabled = enabled)
    }
}

/** 未使用的兼容导出，避免旧引用报错 */
val SelectPlaceholderColor: Color = Muted2
val SelectOnSurface: Color = OnPrimaryText
val SelectSurfaceDeep: Color = SurfaceDeep
