package com.judicialai.desktop.features.admin

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsHoveredAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
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
import androidx.compose.material.Icon
import androidx.compose.material.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Group
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.bool
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import com.judicialai.desktop.data.Repositories
import com.judicialai.desktop.design.components.AppButton
import com.judicialai.desktop.design.components.AppCardRaised
import com.judicialai.desktop.design.components.AppDialog
import com.judicialai.desktop.design.components.AppSegmentedTabs
import com.judicialai.desktop.design.components.AppSelect
import com.judicialai.desktop.design.components.AppTextField
import com.judicialai.desktop.design.components.Eyebrow
import com.judicialai.desktop.design.components.FieldError
import com.judicialai.desktop.design.components.SelectOption
import com.judicialai.desktop.design.components.TagChip
import com.judicialai.desktop.design.theme.AiSoft
import com.judicialai.desktop.design.theme.AppBg
import com.judicialai.desktop.design.theme.Danger
import com.judicialai.desktop.design.theme.DangerSoft
import com.judicialai.desktop.design.theme.Dimens
import com.judicialai.desktop.design.theme.Ink
import com.judicialai.desktop.design.theme.Ink2
import com.judicialai.desktop.design.theme.LineSubtle
import com.judicialai.desktop.design.theme.Muted
import com.judicialai.desktop.design.theme.Muted2
import com.judicialai.desktop.design.theme.Ok
import com.judicialai.desktop.design.theme.OkSoft
import com.judicialai.desktop.design.theme.Primary
import com.judicialai.desktop.design.theme.Surface
import com.judicialai.desktop.design.theme.SurfaceTonal
import com.judicialai.desktop.design.theme.SurfaceDeep
import com.judicialai.desktop.design.theme.Warn
import kotlinx.serialization.json.JsonObject

/** 管理后台：数据概览 / 用户管理 / 知识库管理 / 文档审核 */
@Composable
fun AdminScreen() {
    val vm = remember { AdminViewModel(Repositories.admin) }
    var tab by remember { mutableStateOf(AppState.adminTab) }
    LaunchedEffect(Unit) { vm.loadAll() }
    LaunchedEffect(AppState.adminTab) { tab = AppState.adminTab }

    Column(
        Modifier.fillMaxSize().background(AppBg).padding(Dimens.space6),
        verticalArrangement = Arrangement.spacedBy(Dimens.space5),
    ) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Bottom) {
            Column(Modifier.weight(1f)) {
                Eyebrow("管理能力")
                Spacer(Modifier.height(Dimens.space1))
                Text("管理后台", fontSize = 22.sp, fontWeight = FontWeight.SemiBold, color = Ink)
            }
        }
        AppSegmentedTabs(
            tabs = listOf("数据概览", "用户管理", "知识库管理", "文档审核"),
            selectedIndex = tab.coerceIn(0, 3),
            onSelect = { tab = it },
        )
        Box(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState())) {
            when (tab.coerceIn(0, 3)) {
                0 -> StatsTab(vm)
                1 -> UsersTab(vm)
                2 -> KbTab(vm)
                else -> DocsTab(vm)
            }
        }
        vm.status?.let {
            com.judicialai.desktop.design.components.InlineNotice(
                text = it, container = AiSoft,
                content = com.judicialai.desktop.design.theme.AiInk,
            )
        }
    }
}

@Composable
private fun StatsTab(vm: AdminViewModel) {
    val items = listOf(
        "总用户数" to (vm.userCount to Primary),
        "文档总数" to (vm.docCount to Ok),
        "会话总数" to (vm.sessionCount to Warn),
        "知识库数" to (vm.kbCount to com.judicialai.desktop.design.theme.Purple),
    )
    Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space4)) {
        items.forEach { (label, pair) ->
            val (num, color) = pair
            AppCardRaised(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        Modifier.size(46.dp).clip(RoundedCornerShape(Dimens.radiusMd))
                            .background(color.copy(alpha = 0.10f)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(label.take(1), color = color, fontSize = 18.sp,
                            fontWeight = FontWeight.Bold)
                    }
                    Spacer(Modifier.width(Dimens.space3))
                    Column {
                        Text("$num", fontSize = 26.sp, fontWeight = FontWeight.Bold, color = Ink)
                        Text(label, fontSize = 12.5.sp, color = Muted)
                    }
                }
            }
        }
    }
}

