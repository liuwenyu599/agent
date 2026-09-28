package com.judicialai.desktop.features.settings

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.network.ApiResult
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class SettingsViewModel {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var baseUrl by mutableStateOf(AppState.serverConfig.baseUrl)
    var timeoutSec by mutableStateOf((AppState.serverConfig.requestTimeoutMillis / 1000).toString())
    var testing by mutableStateOf(false)
        private set
    var message by mutableStateOf<String?>(null)
        private set

    fun save(): Boolean {
        val url = baseUrl.trim().trimEnd('/')
        if (!(url.startsWith("http://") || url.startsWith("https://"))) {
            message = "服务器地址必须以 http:// 或 https:// 开头"
            return false
        }
        val timeout = timeoutSec.toLongOrNull()
        if (timeout == null || timeout !in 10L..1800L) {
            message = "请求超时请输入 10～1800 秒"
            return false
        }

        val endpointChanged = AppState.serverConfig.baseUrl.trim().trimEnd('/') != url
        val wasLoggedIn = AppState.loggedIn
        AppState.updateServerConfig(AppState.serverConfig.copy(
            baseUrl = url,
            requestTimeoutMillis = timeout * 1000,
        ))
        message = if (endpointChanged && wasLoggedIn)
            "服务器地址已更新；为保护登录凭据，当前会话已退出，请在新服务器重新登录"
        else "已保存"
        return true
    }

    fun saveAndTest() {
        if (!save()) return
        testing = true
        scope.launch {
            message = when (val r = AppState.api.checkConnection()) {
                is ApiResult.Ok -> r.data
                is ApiResult.Err -> r.message
            }
            testing = false
        }
    }
}

