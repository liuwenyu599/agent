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

    fun save() {
        AppState.updateServerConfig(AppState.serverConfig.copy(
            baseUrl = baseUrl.trim(),
            requestTimeoutMillis = (timeoutSec.toLongOrNull() ?: 120L) * 1000,
        ))
        message = "已保存"
    }

    fun saveAndTest() {
        save()
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