/** 弹出系统文件选择器选择 .xlsx / .csv，选中后交给 ViewModel 上传导入 */
private fun pickUserImportFile(vm: AdminViewModel) {
    val dialog = java.awt.FileDialog(
        null as java.awt.Frame?, "选择用户文件（.xlsx / .csv）", java.awt.FileDialog.LOAD)
    dialog.setFilenameFilter { _, name ->
        val n = name.lowercase()
        n.endsWith(".xlsx") || n.endsWith(".csv")
    }
    dialog.isVisible = true
    val dir = dialog.directory
    val file = dialog.file
    if (dir != null && file != null) {
        vm.importUsers(java.io.File(dir, file))
    }
}

@Composable
private fun UsersTab(vm: AdminViewModel) {
    var showCreate by remember { mutableStateOf(false) }
    var editUser by remember { mutableStateOf<JsonObject?>(null) }
    var resetUser by remember { mutableStateOf<JsonObject?>(null) }
    var disableUser by remember { mutableStateOf<JsonObject?>(null) }

    Column(verticalArrangement = Arrangement.spacedBy(Dimens.space4)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Eyebrow("账号、所属科室与角色", Modifier.weight(1f))
            AppButton(
                if (vm.importBusy) "导入中…" else "批量导入",
                onClick = { pickUserImportFile(vm) },
                enabled = !vm.importBusy,
                kind = com.judicialai.desktop.design.components.AppButtonKind.SECONDARY,
                size = com.judicialai.desktop.design.components.AppButtonSize.SM)
            Spacer(Modifier.width(Dimens.space2))
            AppButton("＋ 新建用户", onClick = { showCreate = true },
                icon = Icons.Default.Add, size = com.judicialai.desktop.design.components.AppButtonSize.SM)
        }
        Text(
            "批量导入支持 .xlsx / .csv，表头：用户名、邮箱、姓名、科室代码、角色（普通用户/科室管理员）、初始密码；" +
                "初始密码缺省 123456，导入的用户首次登录需修改密码。",
            fontSize = 12.sp, color = Muted,
        )
        AdminTable(
            headers = listOf(
                "#" to 46, "用户名" to 110, "真实姓名" to 100, "邮箱" to 180,
                "所属科室" to 150, "角色" to 110, "状态" to 80, "注册时间" to 110, "操作" to 240),
            rows = vm.users.mapIndexed { i, u ->
                listOf(
                    "${i + 1}", u["username"].str(), u["real_name"].str(),
                    u["email"].str(),
                    vm.deptLabel(u["department_code"].str()).ifBlank { u["department"].str() },
                    vm.roleLabel(u["role"].str()),
                    if (u["is_active"].bool()) "正常" else "禁用",
                    u["created_at"].str().take(10),
                    "ops",
                )
            },
        ) { idx, _ ->
            val u = vm.users[idx]
            Row(horizontalArrangement = Arrangement.spacedBy(Dimens.space1)) {
                com.judicialai.desktop.design.components.AppLinkButton("编辑",
                    onClick = { editUser = u })
                com.judicialai.desktop.design.components.AppLinkButton("重置密码",
                    onClick = { resetUser = u })
                if (u["username"].str() == AppState.username) {
                    Text("当前账号", fontSize = 11.5.sp, color = Muted2)
                } else {
                    com.judicialai.desktop.design.components.AppLinkButton(
                        if (u["is_active"].bool()) "禁用" else "启用",
                        onClick = {
                            if (u["is_active"].bool()) disableUser = u
                            else vm.toggleUser(u["id"].str(), true)
                        },
                        color = if (u["is_active"].bool()) Danger else Ok,
                    )
                }
            }
        }
    }

    if (showCreate) {
        UserDialog("新建用户", "所属科室与角色只能从系统提供的选项中选择", null, vm,
            onSubmit = { name, email, pwd, real, deptCode, role ->
                vm.createUser(name, email, pwd, real, deptCode, role); showCreate = false
            }) { showCreate = false }
    }

    editUser?.let { u ->
        UserDialog("编辑用户", "修改后立即生效", u, vm,
            onSubmit = { _, _, _, real, deptCode, role ->
                vm.updateUser(u["id"].str(), real, deptCode, role); editUser = null
            }) { editUser = null }
    }

    disableUser?.let { u ->
        AppDialog(
            onDismissRequest = { disableUser = null },
            title = "禁用用户",
            subtitle = "禁用后该账号将无法继续登录或使用业务功能，已有业务数据不会删除。",
            width = 460.dp,
            actions = {
                AppButton("取消", onClick = { disableUser = null },
                    kind = com.judicialai.desktop.design.components.AppButtonKind.SECONDARY)
                Spacer(Modifier.width(Dimens.space2))
                AppButton("确认禁用", onClick = {
                    vm.toggleUser(u["id"].str(), false)
                    disableUser = null
                }, kind = com.judicialai.desktop.design.components.AppButtonKind.DANGER)
            },
        ) {
            Text("用户：${u["username"].str()} · ${u["real_name"].str().ifBlank { "未填写姓名" }}",
                fontSize = 13.sp, color = Ink2)
        }
    }

    resetUser?.let { u ->
        var pwd by remember { mutableStateOf("") }
        AppDialog(
            onDismissRequest = { resetUser = null },
            title = "重置密码",
            subtitle = "用户：${u["username"].str()}，重置后该用户下次登录需修改密码",
            width = 460.dp,
            actions = {
                AppButton("取消", onClick = { resetUser = null },
                    kind = com.judicialai.desktop.design.components.AppButtonKind.SECONDARY)
                Spacer(Modifier.width(Dimens.space2))
                AppButton("确定重置", onClick = {
                    if (pwd.length >= 6) {
                        vm.resetPassword(u["id"].str(), pwd); resetUser = null
                    }
                }, enabled = pwd.length >= 6)
            },
        ) {
            AppTextField(pwd, { pwd = it }, label = "新密码", placeholder = "初始密码可用 123456",
                hint = if (pwd.isNotBlank() && pwd.length < 6) "密码至少 6 位" else null,
                error = pwd.isNotBlank() && pwd.length < 6)
        }
    }

    // 批量导入结果：逐行成功/失败明细
    vm.importResult?.let { res ->
        val rows = res["results"].arr().mapNotNull { it.obj() }
        AppDialog(
            onDismissRequest = { vm.clearImportResult() },
            title = "批量导入结果",
            subtitle = "共 ${res["total"].int()} 行：成功 ${res["succeeded"].int()}，" +
                "失败 ${res["failed"].int()}。初始密码默认为 123456，用户首次登录需修改密码。",
            width = 560.dp,
            actions = {
                AppButton("知道了", onClick = { vm.clearImportResult() })
            },
        ) {
            Column(
                Modifier.fillMaxWidth().heightIn(max = 360.dp)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                rows.forEach { row ->
                    val ok = row["ok"].bool()
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("第${row["row"].int()}行", fontSize = 12.sp, color = Muted,
                            modifier = Modifier.width(56.dp))
                        Text(row["username"].str(), fontSize = 12.5.sp, color = Ink2,
                            modifier = Modifier.width(110.dp),
                            maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(row["message"].str(), fontSize = 12.5.sp,
                            color = if (ok) Ok else Danger)
                    }
                }
            }
        }
    }
}

