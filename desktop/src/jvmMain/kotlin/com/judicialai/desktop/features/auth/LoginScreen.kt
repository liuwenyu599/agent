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
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Tab
import androidx.compose.material.TabRow
import androidx.compose.material.Text
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
import com.judicialai.desktop.design.theme.EpDanger
import com.judicialai.desktop.design.theme.EpPrimary
import com.judicialai.desktop.design.theme.EpPrimaryDark
import com.judicialai.desktop.design.theme.EpSuccess
import com.judicialai.desktop.design.theme.LoginGradEnd
import com.judicialai.desktop.design.theme.LoginGradStart
import com.judicialai.desktop.design.theme.TextRegular
import com.judicialai.desktop.design.theme.TextSecondary

/**
 * 登录页：1:1 还原 Web 端 LoginView.vue
 * 135° 蓝渐变背景（#1a5fb4 → #4a90d9）+ 居中 420px 圆角卡片 + 登录/注册/首次注册 Tab。
 */
@Composable
fun LoginScreen(vm: AuthViewModel = remember { AuthViewModel() }) {
    Box(
        Modifier.fillMaxSize().background(
            Brush.linearGradient(listOf(LoginGradStart, LoginGradEnd))
        ),
        contentAlignment = Alignment.Center,
    ) {
        Card(
            Modifier.width(420.dp).verticalScroll(rememberScrollState()),
            shape = RoundedCornerShape(12.dp),
            elevation = 16.dp,
            backgroundColor = Color.White,
        ) {
            Column(Modifier.padding(28.dp)) {
                Text(
                    "🏛️ 司法智能办公辅助平台 V1.0",
                    fontSize = 22.sp,
                    fontWeight = FontWeight.Bold,
                    color = EpPrimaryDark,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(20.dp))

                // Tab：首次使用时只显示 登录 / 首次注册（系统管理员）
                val tabs = if (vm.isFirstUser)
                    listOf("登录", "首次注册（系统管理员）")
                else
                    listOf("登录")
                var tab by remember(vm.isFirstUser) {
                    mutableStateOf(if (vm.isFirstUser) 1 else 0)
                }
                TabRow(
                    selectedTabIndex = tab,
                    backgroundColor = Color.White,
                    contentColor = EpPrimary,
                ) {
                    tabs.forEachIndexed { i, title ->
                        Tab(selected = tab == i, onClick = { tab = i }) {
                            Text(title, fontSize = 14.sp,
                                modifier = Modifier.padding(vertical = 12.dp))
                        }
                    }
                }
                Spacer(Modifier.height(20.dp))

                when (tabs[tab]) {
                    "登录" -> LoginForm(vm)
                   "首次注册（系统管理员）" -> RegisterForm(vm, first = true)
                }

                vm.error?.let {
                    Spacer(Modifier.height(12.dp))
                    Text(it, color = EpDanger, fontSize = 13.sp)
                }
                vm.info?.let {
                    Spacer(Modifier.height(12.dp))
                    Text(it, color = EpSuccess, fontSize = 13.sp)
                }
            }
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
private fun RegisterForm(vm: AuthViewModel, first: Boolean) {
    var username by remember { mutableStateOf("") }
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var realName by remember { mutableStateOf("") }
    var department by remember { mutableStateOf("") }

    if (first) {
        Card(
            backgroundColor = Color(0xFFF4F4F5),
            elevation = 0.dp,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(Modifier.padding(12.dp)) {
                Text("系统首次使用", fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                    color = TextRegular)
                Text("当前系统没有用户，请创建系统管理员账号", fontSize = 12.sp,
                    color = TextSecondary)
            }
        }
        Spacer(Modifier.height(16.dp))
    }
    Field(username, { username = it }, "用户名")
    Spacer(Modifier.height(12.dp))
    Field(email, { email = it }, "邮箱")
    Spacer(Modifier.height(12.dp))
    Field(password, { password = it }, "密码", isPassword = true)
    Spacer(Modifier.height(12.dp))
    Field(realName, { realName = it }, "真实姓名")
    Spacer(Modifier.height(12.dp))
    Field(department, { department = it }, "部门")
    Spacer(Modifier.height(20.dp))
    if (first) {
        SubmitButton("创建系统管理员", EpDanger, vm.busy) {
            vm.registerFirst(username, password, email, realName, department)
        }
    } else {
        SubmitButton("注册", EpSuccess, vm.busy) {
            vm.register(username, password, email, realName, department)
        }
    }
}

@Composable
private fun Field(
    value: String, onChange: (String) -> Unit,
    placeholder: String, isPassword: Boolean = false,
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
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CircularProgressIndicator(color = Color.White, strokeWidth = 2.dp,
                    modifier = Modifier.height(16.dp).width(16.dp))
                Text("请稍候…", color = Color.White, fontSize = 15.sp)
            }
        } else {
            Text(text, color = Color.White, fontSize = 15.sp)
        }
    }
}

