package com.judicialai.desktop.features.admin

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
import androidx.compose.material.AlertDialog
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Card
import androidx.compose.material.Divider
import androidx.compose.material.DropdownMenu
import androidx.compose.material.DropdownMenuItem
import androidx.compose.material.OutlinedTextField
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
import com.judicialai.desktop.core.utils.bool
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.theme.EpDanger
import com.judicialai.desktop.design.theme.EpPrimary
import com.judicialai.desktop.design.theme.EpSuccess
import com.judicialai.desktop.design.theme.EpWarning
import com.judicialai.desktop.design.theme.QuickPurple
import com.judicialai.desktop.design.theme.TextPrimary
import com.judicialai.desktop.design.theme.TextRegular
import com.judicialai.desktop.design.theme.TextSecondary
import kotlinx.serialization.json.JsonObject

/** 管理后台：1:1 还原 Web AdminView.vue（数据概览/用户管理/知识库管理/文档审核/会话管理） */
@Composable
fun AdminScreen() {
    val vm = remember { AdminViewModel(Repositories.admin) }
    var tab by remember { mutableStateOf(0) }
    LaunchedEffect(Unit) { vm.loadAll() }

    Column(Modifier.fillMaxSize().padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("管理后台", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = TextPrimary)
        Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp,
            modifier = Modifier.fillMaxSize()) {
            Column {
                TabRow(selectedTabIndex = tab, backgroundColor = Color.White,
                    contentColor = EpPrimary) {
                    listOf("数据概览", "用户管理", "知识库管理", "文档审核", "会话管理")
                        .forEachIndexed { i, t ->
                            Tab(selected = tab == i, onClick = { tab = i }) {
                                Text(t, fontSize = 14.sp,
                                    modifier = Modifier.padding(vertical = 12.dp))
                            }
                        }
                }
                Box(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(16.dp)) {
                    when (tab) {
                        0 -> StatsTab(vm)
                        1 -> UsersTab(vm)
                        2 -> KbTab(vm)
                        3 -> DocsTab(vm)
                        else -> SessionsTab(vm)
                    }
                }
            }
        }
        vm.status?.let { Text(it, fontSize = 12.sp, color = TextSecondary) }
    }
}

@Composable
private fun StatsTab(vm: AdminViewModel) {
    val items = listOf(
        Triple("总用户数", vm.userCount, EpPrimary),
        Triple("文档总数", vm.docCount, EpSuccess),
        Triple("会话总数", vm.sessionCount, EpWarning),
        Triple("知识库数", vm.kbCount, QuickPurple),
    )
    Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
        items.forEach { (label, num, color) ->
            Card(Modifier.weight(1f), shape = RoundedCornerShape(8.dp), elevation = 2.dp) {
                Row(Modifier.padding(20.dp), verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    Box(Modifier.width(48.dp).height(48.dp).clip(RoundedCornerShape(8.dp))
                        .background(color.copy(alpha = 0.12f)),
                        contentAlignment = Alignment.Center) {
                        Text(label.take(1), color = color, fontSize = 20.sp,
                            fontWeight = FontWeight.Bold)
                    }
                    Column {
                        Text("$num", fontSize = 24.sp, fontWeight = FontWeight.Bold,
                            color = TextPrimary)
                        Text(label, fontSize = 13.sp, color = TextSecondary)
                    }
                }
            }
        }
    }
}