/**
 * 新建 / 编辑用户
 *
 * 所属科室与角色均为 [AppSelect]：整块区域可点击、右侧有展开箭头、
 * 展开后显示完整选项并标记当前选中项、禁止自由输入。
 */
@Composable
private fun UserDialog(
    title: String,
    subtitle: String,
    user: JsonObject?,
    vm: AdminViewModel,
    onSubmit: (String, String, String, String, String, String) -> Unit,
    onDismiss: () -> Unit,
) {
    var username by remember { mutableStateOf(user?.get("username").str()) }
    var email by remember { mutableStateOf(user?.get("email").str()) }
    var password by remember { mutableStateOf("") }
    var realName by remember { mutableStateOf(user?.get("real_name").str()) }
    var departmentCode by remember { mutableStateOf(user?.get("department_code").str()) }
    val roleOptions = vm.roleOptions(AppState.role)
    var role by remember {
        mutableStateOf(
            user?.get("role").str().ifBlank { "user" }.let { r ->
                r.takeIf { v -> roleOptions.any { it.first == v } } ?: (roleOptions.firstOrNull()?.first ?: "user")
            }
        )
    }
    var error by remember { mutableStateOf<String?>(null) }
    val isEdit = user != null

    val deptOptions = vm.departments.map { d ->
        val name = d["name"].str()
        val short = d["short_name"].str()
        SelectOption(
            value = d["code"].str(),
            text = name,
            desc = if (short.isNotBlank() && short != name) short else d["type"].str(),
        )
    }
    val roleSelectOptions = roleOptions.map { (v, l) -> SelectOption(v, l, roleRoleDesc(v)) }

    AppDialog(
        onDismissRequest = onDismiss,
        title = title,
        subtitle = subtitle,
        icon = Icons.Default.Group,
        width = 560.dp,
        actions = {
            AppButton("取消", onClick = onDismiss,
                kind = com.judicialai.desktop.design.components.AppButtonKind.SECONDARY)
            Spacer(Modifier.width(Dimens.space2))
            AppButton(if (isEdit) "保存修改" else "创建用户", onClick = {
                error = when {
                    departmentCode.isBlank() -> "请选择所属科室"
                    role.isBlank() -> "请选择角色"
                    !isEdit && username.isBlank() -> "请填写用户名"
                    !isEdit && password.isBlank() -> "请填写密码"
                    !isEdit && email.isBlank() -> "请填写邮箱"
                    else -> {
                        onSubmit(username, email, password, realName, departmentCode, role)
                        null
                    }
                }
            })
        },
    ) {
        if (!isEdit) {
            AppTextField(username, { username = it; error = null }, label = "用户名",
                placeholder = "登录账号")
            AppTextField(email, { email = it; error = null }, label = "邮箱",
                placeholder = "name@example.com")
            AppTextField(password, { password = it; error = null }, label = "密码",
                placeholder = "初始密码可用 123456，用户首次登录需改密")
        }
        AppTextField(realName, { realName = it }, label = "真实姓名", placeholder = "选填")

        AppSelect(
            label = "所属科室",
            value = departmentCode,
            options = deptOptions,
            onSelect = { departmentCode = it; error = null },
            placeholder = "请选择所属科室",
            error = error == "请选择所属科室",
            leadingIcon = Icons.Default.Group,
            hint = if (deptOptions.isEmpty()) "科室列表加载中，请稍候" else "由系统科室字典提供，不可自由输入",
        )

        AppSelect(
            label = "角色",
            value = role,
            options = roleSelectOptions,
            onSelect = { role = it; error = null },
            placeholder = "请选择角色",
            enabled = roleSelectOptions.isNotEmpty(),
            error = error == "请选择角色",
            leadingIcon = Icons.Default.AutoAwesome,
            hint = if (roleSelectOptions.isEmpty()) "当前账号无角色分配权限"
            else "可分配角色与后端权限口径一致",
        )

        error?.let { FieldError(it) }
    }
}

