package com.judicialai.desktop.features.auth

import androidx.compose.foundation.background
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
import androidx.compose.material.CircularProgressIndicator
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.design.components.AppButton
import com.judicialai.desktop.design.components.AppButtonKind
import com.judicialai.desktop.design.components.AppDialog
import com.judicialai.desktop.design.layout.LocalWindowChrome
import com.judicialai.desktop.design.layout.WindowControlGroup
import com.judicialai.desktop.design.layout.dragWindow
import com.judicialai.desktop.design.theme.EpPrimary
import com.judicialai.desktop.design.theme.EpPrimaryDark
import com.judicialai.desktop.design.theme.TextRegular
import com.judicialai.desktop.design.theme.TextSecondary
import com.judicialai.desktop.features.settings.SettingsViewModel

/**
 * 登录页。
 *
 * 首个系统管理员必须由部署主机执行 `python -m scripts.create_admin` 创建，客户端不再暴露
 * 匿名 register-first/check-first-user 流程，消除全新部署阶段的管理员抢注窗口。
 */
@Composable
fun LoginScreen(vm: AuthViewModel = remember { AuthViewModel() }) {
    var showServerSettings by remember { mutableStateOf(false) }
    val settingsVm = remember { SettingsViewModel() }

    Box(
        Modifier.fillMaxSize().background(
            Brush.linearGradient(listOf(
                com.judicialai.desktop.design.theme.LoginGradStart,
                com.judicialai.desktop.design.theme.LoginGradEnd,
            ))
        ),
        contentAlignment = Alignment.Center,
    ) {
        val chrome = LocalWindowChrome.current
        if (chrome != null) {
            Row(
                Modifier.align(Alignment.TopCenter).fillMaxWidth().height(40.dp)
                    .dragWindow(chrome.window),
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                WindowControlGroup(chrome)
                Spacer(Modifier.width(10.dp))
            }
        }

        Card(
            Modifier.width(420.dp).verticalScroll(rememberScrollState()),
            shape = RoundedCornerShape(12.dp),
            elevation = 16.dp,
            backgroundColor = Color.White,
        ) {
            Column(Modifier.padding(28.dp)) {
                Text(
                    "白云司法局智慧办公平台",
                    fontSize = 22.sp,
                    fontWeight = FontWeight.Bold,
                    color = EpPrimaryDark,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(24.dp))
                LoginForm(vm)
                vm.error?.let {
                    Spacer(Modifier.height(12.dp))
                    Text(it, color = com.judicialai.desktop.design.theme.EpDanger, fontSize = 13.sp)
                }
                Spacer(Modifier.height(14.dp))
                TextButton(
                    onClick = { showServerSettings = true },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("服务器连接设置", fontSize = 12.5.sp, color = TextSecondary)
                }
            }
        }
    }

    if (showServerSettings) {
        LoginServerSettingsDialog(settingsVm) { showServerSettings = false }
    }
}

@Composable
private fun LoginServerSettingsDialog(
    vm: SettingsViewModel,
    onDismiss: () -> Unit,
) {
    AppDialog(
        onDismissRequest = onDismiss,
        title = "服务器连接",
        subtitle = "首次部署或服务器地址变更时使用。请仅填写本单位可信服务器地址。",
        width = 520.dp,
        actions = {
            AppButton("关闭", onClick = onDismiss, kind = AppButtonKind.SECONDARY)
            Spacer(Modifier.width(8.dp))
            AppButton(
                if (vm.testing) "测试中…" else "保存并测试",
                onClick = { vm.saveAndTest() },
                enabled = !vm.testing,
            )
        },
    ) {
        OutlinedTextField(
            value = vm.baseUrl,
            onValueChange = { vm.baseUrl = it },
            label = { Text("服务器地址") },
            placeholder = { Text("例如：http://10.0.0.20:8000") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Text(
            "当前配置：${AppState.serverConfig.baseUrl}",
            fontSize = 11.5.sp,
            color = TextSecondary,
        )
        vm.message?.let {
            Text(
                it,
                fontSize = 12.5.sp,
                color = if (it.contains("成功") || it.contains("正常") || it == "已保存")
                    com.judicialai.desktop.design.theme.EpSuccess else TextRegular,
            )
        }
    }
}

@Composable
private fun LoginForm(vm: AuthViewModel) {
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    Field(username, { username = it }, "用户名")
    Spacer(Modifier.height(12.dp))
    Field(password, { password = it }, "密码", isPassword = true)
    Spacer(Modifier.height(20.dp))
    SubmitButton("登录", EpPrimary, vm.busy) { vm.login(username, password) }
}

@Composable
private fun Field(
    value: String,
    onChange: (String) -> Unit,
    placeholder: String,
    isPassword: Boolean = false,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        placeholder = { Text(placeholder, color = TextSecondary) },
        singleLine = true,
        visualTransformation = if (isPassword) PasswordVisualTransformation()
        else androidx.compose.ui.text.input.VisualTransformation.None,
        modifier = Modifier.fillMaxWidth(),
        colors = androidx.compose.material.TextFieldDefaults.outlinedTextFieldColors(
            focusedBorderColor = EpPrimary,
            cursorColor = EpPrimary,
        ),
    )
}

@Composable
private fun SubmitButton(text: String, color: Color, busy: Boolean, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        enabled = !busy,
        modifier = Modifier.fillMaxWidth().height(44.dp),
        colors = ButtonDefaults.buttonColors(backgroundColor = color),
        shape = RoundedCornerShape(6.dp),
    ) {
        if (busy) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                CircularProgressIndicator(
                    color = Color.White,
                    strokeWidth = 2.dp,
                    modifier = Modifier.height(16.dp).width(16.dp),
                )
                Text("请稍候…", color = Color.White, fontSize = 15.sp)
            }
        } else {
            Text(text, color = Color.White, fontSize = 15.sp)
        }
    }
}
