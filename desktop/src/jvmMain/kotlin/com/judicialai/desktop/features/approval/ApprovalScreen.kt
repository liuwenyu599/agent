package com.judicialai.desktop.features.approval

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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Card
import androidx.compose.material.Divider
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedButton
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Tab
import androidx.compose.material.TabRow
import androidx.compose.material.TabRowDefaults
import androidx.compose.material.Text
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.design.theme.Accent
import com.judicialai.desktop.design.theme.AccentSoft
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.Line
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Ok
import com.judicialai.desktop.design.theme.OkSoft
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.PrimarySoft
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.Warn
import com.judicialai.desktop.design.theme.WarnSoft

/**
 * 待办审批（v3.0 新增一级页面）。
 *
 * 这是「公文提交后去哪看」的入口：三个视图 + 详情流转时间轴 + 同意/退回/终止。
 * 全部数据来自后端 /approvals 接口，**没有任何本地假数据**；
 * 可执行动作由后端 available_actions 下发，前端不硬编码流程判断。
 */
@Composable
fun ApprovalScreen(vm: ApprovalViewModel = remember { ApprovalViewModel() }) {
    LaunchedEffect(Unit) { vm.load() }

    Row(Modifier.fillMaxSize().background(AppBg)) {
        // 左：列表
        Column(Modifier.weight(1f).fillMaxHeight().padding(18.dp)) {
            Text("待办审批", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Ink)
            Spacer(Modifier.height(4.dp))
            Text("公文送审后在此跟踪流转进度，退回与签发均会留痕",
                fontSize = 12.5.sp, color = Muted)
            Spacer(Modifier.height(14.dp))

            val tabs = ApprovalView.values()
            val idx = tabs.indexOf(vm.currentView())
            TabRow(
                selectedTabIndex = idx.coerceAtLeast(0),
                backgroundColor = Surface,
                contentColor = Primary,
                divider = { TabRowDefaults.Divider(color = Line) },
            ) {
                tabs.forEach { v ->
                    Tab(selected = v == vm.currentView(), onClick = { vm.switch(v) }) {
                        Text(v.label, fontSize = 13.5.sp, modifier = Modifier.padding(vertical = 11.dp))
                    }
                }
            }

            Spacer(Modifier.height(12.dp))

            when (vm.viewState) {
                ApprovalLoadState.LOADING -> CenteredHint("加载中…")
                ApprovalLoadState.ERROR -> CenteredHint("暂时无法获取审批列表\n${vm.error}", vm::load)
                ApprovalLoadState.EMPTY -> CenteredHint(
                    when (vm.currentView()) {
                        ApprovalView.TODO -> "当前没有待你审批的公文"
                        ApprovalView.MINE -> "你还没有提交过公文送审"
                        ApprovalView.DONE -> "暂无已办结的公文"
                    }
                )
                ApprovalLoadState.READY -> {
                    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        vm.items.forEach { item ->
                            ApprovalRow(item, selected = item.id == vm.detailId) {
                                vm.openDetail(item.id)
                            }
                        }
                    }
                }
            }
        }

        // 右：详情
        if (vm.detailId != null) {
            Card(
                Modifier.width(400.dp).fillMaxHeight().padding(top = 18.dp, end = 18.dp, bottom = 18.dp),
                shape = RoundedCornerShape(14.dp),
                backgroundColor = Surface,
                elevation = 1.dp,
            ) {
                ApprovalDetail(vm)
            }
        }
    }
}

@Composable
private fun ApprovalRow(item: ApprovalItem, selected: Boolean, onClick: () -> Unit) {
    Card(
        Modifier.fillMaxWidth().clickable(onClick = onClick),
        shape = RoundedCornerShape(12.dp),
        backgroundColor = if (selected) PrimarySoft else Surface,
        elevation = if (selected) 2.dp else 1.dp,
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(item.title, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                    color = Ink, maxLines = 1, modifier = Modifier.weight(1f))
                StatusChip(item.status)
            }
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("当前环节：${item.stepName}", fontSize = 12.sp, color = Primary,
                    fontWeight = FontWeight.SemiBold)
                if (item.urgency == "urgent") {
                    Spacer(Modifier.width(8.dp))
                    Text("急件", fontSize = 11.sp, color = Accent,
                        modifier = Modifier.clip(RoundedCornerShape(4.dp))
                            .background(AccentSoft).padding(horizontal = 6.dp, vertical = 2.dp))
                }
            }
            Spacer(Modifier.height(6.dp))
            Row {
                Text("${item.submitter}", fontSize = 12.sp, color = Ink2)
                if (item.department.isNotBlank()) {
                    Text(" · ${item.department}", fontSize = 12.sp, color = Muted)
                }
                Spacer(Modifier.weight(1f))
                Text(item.submittedAt, fontSize = 11.5.sp, color = Muted)
            }
        }
    }
}

@Composable
private fun StatusChip(status: String) {
    val (text, fg, bg) = when (status) {
        "PENDING_DEPT", "PENDING_OFFICE", "PENDING_LEADER" -> Triple("流转中", Warn, WarnSoft)
        "APPROVED", "NUMBERED", "ISSUED" -> Triple("已签发", Ok, OkSoft)
        "ARCHIVED" -> Triple("已归档", Ok, OkSoft)
        "TERMINATED" -> Triple("已终止", Accent, AccentSoft)
        "DRAFT" -> Triple("草稿", Muted, PrimarySoft)
        else -> Triple(status, Muted, PrimarySoft)
    }
    Text(text, fontSize = 11.5.sp, color = fg,
        modifier = Modifier.clip(RoundedCornerShape(999.dp)).background(bg)
            .padding(horizontal = 9.dp, vertical = 3.dp))
}