private fun roleRoleDesc(role: String): String = when (role) {
    "developer" -> "可管理全部科室与系统配置"
    "knowledge_admin" -> "可维护本科室知识、模板与智能助手配置"
    else -> "使用本科室能力完成日常办公"
}

@Composable
private fun KbTab(vm: AdminViewModel) {
    var pendingDelete by remember { mutableStateOf<JsonObject?>(null) }
    AdminTable(
        headers = listOf("#" to 46, "知识库名称" to 320, "类型" to 90,
            "文档数" to 90, "创建时间" to 140, "操作" to 120),
        rows = vm.kbs.mapIndexed { i, kb ->
            listOf("${i + 1}", kb["name"].str(),
                when {
                    kb["department_code"].str().isNotBlank() -> "科室"
                    kb["type"].str() == "public" -> "公共"
                    else -> "个人"
                },
                "${kb["doc_count"].int()}", kb["created_at"].str().take(10), "ops")
        },
    ) { idx, _ ->
        com.judicialai.desktop.design.components.AppLinkButton("删除",
            onClick = { pendingDelete = vm.kbs[idx] }, color = Danger)
    }

    pendingDelete?.let { kb ->
        AppDialog(
            onDismissRequest = { pendingDelete = null },
            title = "删除知识库",
            subtitle = "这是管理后台的破坏性操作，删除后知识检索与关联文档会受到影响。",
            width = 480.dp,
            actions = {
                AppButton("取消", onClick = { pendingDelete = null },
                    kind = com.judicialai.desktop.design.components.AppButtonKind.SECONDARY)
                Spacer(Modifier.width(Dimens.space2))
                AppButton("确认删除", onClick = {
                    vm.deleteKb(kb["id"].str())
                    pendingDelete = null
                }, kind = com.judicialai.desktop.design.components.AppButtonKind.DANGER)
            },
        ) {
            Text("知识库：${kb["name"].str().ifBlank { "未命名知识库" }} · ${kb["doc_count"].int()} 篇文档",
                fontSize = 13.sp, color = Ink2)
        }
    }
}