@Composable
private fun UsersTab(vm: AdminViewModel) {
    var showCreate by remember { mutableStateOf(false) }
    var editUser by remember { mutableStateOf<JsonObject?>(null) }
    var resetUser by remember { mutableStateOf<JsonObject?>(null) }

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row {
            Spacer(Modifier.weight(1f))
            Button(onClick = { showCreate = true },
                colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary)) {
                Text("＋ 新建用户", color = Color.White, fontSize = 13.sp)
            }
        }
        AdminTable(
            headers = listOf(
                "#" to 50, "用户名" to 110, "真实姓名" to 110, "邮箱" to 170,
                "部门" to 130, "角色" to 100, "状态" to 80, "注册时间" to 150, "操作" to 230),
            rows = vm.users.mapIndexed { i, u ->
                listOf(
                    "${i + 1}", u["username"].str(), u["real_name"].str(),
                    u["email"].str(), u["department"].str(),
                    roleText(u["role"].str()),
                    if (u["is_active"].bool()) "正常" else "禁用",
                    u["created_at"].str().take(10),
                    "ops",
                )
            },
        ) { idx, _ ->
            val u = vm.users[idx]
            Row {
                TextButton(onClick = { editUser = u }) { Text("编辑", color = EpPrimary, fontSize = 12.sp) }
                TextButton(onClick = { resetUser = u }) { Text("重置密码", color = EpPrimary, fontSize = 12.sp) }
                TextButton(onClick = {
                    vm.toggleUser(u["id"].str(), !u["is_active"].bool())
                }) {
                    Text(if (u["is_active"].bool()) "禁用" else "启用",
                        color = if (u["is_active"].bool()) EpDanger else EpSuccess,
                        fontSize = 12.sp)
                }
            }
        }
    }

    if (showCreate) UserDialog("新建用户", null,
        onSubmit = { name, email, pwd, real, dept, role ->
            vm.createUser(name, email, pwd, real, dept, role); showCreate = false
        }) { showCreate = false }

    editUser?.let { u ->
        UserDialog("编辑用户", u,
            onSubmit = { _, _, _, real, dept, role ->
                vm.updateUser(u["id"].str(), real, dept, role); editUser = null
            }) { editUser = null }
    }

    resetUser?.let { u ->
        var pwd by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { resetUser = null },
            title = { Text("重置密码：${u["username"].str()}") },
            text = {
                OutlinedTextField(value = pwd, onValueChange = { pwd = it },
                    label = { Text("新密码（至少6位）") }, singleLine = true,
                    modifier = Modifier.fillMaxWidth())
            },
            confirmButton = {
                Button(onClick = {
                    if (pwd.length >= 6) { vm.resetPassword(u["id"].str(), pwd); resetUser = null }
                }, colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary)) {
                    Text("确定", color = Color.White)
                }
            },
            dismissButton = { TextButton(onClick = { resetUser = null }) { Text("取消") } },
        )
    }
}