@Composable
private fun ApprovalDetail(vm: ApprovalViewModel) {
    val d = vm.detail
    var comment by remember(vm.detailId) { mutableStateOf("") }

    Column(Modifier.fillMaxSize()) {
        // 头部
        Row(
            Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("流转详情", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Ink,
                modifier = Modifier.weight(1f))
            Text("关闭", fontSize = 12.5.sp, color = Muted,
                modifier = Modifier.clickable { vm.closeDetail() })
        }
        Divider(color = Line)

        if (d == null) {
            Box(Modifier.fillMaxSize(), Alignment.Center) {
                Text(if (vm.detailError.isBlank()) "加载中…" else vm.detailError,
                    fontSize = 12.5.sp, color = Muted)
            }
            return
        }

        Column(Modifier.fillMaxSize().padding(16.dp)) {
            Text(d.title, fontSize = 15.sp, fontWeight = FontWeight.Bold, color = Ink)
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                StatusChip(d.status)
                Spacer(Modifier.width(8.dp))
                Text(d.stepName, fontSize = 12.sp, color = Primary)
            }
            Spacer(Modifier.height(10.dp))
            InfoLine("提交人", "${d.submitter}${if (d.department.isNotBlank()) " · ${d.department}" else ""}")
            InfoLine("提交时间", d.submittedAt)
            if (d.docNumber.isNotBlank()) InfoLine("文号", d.docNumber)

            if (d.contentExcerpt.isNotBlank()) {
                Spacer(Modifier.height(10.dp))
                Text("正文摘要", fontSize = 12.sp, color = Muted)
                Spacer(Modifier.height(4.dp))
                Text(d.contentExcerpt, fontSize = 12.5.sp, color = Ink2, lineHeight = 19.sp,
                    maxLines = 6,
                    modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
                        .background(AppBg).padding(10.dp))
            }

            Spacer(Modifier.height(14.dp))
            Text("流转记录", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Ink)
            Spacer(Modifier.height(8.dp))

            Column(Modifier.weight(1f)) {
                if (vm.actions.isEmpty()) {
                    Text("暂无流转记录", fontSize = 12.sp, color = Muted)
                } else {
                    vm.actions.forEach { a ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                            Box(Modifier.size(7.dp).padding(top = 4.dp)
                                .clip(RoundedCornerShape(999.dp)).background(Primary))
                            Spacer(Modifier.width(10.dp))
                            Column(Modifier.weight(1f)) {
                                Text("${a.actorName} ${a.actionName}",
                                    fontSize = 12.5.sp, color = Ink, fontWeight = FontWeight.SemiBold)
                                if (a.fromName.isNotBlank() || a.toName.isNotBlank()) {
                                    Text("${a.fromName} → ${a.toName}",
                                        fontSize = 11.5.sp, color = Muted)
                                }
                                if (a.comment.isNotBlank()) {
                                    Text(a.comment, fontSize = 12.sp, color = Ink2)
                                }
                                Text(a.createdAt, fontSize = 11.sp, color = Muted)
                            }
                        }
                    }
                }
            }

            // 操作区
            if (vm.availableActions.isNotEmpty()) {
                Divider(color = Line)
                Spacer(Modifier.height(12.dp))
                Text("办理意见", fontSize = 12.5.sp, color = Ink2)
                Spacer(Modifier.height(6.dp))
                OutlinedTextField(
                    value = comment,
                    onValueChange = { comment = it },
                    placeholder = { Text("退回或终止需填写不少于 5 个字的意见", fontSize = 12.sp) },
                    modifier = Modifier.fillMaxWidth().height(84.dp),
                    maxLines = 3,
                    textStyle = MaterialTheme.typography.body2,
                )
                if (vm.actionError.isNotBlank()) {
                    Spacer(Modifier.height(6.dp))
                    Text(vm.actionError, fontSize = 12.sp, color = Accent)
                }
                if (vm.actionDone.isNotBlank()) {
                    Spacer(Modifier.height(6.dp))
                    Text(vm.actionDone, fontSize = 12.sp, color = Ok)
                }
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    vm.availableActions.forEach { a ->
                        val isPrimary = a.action == "approve"
                        val color = when {
                            a.action == "approve" -> Ok
                            a.action.startsWith("return") -> Warn
                            a.action == "terminate" -> Accent
                            else -> Primary
                        }
                        if (isPrimary) {
                            Button(
                                onClick = { vm.act(a, comment) },
                                enabled = !vm.acting,
                                colors = ButtonDefaults.buttonColors(backgroundColor = color),
                                shape = RoundedCornerShape(8.dp),
                            ) { Text(a.name, fontSize = 12.5.sp, color = Color.White) }
                        } else {
                            OutlinedButton(
                                onClick = { vm.act(a, comment) },
                                enabled = !vm.acting,
                                shape = RoundedCornerShape(8.dp),
                            ) { Text(a.name, fontSize = 12.5.sp, color = color) }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun InfoLine(label: String, value: String) {
    Row(Modifier.padding(vertical = 2.dp)) {
        Text("$label：", fontSize = 12.sp, color = Muted, modifier = Modifier.width(64.dp))
        Text(value, fontSize = 12.sp, color = Ink2)
    }
}

@Composable
private fun CenteredHint(text: String, onRetry: (() -> Unit)? = null) {
    Box(Modifier.fillMaxWidth().padding(vertical = 48.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(text, fontSize = 13.sp, color = Muted)
            if (onRetry != null) {
                Spacer(Modifier.height(10.dp))
                Text("重试", fontSize = 13.sp, color = Primary, fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.clickable { onRetry() })
            }
        }
    }
}