@Composable
private fun DocsTab(vm: AdminViewModel) {
    var sub by remember { mutableStateOf(0) }
    var pendingReview by remember { mutableStateOf<Pair<JsonObject, String>?>(null) }
    var pendingArchive by remember { mutableStateOf<JsonObject?>(null) }

    Column(verticalArrangement = Arrangement.spacedBy(Dimens.space4)) {
        AppSegmentedTabs(
            tabs = listOf("待审核 (${vm.pendingDocs.size})", "已发布 (${vm.publishedDocs.size})",
                "已驳回 (${vm.rejectedDocs.size})"),
            selectedIndex = sub,
            onSelect = { sub = it },
        )
        val docs = when (sub) { 0 -> vm.pendingDocs; 1 -> vm.publishedDocs; else -> vm.rejectedDocs }
        AdminTable(
            headers = listOf("#" to 46, "文档标题" to 320, "类型" to 80,
                "所属知识库" to 150, "上传者" to 110, "时间" to 140, "操作" to 170),
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
                    com.judicialai.desktop.design.components.AppLinkButton("通过",
                        onClick = { pendingReview = d to "approved" }, color = Ok)
                    com.judicialai.desktop.design.components.AppLinkButton("驳回",
                        onClick = { pendingReview = d to "rejected" }, color = Danger)
                } else if (sub == 1) {
                    com.judicialai.desktop.design.components.AppLinkButton("归档",
                        onClick = { pendingArchive = d }, color = Danger)
                }
            }
        }
    }

    pendingReview?.let { (doc, action) ->
        var comment by remember(pendingReview) {
            mutableStateOf(if (action == "approved") "审核通过" else "")
        }
        val rejected = action == "rejected"
        AppDialog(
            onDismissRequest = { pendingReview = null },
            title = if (rejected) "驳回文档" else "通过文档",
            subtitle = if (rejected)
                "请填写明确驳回原因，提交后将作为审核记录保留。"
            else "确认该文档符合发布要求；可补充审核意见。",
            width = 520.dp,
            actions = {
                AppButton("取消", onClick = { pendingReview = null },
                    kind = com.judicialai.desktop.design.components.AppButtonKind.SECONDARY)
                Spacer(Modifier.width(Dimens.space2))
                AppButton(if (rejected) "确认驳回" else "确认通过", onClick = {
                    vm.review(doc["id"].str(), action,
                        comment.ifBlank { if (rejected) "" else "审核通过" })
                    pendingReview = null
                }, enabled = !rejected || comment.isNotBlank(),
                    kind = if (rejected)
                        com.judicialai.desktop.design.components.AppButtonKind.DANGER
                    else com.judicialai.desktop.design.components.AppButtonKind.PRIMARY)
            },
        ) {
            Text(doc["title"].str().ifBlank { "未命名文档" }, fontSize = 13.sp, color = Ink)
            AppTextField(
                value = comment,
                onValueChange = { comment = it },
                label = "审核意见",
                placeholder = if (rejected) "请写明不符合要求的具体原因" else "可补充审核意见",
                singleLine = false,
                minLines = 3,
            )
        }
    }

    pendingArchive?.let { doc ->
        AppDialog(
            onDismissRequest = { pendingArchive = null },
            title = "归档已发布文档",
            subtitle = "归档后文档将退出当前发布列表和检索范围，请确认该内容已不再有效。",
            width = 480.dp,
            actions = {
                AppButton("取消", onClick = { pendingArchive = null },
                    kind = com.judicialai.desktop.design.components.AppButtonKind.SECONDARY)
                Spacer(Modifier.width(Dimens.space2))
                AppButton("确认归档", onClick = {
                    vm.archive(doc["id"].str())
                    pendingArchive = null
                }, kind = com.judicialai.desktop.design.components.AppButtonKind.DANGER)
            },
        ) {
            Text(doc["title"].str().ifBlank { "未命名文档" }, fontSize = 13.sp, color = Ink2)
        }
    }
}

