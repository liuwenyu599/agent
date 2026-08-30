package com.judicialai.desktop.features.workflow

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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.AlertDialog
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Card
import androidx.compose.material.Divider
import androidx.compose.material.Icon
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.material.TextFieldDefaults
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Share
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
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.theme.EpDanger
import com.judicialai.desktop.design.theme.EpPrimary
import com.judicialai.desktop.design.theme.EpSuccess
import com.judicialai.desktop.design.theme.EpWarning
import com.judicialai.desktop.design.theme.HoverBlue
import com.judicialai.desktop.design.theme.QuickBlue
import com.judicialai.desktop.design.theme.QuickGreen
import com.judicialai.desktop.design.theme.QuickOrange
import com.judicialai.desktop.design.theme.QuickPurple
import com.judicialai.desktop.design.theme.QuickTeal
import com.judicialai.desktop.design.theme.TextPrimary
import com.judicialai.desktop.design.theme.TextRegular
import com.judicialai.desktop.design.theme.TextSecondary
import kotlinx.serialization.json.JsonObject

private val tplColors = listOf(QuickBlue, QuickGreen, QuickOrange, QuickPurple, QuickTeal)

/** 工作流：1:1 还原 Web WorkflowsView（页头 + 分类 chips + 模板卡片 + 我的工作流） */
@Composable
fun WorkflowScreen() {
    val vm = remember { WorkflowViewModel(Repositories.workflow) }
    LaunchedEffect(Unit) { vm.load() }

    val detail = vm.detail
    if (detail != null) {
        WorkflowDetail(vm, detail)
    } else {
        WorkflowHome(vm)
    }
}

@Composable
private fun WorkflowHome(vm: WorkflowViewModel) {
    var category by remember { mutableStateOf("all") }
    var showCreate by remember { mutableStateOf<JsonObject?>(null) }

    val categories = listOf("all") + vm.templates.map { it["category"].str() }.distinct()
        .filter { it.isNotBlank() }
    val filtered = vm.templates.filter {
        category == "all" || it["category"].str() == category
    }

    Row(Modifier.fillMaxSize().padding(20.dp),
        horizontalArrangement = Arrangement.spacedBy(20.dp)) {
        // 左主区
        Column(Modifier.weight(2f).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp)) {
            // 页头
            Card(shape = RoundedCornerShape(10.dp), elevation = 0.dp) {
                Row(Modifier.padding(20.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(44.dp).clip(RoundedCornerShape(10.dp))
                        .background(EpPrimary), contentAlignment = Alignment.Center) {
                        Icon(Icons.Default.Share, null, tint = Color.White,
                            modifier = Modifier.size(26.dp))
                    }
                    Spacer(Modifier.width(14.dp))
                    Column(Modifier.weight(1f)) {
                        Text("公共工作流", fontSize = 18.sp, fontWeight = FontWeight.Bold,
                            color = TextPrimary)
                        Text("提供常用办公流程模板，支持一键创建，智能生成各类材料",
                            fontSize = 12.sp, color = TextSecondary)
                    }
                    Button(onClick = { showCreate = filtered.firstOrNull() },
                        colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary)) {
                        Icon(Icons.Default.Add, null, tint = Color.White,
                            modifier = Modifier.size(16.dp))
                        Text("新建工作流", color = Color.White, fontSize = 13.sp)
                    }
                }
            }

            // 分类 + 模板卡片
            Card(shape = RoundedCornerShape(10.dp), elevation = 0.dp) {
                Column(Modifier.padding(20.dp)) {
                    Text("工作流分类", fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                        color = TextPrimary)
                    Spacer(Modifier.height(10.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        categories.forEach { c ->
                            val on = category == c
                            Box(Modifier.clip(RoundedCornerShape(14.dp))
                                .background(if (on) EpPrimary else Color(0xFFF2F4F8))
                                .clickable { category = c }
                                .padding(horizontal = 14.dp, vertical = 6.dp)) {
                                Text(if (c == "all") "全部" else c, fontSize = 12.sp,
                                    color = if (on) Color.White else TextRegular)
                            }
                        }
                    }
                    Spacer(Modifier.height(16.dp))
                    filtered.forEachIndexed { i, t ->
                        WfTemplateCard(t, tplColors[i % tplColors.size]) { showCreate = t }
                        Spacer(Modifier.height(10.dp))
                    }
                    if (filtered.isEmpty()) {
                        Text("暂无工作流模板", color = TextSecondary, fontSize = 13.sp)
                    }
                }
            }
        }

        // 右栏：我的工作流
        Card(Modifier.weight(1f).fillMaxHeight(), shape = RoundedCornerShape(10.dp),
            elevation = 0.dp) {
            Column(Modifier.padding(16.dp)) {
                Text("⚡ 我的工作流", fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                    color = TextPrimary)
                Spacer(Modifier.height(10.dp))
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    if (vm.instances.isEmpty()) {
                        Text("暂无工作流，从左侧模板创建", color = TextSecondary, fontSize = 12.sp)
                    }
                    vm.instances.forEach { inst ->
                        Column(
                            Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
                                .clickable { vm.open(inst["id"].str()) }
                                .padding(vertical = 10.dp, horizontal = 8.dp),
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(inst["title"].str(), fontSize = 13.sp,
                                    fontWeight = FontWeight.Medium, color = TextPrimary,
                                    modifier = Modifier.weight(1f),
                                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                                StatusTag(inst["status"].str())
                            }
                            Text(
                                "${inst["template_name"].str()} ｜ ${inst["created_at"].str()}",
                                fontSize = 11.sp, color = TextSecondary)
                        }
                        Divider(color = Color(0xFFF2F4F8))
                    }
                }
            }
        }
    }

    showCreate?.let { tpl ->
        var title by remember { mutableStateOf(tpl["name"].str()) }
        AlertDialog(
            onDismissRequest = { showCreate = null },
            title = { Text("新建工作流：${tpl["name"].str()}") },
            text = {
                OutlinedTextField(value = title, onValueChange = { title = it },
                    label = { Text("工作流标题") }, singleLine = true,
                    modifier = Modifier.fillMaxWidth())
            },
            confirmButton = {
                Button(onClick = {
                    if (title.isNotBlank()) {
                        vm.create(tpl["code"].str().ifBlank { tpl["id"].str() }, title)
                        showCreate = null
                    }
                }, colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary)) {
                    Text("创建", color = Color.White)
                }
            },
            dismissButton = { TextButton(onClick = { showCreate = null }) { Text("取消") } },
        )
    }
}