@Composable
private fun UserDialog(
    title: String, user: JsonObject?,
    onSubmit: (String, String, String, String, String, String) -> Unit,
    onDismiss: () -> Unit,
) {
    var username by remember { mutableStateOf(user?.get("username").str()) }
    var email by remember { mutableStateOf(user?.get("email").str()) }
    var password by remember { mutableStateOf("") }
    var realName by remember { mutableStateOf(user?.get("real_name").str()) }
    var department by remember { mutableStateOf(user?.get("department").str()) }
    var role by remember { mutableStateOf(user?.get("role").str().ifBlank { "user" }) }
    var roleMenu by remember { mutableStateOf(false) }
    val isEdit = user != null

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (!isEdit) {
                    OutlinedTextField(value = username, onValueChange = { username = it },
                        label = { Text("用户名") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(value = email, onValueChange = { email = it },
                        label = { Text("邮箱") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(value = password, onValueChange = { password = it },
                        label = { Text("密码") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                }
                OutlinedTextField(value = realName, onValueChange = { realName = it },
                    label = { Text("真实姓名") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(value = department, onValueChange = { department = it },
                    label = { Text("部门") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                Box {
                    OutlinedTextField(value = roleText(role), onValueChange = {},
                        label = { Text("角色") }, readOnly = true,
                        modifier = Modifier.fillMaxWidth().clickable { roleMenu = true })
                    DropdownMenu(expanded = roleMenu, onDismissRequest = { roleMenu = false }) {
                        listOf("user", "knowledge_admin", "admin", "developer").forEach { r ->
                            DropdownMenuItem(onClick = { role = r; roleMenu = false }) {
                                Text(roleText(r))
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            Button(onClick = {
                if (isEdit || (username.isNotBlank() && password.isNotBlank()))
                    onSubmit(username, email, password, realName, department, role)
            }, colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary)) {
                Text("确定", color = Color.White)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

private fun roleText(role: String) = when (role) {
    "developer" -> "系统管理员"
    "knowledge_admin" -> "知识管理员"
    "admin" -> "管理员"
    "user" -> "普通用户"
    else -> role
}

@Composable
private fun KbTab(vm: AdminViewModel) {
    AdminTable(
        headers = listOf("#" to 50, "知识库名称" to 300, "类型" to 90,
            "文档数" to 90, "创建时间" to 160, "操作" to 100),
        rows = vm.kbs.mapIndexed { i, kb ->
            listOf("${i + 1}", kb["name"].str(),
                if (kb["type"].str() == "public") "公共" else "个人",
                "${kb["doc_count"].int()}", kb["created_at"].str().take(10), "ops")
        },
    ) { idx, _ ->
        TextButton(onClick = { vm.deleteKb(vm.kbs[idx]["id"].str()) }) {
            Text("删除", color = EpDanger, fontSize = 12.sp)
        }
    }
}

@Composable
private fun DocsTab(vm: AdminViewModel) {
    var sub by remember { mutableStateOf(0) }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        TabRow(selectedTabIndex = sub, backgroundColor = Color.White, contentColor = EpPrimary) {
            listOf("待审核 (${vm.pendingDocs.size})", "已发布 (${vm.publishedDocs.size})",
                "已驳回 (${vm.rejectedDocs.size})").forEachIndexed { i, t ->
                Tab(selected = sub == i, onClick = { sub = i }) {
                    Text(t, fontSize = 13.sp, modifier = Modifier.padding(vertical = 10.dp))
                }
            }
        }
        val docs = when (sub) { 0 -> vm.pendingDocs; 1 -> vm.publishedDocs; else -> vm.rejectedDocs }
        AdminTable(
            headers = listOf("#" to 50, "文档标题" to 300, "类型" to 80,
                "所属知识库" to 140, "上传者" to 100, "时间" to 150, "操作" to 160),
            rows = docs.mapIndexed { i, d ->
                listOf("${i + 1}", d["title"].str(), d["doc_type"].str(),
                    d["kb_name"].str(), d["uploader_name"].str(),
                    (d["created_at"].str().ifBlank { d["reviewed_at"].str() })
                        .take(16).replace("T", " "), "ops")
            },
        ) { idx, _ ->
            val d = docs[idx]
            Row {
                if (sub == 0) {
                    TextButton(onClick = { vm.review(d["id"].str(), "approved") }) {
                        Text("通过", color = EpSuccess, fontSize = 12.sp)
                    }
                    TextButton(onClick = { vm.review(d["id"].str(), "rejected") }) {
                        Text("驳回", color = EpDanger, fontSize = 12.sp)
                    }
                } else if (sub == 1) {
                    TextButton(onClick = { vm.archive(d["id"].str()) }) {
                        Text("归档", color = EpDanger, fontSize = 12.sp)
                    }
                }
            }
        }
    }
}

@Composable
private fun SessionsTab(vm: AdminViewModel) {
    AdminTable(
        headers = listOf("#" to 50, "会话标题" to 340, "用户" to 120,
            "消息数" to 90, "创建时间" to 160, "操作" to 100),
        rows = vm.sessions.mapIndexed { i, s ->
            listOf("${i + 1}", s["title"].str(), s["user_name"].str(),
                "${s["message_count"].int()}",
                s["created_at"].str().take(16).replace("T", " "), "ops")
        },
    ) { idx, _ ->
        TextButton(onClick = { vm.deleteSession(vm.sessions[idx]["id"].str()) }) {
            Text("删除", color = EpDanger, fontSize = 12.sp)
        }
    }
}

/** 通用表格：表头灰底 + 行分隔线 + 操作列插槽 */
@Composable
private fun AdminTable(
    headers: List<Pair<String, Int>>,
    rows: List<List<String>>,
    opsCell: @Composable (rowIndex: Int, row: List<String>) -> Unit,
) {
    Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp,
        modifier = Modifier.fillMaxWidth()) {
        Column {
            Row(Modifier.fillMaxWidth().background(Color(0xFFFAFAFA))
                .padding(horizontal = 16.dp, vertical = 10.dp)) {
                headers.forEach { (h, w) ->
                    Text(h, Modifier.width(w.dp), fontSize = 12.sp, color = TextSecondary)
                }
            }
            if (rows.isEmpty()) {
                Box(Modifier.fillMaxWidth().padding(32.dp),
                    contentAlignment = Alignment.Center) {
                    Text("暂无数据", color = TextSecondary, fontSize = 13.sp)
                }
            }
            rows.forEachIndexed { i, row ->
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    row.forEachIndexed { j, cell ->
                        val w = headers[j].second
                        if (cell == "ops") {
                            Box(Modifier.width(w.dp)) { opsCell(i, row) }
                        } else {
                            Text(cell, Modifier.width(w.dp), fontSize = 13.sp,
                                color = TextRegular, maxLines = 1,
                                overflow = TextOverflow.Ellipsis)
                        }
                    }
                }
                Divider(color = Color(0xFFF2F4F8))
            }
        }
    }
}

