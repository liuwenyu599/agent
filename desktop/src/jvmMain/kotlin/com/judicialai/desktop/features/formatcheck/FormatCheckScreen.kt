package com.judicialai.desktop.features.formatcheck

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Card
import androidx.compose.material.Checkbox
import androidx.compose.material.CheckboxDefaults
import androidx.compose.material.Divider
import androidx.compose.material.OutlinedButton
import androidx.compose.material.Tab
import androidx.compose.material.TabRow
import androidx.compose.material.Text
import androidx.compose.material.TextButton
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
import com.judicialai.desktop.core.platform.pickFiles
import com.judicialai.desktop.core.platform.pickSaveFile
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.theme.EpDanger
import com.judicialai.desktop.design.theme.EpPrimary
import com.judicialai.desktop.design.theme.EpSuccess
import com.judicialai.desktop.design.theme.EpWarning
import com.judicialai.desktop.design.theme.HoverBlue
import com.judicialai.desktop.design.theme.TextPrimary
import com.judicialai.desktop.design.theme.TextRegular
import com.judicialai.desktop.design.theme.TextSecondary

/** 格式校验：1:1 还原 Web FormatCheckView（统计卡 + 问题表 + 历史记录） */
@Composable
fun FormatCheckScreen() {
    val vm = remember { FormatCheckViewModel(Repositories.formatCheck) }
    var tab by remember { mutableStateOf(0) }

    LaunchedEffect(Unit) { vm.loadRecords() }

    Column(Modifier.fillMaxSize().padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        // 页头
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("公文格式校验", fontSize = 20.sp, fontWeight = FontWeight.Bold,
                    color = TextPrimary)
                Text("上传 Word 文档，依据 GB/T 9704 规则与 AI 辅助逐条检查格式问题",
                    fontSize = 13.sp, color = TextSecondary)
            }
            Checkbox(checked = vm.useAi, onCheckedChange = { vm.useAi = it },
                colors = CheckboxDefaults.colors(checkedColor = EpPrimary))
            Text("AI 辅助判断", fontSize = 13.sp, color = TextRegular)
            Spacer(Modifier.width(16.dp))
            Button(
                enabled = !vm.busy,
                onClick = {
                    pickFiles("选择 docx 文档").firstOrNull()?.let {
                        vm.check(it); tab = 0
                    }
                },
                colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary),
                shape = RoundedCornerShape(6.dp),
            ) { Text(if (vm.busy) "校验中…" else "上传文档校验", color = Color.White) }
        }

        vm.status?.let {
            Text(it, fontSize = 12.sp,
                color = if (it.contains("完成") || it.contains("已保存")) EpSuccess else EpDanger)
        }

        // 统计卡（当前选中记录）
        val cur = vm.current
        if (cur != null) {
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                StatCard("问题总数", cur["issue_count"].int(), EpDanger, Modifier.weight(1f))
                StatCard("规则问题", cur["rule_issue_count"].int(), EpWarning, Modifier.weight(1f))
                StatCard("AI 问题", cur["ai_issue_count"].int(), EpPrimary, Modifier.weight(1f))
                StatCard("已选修正", vm.accepted.size, EpSuccess, Modifier.weight(1f))
            }
        }

        TabRow(selectedTabIndex = tab, backgroundColor = Color.Transparent,
            contentColor = EpPrimary) {
            Tab(selected = tab == 0, onClick = { tab = 0 }) {
                Text("校验结果", fontSize = 14.sp, modifier = Modifier.padding(vertical = 10.dp))
            }
            Tab(selected = tab == 1, onClick = { tab = 1 }) {
                Text("历史记录", fontSize = 14.sp, modifier = Modifier.padding(vertical = 10.dp))
            }
        }

        when (tab) {
            0 -> ResultPanel(vm, Modifier.weight(1f))
            else -> HistoryPanel(vm, Modifier.weight(1f)) { tab = 0 }
        }
    }
}

@Composable
private fun StatCard(label: String, value: Int, color: Color, modifier: Modifier = Modifier) {
    Card(modifier, shape = RoundedCornerShape(8.dp), elevation = 0.dp) {
        Column(Modifier.fillMaxWidth().padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally) {
            Text("$value", fontSize = 26.sp, fontWeight = FontWeight.Bold, color = color)
            Spacer(Modifier.height(6.dp))
            Text(label, fontSize = 13.sp, color = TextSecondary)
        }
    }
}