@Composable
private fun WfTemplateCard(t: JsonObject, color: Color, onUse: () -> Unit) {
    Card(shape = RoundedCornerShape(8.dp), elevation = 1.dp,
        modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Box(Modifier.size(36.dp).clip(RoundedCornerShape(8.dp)).background(color),
                    contentAlignment = Alignment.Center) {
                    Icon(Icons.Default.Share, null, tint = Color.White,
                        modifier = Modifier.size(20.dp))
                }
                Text(t["name"].str(), fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
                    color = TextPrimary, modifier = Modifier.weight(1f))
                TextButton(onClick = onUse) { Text("立即使用 →", color = EpPrimary, fontSize = 13.sp) }
            }
            Text(t["description"].str(), fontSize = 12.sp, color = TextSecondary)
            Spacer(Modifier.height(8.dp))
            t["nodes"].arr().mapNotNull { it.obj() }.take(4).forEach { n ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("· ${n["name"].str()}", fontSize = 12.sp, color = TextRegular)
                    Spacer(Modifier.width(4.dp))
                    Icon(Icons.Default.CheckCircle, null, tint = EpSuccess,
                        modifier = Modifier.size(12.dp))
                }
            }
        }
    }
}

/** 工作流详情：节点列表 + 生成/编辑内容（对应 Web WorkflowDetailView 核心） */
@Composable
private fun WorkflowDetail(vm: WorkflowViewModel, inst: JsonObject) {
    Column(Modifier.fillMaxSize().padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { vm.closeDetail() }) {
                Icon(Icons.Default.ArrowBack, null, tint = EpPrimary,
                    modifier = Modifier.size(16.dp))
                Text("返回", color = EpPrimary)
            }
            Text(inst["title"].str(), fontSize = 18.sp, fontWeight = FontWeight.Bold,
                color = TextPrimary)
            Spacer(Modifier.width(10.dp))
            StatusTag(inst["status"].str())
        }
        vm.status?.let { Text(it, fontSize = 12.sp, color = TextSecondary) }

        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            inst["nodes"].arr().mapNotNull { it.obj() }.forEach { node ->
                NodeCard(vm, node)
            }
        }
    }
}

@Composable
private fun NodeCard(vm: WorkflowViewModel, node: JsonObject) {
    var editing by remember { mutableStateOf(false) }
    var draft by remember(node["content"].str()) { mutableStateOf(node["content"].str()) }
    val generating = vm.generatingNodeId == node["id"].str()

    Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp,
        modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(node["name"].str(), fontSize = 15.sp, fontWeight = FontWeight.SemiBold,
                    color = TextPrimary)
                Spacer(Modifier.width(8.dp))
                StatusTag(node["status"].str())
                Spacer(Modifier.weight(1f))
                Button(
                    enabled = !generating,
                    onClick = { vm.generateNode(node["id"].str()) },
                    colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary),
                    shape = RoundedCornerShape(6.dp),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(
                        horizontal = 12.dp, vertical = 4.dp),
                ) {
                    Text(if (generating) "生成中…" else "AI 生成", color = Color.White,
                        fontSize = 12.sp)
                }
                Spacer(Modifier.width(8.dp))
                TextButton(onClick = { editing = !editing }) {
                    Text(if (editing) "取消编辑" else "编辑", color = EpPrimary, fontSize = 12.sp)
                }
                if (editing) {
                    TextButton(onClick = {
                        vm.saveNode(node["id"].str(), draft); editing = false
                    }) { Text("保存", color = EpSuccess, fontSize = 12.sp) }
                }
            }
            if (node["write_guide"].str().isNotBlank()) {
                Text("写作要求：${node["write_guide"].str()}", fontSize = 12.sp,
                    color = TextSecondary)
            }
            Spacer(Modifier.height(8.dp))
            if (editing) {
                OutlinedTextField(
                    value = draft, onValueChange = { draft = it },
                    modifier = Modifier.fillMaxWidth().height(200.dp),
                    colors = TextFieldDefaults.outlinedTextFieldColors(
                        focusedBorderColor = EpPrimary, cursorColor = EpPrimary),
                )
            } else {
                Text(
                    node["content"].str().ifBlank { "（尚未生成内容，点击「AI 生成」）" },
                    fontSize = 13.sp, lineHeight = 22.sp,
                    color = if (node["content"].str().isBlank()) TextSecondary else TextRegular,
                    maxLines = 8, overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun StatusTag(status: String) {
    val (text, color) = when (status) {
        "running" -> "进行中" to EpPrimary
        "draft" -> "草稿" to EpWarning
        "completed" -> "已完成" to EpSuccess
        "pending" -> "待处理" to TextSecondary
        else -> status.ifBlank { "未知" } to TextSecondary
    }
    Box(Modifier.clip(RoundedCornerShape(4.dp)).background(color.copy(alpha = 0.12f))
        .padding(horizontal = 8.dp, vertical = 2.dp)) {
        Text(text, fontSize = 11.sp, color = color)
    }
}

