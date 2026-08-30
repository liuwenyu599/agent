package com.judicialai.desktop.features.templates

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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.AlertDialog
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Card
import androidx.compose.material.CircularProgressIndicator
import androidx.compose.material.Divider
import androidx.compose.material.Icon
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.material.TextFieldDefaults
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Star
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.platform.pickSaveFile
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.theme.EpDanger
import com.judicialai.desktop.design.theme.EpPrimary
import com.judicialai.desktop.design.theme.EpWarning
import com.judicialai.desktop.design.theme.HoverBlue
import com.judicialai.desktop.design.theme.QuickBlue
import com.judicialai.desktop.design.theme.QuickBlueBg
import com.judicialai.desktop.design.theme.QuickGreen
import com.judicialai.desktop.design.theme.QuickGreenBg
import com.judicialai.desktop.design.theme.QuickOrange
import com.judicialai.desktop.design.theme.QuickOrangeBg
import com.judicialai.desktop.design.theme.QuickPurple
import com.judicialai.desktop.design.theme.QuickPurpleBg
import com.judicialai.desktop.design.theme.QuickTeal
import com.judicialai.desktop.design.theme.QuickTealBg
import com.judicialai.desktop.design.theme.TextPrimary
import com.judicialai.desktop.design.theme.TextRegular
import com.judicialai.desktop.design.theme.TextSecondary
import kotlinx.serialization.json.JsonObject

/** 公文助手（模板中心）：1:1 还原 Web TemplatesView + TemplateView */
@Composable
fun TemplatesScreen() {
    val vm = remember { TemplatesViewModel(Repositories.templates) }
    LaunchedEffect(Unit) { vm.load() }

    val using = vm.usingTemplate
    if (using != null) {
        TemplateUseView(vm, using)
    } else {
        TemplateCenter(vm)
    }
}

/** 分类配色（对应 Web iconColor） */
private fun catColor(cat: String): Pair<Color, Color> = when {
    cat.contains("法定") || cat.contains("公文") -> QuickBlue to QuickBlueBg
    cat.contains("工作") -> QuickGreen to QuickGreenBg
    cat.contains("会议") -> QuickOrange to QuickOrangeBg
    cat.contains("信息") || cat.contains("宣传") -> QuickPurple to QuickPurpleBg
    else -> QuickTeal to QuickTealBg
}

