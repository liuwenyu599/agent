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
            Text("配置司法智能办公平台后端服务地址", fontSize = 13.sp, color = TextSecondary)
        }

        Card(shape = RoundedCornerShape(8.dp), elevation = 0.dp,
            modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Text("服务器地址", fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
                    color = TextPrimary)
                OutlinedTextField(
                    value = vm.baseUrl,
                    onValueChange = { vm.baseUrl = it },
                    placeholder = { Text("如 http://127.0.0.1:8000 或 http://内网地址:8000") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    colors = TextFieldDefaults.outlinedTextFieldColors(
                        focusedBorderColor = EpPrimary, cursorColor = EpPrimary),
                )
                OutlinedTextField(
                    value = vm.timeoutSec,
                    onValueChange = { vm.timeoutSec = it.filter { c -> c.isDigit() } },
                    label = { Text("请求超时（秒），AI 长任务建议 120 以上") },
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
                    "· 生产环境使用司法局内网地址；HTTP 仅允许内网部署时作为配置项，客户端不写死地址\n" +
                        "· 登录令牌只保存在内存中，退出登录即清除，不写入磁盘\n" +
                        "· 客户端不保存任何 API Key、密码、模型权重与服务器内部路径\n" +
                        "· 本机日志不记录 token、密码与文件内容",
                    fontSize = 13.sp, color = TextRegular, lineHeight = 22.sp)
            }
        }
    }
}

