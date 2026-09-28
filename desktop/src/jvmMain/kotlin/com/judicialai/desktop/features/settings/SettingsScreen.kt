package com.judicialai.desktop.features.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Card
import androidx.compose.material.OutlinedButton
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.judicialai.desktop.design.theme.EpPrimary
import com.judicialai.desktop.design.theme.TextPrimary
import com.judicialai.desktop.design.theme.TextRegular
import com.judicialai.desktop.design.theme.TextSecondary

/** 服务器连接设置：对应 Web ServerSettingsView（顶栏用户下拉进入） */
@Composable
fun SettingsScreen() {
    val vm = remember { SettingsViewModel() }

    Column(Modifier.fillMaxSize().padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Column {
            Text("服务器连接设置", fontSize = 20.sp, fontWeight = FontWeight.Bold,
                color = TextPrimary)
            Text("配置司法智能办公平台的服务连接", fontSize = 13.sp, color = TextSecondary)
        }

        Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp,
            modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Text("服务器地址", fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                    color = TextPrimary)
                OutlinedTextField(
                    value = vm.baseUrl,
                    onValueChange = { vm.baseUrl = it },
                    placeholder = { Text("请输入本单位提供的服务地址") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    colors = TextFieldDefaults.outlinedTextFieldColors(
                        focusedBorderColor = EpPrimary, cursorColor = EpPrimary),
                )
                Text(
                    "修改服务器地址会结束当前登录，并清理正在恢复的写作/PPT任务；请确认新地址属于本单位可信服务器。",
                    fontSize = 12.sp, color = TextSecondary)
                OutlinedTextField(
                    value = vm.timeoutSec,
                    onValueChange = { vm.timeoutSec = it.filter { c -> c.isDigit() } },
                    label = { Text("最长等待时间（秒），内容生成较慢时建议 120 以上") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    colors = TextFieldDefaults.outlinedTextFieldColors(
                        focusedBorderColor = EpPrimary, cursorColor = EpPrimary),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Button(onClick = { vm.save() },
                        colors = ButtonDefaults.buttonColors(backgroundColor = EpPrimary)) {
                        Text("保存", color = Color.White)
                    }
                    OutlinedButton(enabled = !vm.testing, onClick = { vm.saveAndTest() }) {
                        Text(if (vm.testing) "测试中…" else "保存并测试连接")
                    }
                    vm.message?.let { Text(it, fontSize = 13.sp, color = TextRegular) }
                }
            }
        }

        Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp,
            modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(20.dp)) {
                Text("安全说明", fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                    color = TextPrimary)
                Spacer(Modifier.height(8.dp))
                Text(
                    "· 请仅使用本单位提供的可信服务地址\n" +
                        "· 登录凭据仅在本次使用期间保留，退出登录后自动清除\n" +
                        "· 客户端不会保存服务器密钥、账号密码或内部配置\n" +
                        "· 本机日志不会记录密码与文档正文",
                    fontSize = 13.sp, color = TextRegular, lineHeight = 22.sp)
            }
        }
    }
}