@Composable
private fun TemplateCenter(vm: TemplatesViewModel) {
    var search by remember { mutableStateOf("") }
    var onlyMine by remember { mutableStateOf(false) }
    var selectedId by remember { mutableStateOf<String?>(null) }

    val filtered = vm.templates.filter { t ->
        (vm.filterCat == null || t["category"].str() == vm.filterCat) &&
            (search.isBlank() || t["name"].str().contains(search, true) ||
                t["description"].str().contains(search, true))
    }
    val selected = filtered.firstOrNull { it["id"].str() == selectedId }

    Column(Modifier.fillMaxSize().padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        // 页头
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("模板中心", fontSize = 20.sp, fontWeight = FontWeight.Bold,
                    color = TextPrimary)
                Text("选择合适的模板，作为智能写作和公文起草的格式参考。",
                    fontSize = 13.sp, color = TextSecondary)
            }
            if (AppState.isAdmin) {
                TextButton(onClick = { vm.initBuiltin() }) {
                    Icon(Icons.Default.Refresh, null, tint = EpPrimary,
                        modifier = Modifier.size(16.dp))
                    Text("初始化内置模板", color = EpPrimary, fontSize = 13.sp)
                }
            }
        }

        // 搜索
        OutlinedTextField(
            value = search, onValueChange = { search = it },
            placeholder = { Text("搜索模板名称或关键词，例如：请示、工作总结、会议通知…",
                fontSize = 13.sp, color = TextSecondary) },
            leadingIcon = { Icon(Icons.Default.Search, null, tint = TextSecondary) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            colors = TextFieldDefaults.outlinedTextFieldColors(
                focusedBorderColor = EpPrimary, cursorColor = EpPrimary),
        )

        // 一级分类
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            CategoryChip("全部", vm.filterCat == null) { vm.filterCat = null }
            vm.categories.forEach { c ->
                CategoryChip(c, vm.filterCat == c) { vm.filterCat = c }
            }
        }

        // 列表 + 预览
        Row(Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            // 左：模板列表
            Card(Modifier.weight(1.2f).fillMaxHeight(), shape = RoundedCornerShape(8.dp),
                elevation = 0.dp) {
                Column {
                    Text("模板列表（共 ${filtered.size} 个）",
                        fontSize = 13.sp, color = TextSecondary,
                        modifier = Modifier.padding(14.dp))
                    Divider(color = Color(0xFFF2F4F8))
                    Column(Modifier.verticalScroll(rememberScrollState())) {
                        filtered.forEach { t ->
                            val active = selectedId == t["id"].str()
                            val (fg, bg) = catColor(t["category"].str())
                            Row(
                                Modifier.fillMaxWidth()
                                    .background(if (active) HoverBlue else Color.Transparent)
                                    .clickable { selectedId = t["id"].str() }
                                    .padding(12.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(12.dp),
                            ) {
                                Box(Modifier.size(40.dp).clip(RoundedCornerShape(8.dp))
                                    .background(bg), contentAlignment = Alignment.Center) {
                                    Icon(Icons.Default.Star, null, tint = fg,
                                        modifier = Modifier.size(20.dp))
                                }
                                Column(Modifier.weight(1f)) {
                                    Row(verticalAlignment = Alignment.CenterVertically,
                                        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                        Text(t["name"].str(), fontSize = 14.sp,
                                            fontWeight = FontWeight.Medium, color = TextPrimary,
                                            maxLines = 1, overflow = TextOverflow.Ellipsis)
                                        Box(Modifier.clip(RoundedCornerShape(3.dp))
                                            .background(bg)
                                            .padding(horizontal = 6.dp, vertical = 1.dp)) {
                                            Text(t["category"].str(), fontSize = 10.sp, color = fg)
                                        }
                                    }
                                    Text(t["description"].str()
                                        .ifBlank { t["base_type"].str() + "类材料" },
                                        fontSize = 12.sp, color = TextSecondary,
                                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                                }
                                Button(onClick = { vm.startUse(t) },
                                    colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary),
                                    shape = RoundedCornerShape(6.dp),
                                    contentPadding = androidx.compose.foundation.layout.PaddingValues(
                                        horizontal = 12.dp, vertical = 4.dp)) {
                                    Text("使用模板", color = Color.White, fontSize = 12.sp)
                                }
                                if (AppState.isAdmin) {
                                    TextButton(onClick = { vm.delete(t["id"].str()) }) {
                                        Icon(Icons.Default.Delete, null, tint = EpDanger,
                                            modifier = Modifier.size(16.dp))
                                    }
                                }
                            }
                            Divider(color = Color(0xFFF2F4F8))
                        }
                        if (filtered.isEmpty()) {
                            Box(Modifier.fillMaxWidth().padding(40.dp),
                                contentAlignment = Alignment.Center) {
                                Text("没有符合条件的模板", color = TextSecondary, fontSize = 13.sp)
                            }
                        }
                    }
                }
            }

            // 右：模板预览
            Card(Modifier.weight(1f).fillMaxHeight(), shape = RoundedCornerShape(8.dp),
                elevation = 0.dp) {
                if (selected == null) {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Text("点击左侧模板查看预览", color = TextSecondary, fontSize = 13.sp)
                    }
                } else {
                    Column(Modifier.verticalScroll(rememberScrollState()).padding(20.dp)) {
                        Text("模板预览", fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
                            color = TextPrimary)
                        Spacer(Modifier.height(16.dp))
                        Row(verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            val (fg, bg) = catColor(selected["category"].str())
                            Box(Modifier.size(48.dp).clip(RoundedCornerShape(10.dp))
                                .background(bg), contentAlignment = Alignment.Center) {
                                Icon(Icons.Default.Star, null, tint = fg,
                                    modifier = Modifier.size(24.dp))
                            }
                            Column {
                                Text(selected["name"].str(), fontSize = 18.sp,
                                    fontWeight = FontWeight.Bold, color = TextPrimary)
                                Text(selected["description"].str(), fontSize = 12.sp,
                                    color = TextSecondary)
                            }
                        }
                        Spacer(Modifier.height(16.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            PreviewTag(selected["base_type"].str().ifBlank { "公文" })
                            PreviewTag(selected["category"].str())
                            PreviewTag("约 ${selected["word_count"].int().let { if (it > 0) it else 1000 }} 字")
                            PreviewTag(selected["writing_style"].str().ifBlank { "正式公文" })
                        }
                        Spacer(Modifier.height(16.dp))
                        Text("填写要素", fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                            color = TextPrimary)
                        Spacer(Modifier.height(8.dp))
                        selected["params_schema"].arr().mapNotNull { it.obj() }.forEach { f ->
                            Row(Modifier.padding(vertical = 3.dp)) {
                                Text("· ${f["label"].str()}",
                                    fontSize = 13.sp, color = TextRegular)
                                if (f["required"].str() == "true") {
                                    Text("（必填）", fontSize = 12.sp, color = EpDanger)
                                }
                            }
                        }
                        Spacer(Modifier.height(20.dp))
                        Button(onClick = { vm.startUse(selected) },
                            colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary),
                            shape = RoundedCornerShape(6.dp),
                            modifier = Modifier.fillMaxWidth()) {
                            Text("使用模板", color = Color.White, fontSize = 14.sp)
                        }
                    }
                }
            }
        }
        vm.status?.let { Text(it, fontSize = 12.sp, color = TextSecondary) }
    }
}