/** 校验结果：问题表（element/location/current/expected/建议/严重程度/来源 + 勾选） */
@Composable
private fun ResultPanel(vm: FormatCheckViewModel, modifier: Modifier = Modifier) {
    Column(modifier) {
        Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp,
            modifier = Modifier.weight(1f).fillMaxWidth()) {
            Column {
                Row(Modifier.fillMaxWidth().background(Color(0xFFFAFAFA))
                    .padding(horizontal = 16.dp, vertical = 10.dp)) {
                    Text("修正", Modifier.width(50.dp), fontSize = 12.sp, color = TextSecondary)
                    Text("要素", Modifier.width(110.dp), fontSize = 12.sp, color = TextSecondary)
                    Text("位置", Modifier.width(130.dp), fontSize = 12.sp, color = TextSecondary)
                    Text("当前", Modifier.weight(1f), fontSize = 12.sp, color = TextSecondary)
                    Text("要求/建议", Modifier.weight(1.2f), fontSize = 12.sp, color = TextSecondary)
                    Text("程度", Modifier.width(70.dp), fontSize = 12.sp, color = TextSecondary)
                    Text("来源", Modifier.width(60.dp), fontSize = 12.sp, color = TextSecondary)
                }
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    if (vm.issues.isEmpty()) {
                        Box(Modifier.fillMaxWidth().padding(48.dp),
                            contentAlignment = Alignment.Center) {
                            Text(
                                if (vm.current == null) "请先上传文档进行校验"
                                else "未发现问题，格式规范",
                                color = TextSecondary, fontSize = 13.sp)
                        }
                    }
                    vm.issues.forEachIndexed { idx, iss ->
                        val sev = iss["severity"].str()
                        Row(
                            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Checkbox(
                                checked = idx in vm.accepted,
                                onCheckedChange = { c ->
                                    vm.accepted =
                                        if (c) vm.accepted + idx else vm.accepted - idx
                                },
                                colors = CheckboxDefaults.colors(checkedColor = EpPrimary),
                                modifier = Modifier.width(50.dp),
                            )
                            Text(iss["element"].str().ifBlank { iss["rule_name"].str() },
                                Modifier.width(110.dp), fontSize = 13.sp, color = TextPrimary,
                                maxLines = 2, overflow = TextOverflow.Ellipsis)
                            Text(iss["location"].str(), Modifier.width(130.dp),
                                fontSize = 12.sp, color = TextRegular,
                                maxLines = 2, overflow = TextOverflow.Ellipsis)
                            Text(iss["current"].str().ifBlank { iss["message"].str() },
                                Modifier.weight(1f), fontSize = 12.sp, color = TextRegular,
                                maxLines = 3, overflow = TextOverflow.Ellipsis)
                            Text(
                                iss["expected"].str().ifBlank { iss["suggestion"].str() },
                                Modifier.weight(1.2f), fontSize = 12.sp, color = TextRegular,
                                maxLines = 3, overflow = TextOverflow.Ellipsis)
                            Box(Modifier.width(70.dp)) {
                                SevTag(
                                    when (sev) {
                                        "error" -> "严重"; "warning" -> "警告"; else -> "提示"
                                    },
                                    when (sev) {
                                        "error" -> EpDanger; "warning" -> EpWarning
                                        else -> EpPrimary
                                    },
                                )
                            }
                            Box(Modifier.width(60.dp)) {
                                SevTag(
                                    if (iss["source"].str() == "ai") "AI" else "规则",
                                    if (iss["source"].str() == "ai") EpPrimary else EpSuccess,
                                )
                            }
                        }
                        Divider(color = Color(0xFFF2F4F8))
                    }
                }
            }
        }

        if (vm.current != null && vm.issues.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("已选 ${vm.accepted.size} / ${vm.issues.size} 项", fontSize = 12.sp,
                    color = TextSecondary, modifier = Modifier.weight(1f))
                OutlinedButton(onClick = { vm.accepted = vm.issues.indices.toSet() }) {
                    Text("全选", fontSize = 13.sp)
                }
                OutlinedButton(onClick = { vm.accepted = emptySet() }) {
                    Text("全不选", fontSize = 13.sp)
                }
                Button(
                    enabled = !vm.busy && vm.accepted.isNotEmpty(),
                    onClick = { pickSaveFile("修正稿.docx")?.let { vm.fix(it) } },
                    colors = ButtonDefaults.buttonColors(backgroundColor = EpSuccess),
                ) { Text("导出修正稿", color = Color.White) }
            }
        }
    }
}

/** 历史记录 */
@Composable
private fun HistoryPanel(
    vm: FormatCheckViewModel, modifier: Modifier = Modifier, onOpen: () -> Unit,
) {
    Card(modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), elevation = 0.dp) {
        Column {
            Row(Modifier.fillMaxWidth().background(Color(0xFFFAFAFA))
                .padding(horizontal = 16.dp, vertical = 10.dp)) {
                Text("文件名", Modifier.weight(2f), fontSize = 12.sp, color = TextSecondary)
                Text("类型", Modifier.width(80.dp), fontSize = 12.sp, color = TextSecondary)
                Text("问题数", Modifier.width(80.dp), fontSize = 12.sp, color = TextSecondary)
                Text("时间", Modifier.width(160.dp), fontSize = 12.sp, color = TextSecondary)
                Text("操作", Modifier.width(90.dp), fontSize = 12.sp, color = TextSecondary)
            }
            Column(Modifier.verticalScroll(rememberScrollState())) {
                if (vm.records.isEmpty()) {
                    Box(Modifier.fillMaxWidth().padding(40.dp),
                        contentAlignment = Alignment.Center) {
                        Text("暂无校验记录", color = TextSecondary, fontSize = 13.sp)
                    }
                }
                vm.records.forEach { rec ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clickable { vm.openRecord(rec); onOpen() }
                            .padding(horizontal = 16.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(rec["filename"].str(), Modifier.weight(2f), fontSize = 13.sp,
                            color = TextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(rec["file_type"].str(), Modifier.width(80.dp), fontSize = 12.sp,
                            color = TextRegular)
                        Text("${rec["issue_count"].int()}", Modifier.width(80.dp),
                            fontSize = 13.sp, color = EpWarning)
                        Text(rec["created_at"].str().take(16).replace("T", " "),
                            Modifier.width(160.dp), fontSize = 12.sp, color = TextRegular)
                        TextButton(onClick = { vm.openRecord(rec); onOpen() },
                            modifier = Modifier.width(90.dp)) {
                            Text("查看", color = EpPrimary, fontSize = 13.sp)
                        }
                    }
                    Divider(color = Color(0xFFF2F4F8))
                }
            }
        }
    }
}

@Composable
private fun SevTag(text: String, color: Color) {
    Box(Modifier.clip(RoundedCornerShape(4.dp)).background(color.copy(alpha = 0.12f))
        .padding(horizontal = 8.dp, vertical = 2.dp)) {
        Text(text, fontSize = 11.sp, color = color)
    }
}