/**
 * 通用表格：tonal 表头 + hover 行 + 弱化分隔线 + 操作列插槽
 */
@Composable
private fun AdminTable(
    headers: List<Pair<String, Int>>,
    rows: List<List<String>>,
    opsCell: @Composable (rowIndex: Int, row: List<String>) -> Unit,
) {
    AppCardRaised(padding = 0.dp) {
        Row(
            Modifier.fillMaxWidth().background(SurfaceDeep)
                .padding(horizontal = Dimens.space4, vertical = 11.dp),
        ) {
            headers.forEach { (h, w) ->
                Text(h, Modifier.width(w.dp), fontSize = 11.5.sp,
                    fontWeight = FontWeight.Medium, color = Muted)
            }
        }
        if (rows.isEmpty()) {
            com.judicialai.desktop.design.components.EmptyLine("暂无数据")
        }
        rows.forEachIndexed { i, row ->
            val interaction = remember { MutableInteractionSource() }
            val hovered by interaction.collectIsHoveredAsState()
            Row(
                Modifier.fillMaxWidth()
                    .background(if (hovered) SurfaceTonal else Surface)
                    .padding(horizontal = Dimens.space4, vertical = 9.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                row.forEachIndexed { j, cell ->
                    val w = headers[j].second
                    if (cell == "ops") {
                        Box(Modifier.width(w.dp)) { opsCell(i, row) }
                    } else {
                        val isIndex = j == 0
                        val isState = headers[j].first == "状态"
                        Box(Modifier.width(w.dp)) {
                            if (isState) {
                                TagChip(
                                    text = cell,
                                    fg = if (cell == "正常") Ok else Danger,
                                    bg = if (cell == "正常") OkSoft else DangerSoft,
                                )
                            } else {
                                Text(cell, fontSize = 12.5.sp,
                                    color = if (isIndex) Muted2 else Ink2,
                                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                        }
                    }
                }
            }
            Box(Modifier.fillMaxWidth().height(1.dp).background(LineSubtle))
        }
    }
}