@Composable
private fun CategoryChip(label: String, active: Boolean, onClick: () -> Unit) {
    Box(
        Modifier.clip(RoundedCornerShape(16.dp))
            .background(if (active) EpPrimary else Color.White)
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 7.dp),
    ) {
        Text(label, fontSize = 13.sp,
            color = if (active) Color.White else TextRegular)
    }
}

@Composable
private fun PreviewTag(text: String) {
    if (text.isBlank()) return
    Box(Modifier.clip(RoundedCornerShape(4.dp)).background(HoverBlue)
        .padding(horizontal = 8.dp, vertical = 3.dp)) {
        Text(text, fontSize = 11.sp, color = EpPrimary)
    }
}

/** 模板使用视图：对应 Web TemplateView（要素填写 → 生成 → 结果导出） */
@Composable
private fun TemplateUseView(vm: TemplatesViewModel, t: JsonObject) {
    val fields = t["params_schema"].arr().mapNotNull { it.obj() }
    var values by remember { mutableStateOf(fields.associate { it["name"].str() to "" }) }

    Column(Modifier.fillMaxSize().padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { vm.cancelUse() }) {
                Icon(Icons.Default.ArrowBack, null, tint = EpPrimary,
                    modifier = Modifier.size(16.dp))
                Text("返回模板中心", color = EpPrimary)
            }
            Spacer(Modifier.weight(1f))
        }
        Row(Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            // 左：要素表单
            Card(Modifier.weight(1f).fillMaxHeight(), shape = RoundedCornerShape(8.dp),
                elevation = 0.dp) {
                Column(Modifier.verticalScroll(rememberScrollState()).padding(20.dp)) {
                    Text(t["name"].str(), fontSize = 18.sp, fontWeight = FontWeight.Bold,
                        color = TextPrimary)
                    Text(t["description"].str(), fontSize = 12.sp, color = TextSecondary)
                    Spacer(Modifier.height(16.dp))
                    fields.forEach { f ->
                        val name = f["name"].str()
                        val label = f["label"].str().ifBlank { name } +
                            if (f["required"].str() == "true") " *" else ""
                        val isArea = f["type"].str() == "textarea"
                        Text(label, fontSize = 13.sp, color = TextRegular)
                        Spacer(Modifier.height(4.dp))
                        OutlinedTextField(
                            value = values[name] ?: "",
                            onValueChange = { values = values + (name to it) },
                            placeholder = {
                                Text(f["placeholder"].str(), fontSize = 12.sp,
                                    color = TextSecondary)
                            },
                            modifier = Modifier.fillMaxWidth()
                                .then(if (isArea) Modifier.heightIn(min = 90.dp) else Modifier),
                            colors = TextFieldDefaults.outlinedTextFieldColors(
                                focusedBorderColor = EpPrimary, cursorColor = EpPrimary),
                        )
                        Spacer(Modifier.height(12.dp))
                    }
                    Button(
                        onClick = {
                            vm.generate(values.mapKeys { it.key }
                                .mapValues { it.key to it.value })
                        },
                        enabled = !vm.generating,
                        colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary),
                        modifier = Modifier.fillMaxWidth().height(44.dp),
                        shape = RoundedCornerShape(6.dp),
                    ) {
                        if (vm.generating) {
                            CircularProgressIndicator(color = Color.White, strokeWidth = 2.dp,
                                modifier = Modifier.size(16.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("生成中…", color = Color.White)
                        } else Text("生成公文", color = Color.White, fontSize = 15.sp)
                    }
                }
            }
            // 右：生成结果
            Card(Modifier.weight(1.2f).fillMaxHeight(), shape = RoundedCornerShape(8.dp),
                elevation = 0.dp) {
                Column(Modifier.padding(20.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("生成结果", fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
                            color = TextPrimary, modifier = Modifier.weight(1f))
                        if (vm.result.isNotBlank()) {
                            TextButton(onClick = {
                                val target = pickSaveFile("${t["name"].str()}.docx")
                                    ?: return@TextButton
                                vm.exportResult(t["name"].str(), target)
                            }) { Text("导出 Word", color = EpPrimary, fontSize = 13.sp) }
                        }
                    }
                    Divider(color = Color(0xFFF2F4F8))
                    Box(Modifier.weight(1f).verticalScroll(rememberScrollState())
                        .padding(vertical = 12.dp)) {
                        when {
                            vm.generating -> Text("正在生成，请稍候…", color = TextSecondary,
                                fontSize = 14.sp)
                            vm.result.isBlank() -> Text("填写左侧要素后点击「生成公文」",
                                color = TextSecondary, fontSize = 14.sp)
                            else -> Text(vm.result, fontSize = 15.sp, lineHeight = 28.sp,
                                color = TextPrimary)
                        }
                    }
                }
            }
        }
        vm.status?.let { Text(it, fontSize = 12.sp, color = EpDanger) }
    }
}

