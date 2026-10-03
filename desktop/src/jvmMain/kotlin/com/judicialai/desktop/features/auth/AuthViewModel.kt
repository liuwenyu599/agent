package com.judicialai.desktop.features.auth

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.network.ApiResult
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class AuthViewModel {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var info by mutableStateOf<String?>(null)
        private set

    fun login(username: String, password: String) {
        if (username.isBlank() || password.isBlank()) {
            error = "请输入用户名和密码"
            return
        }
        busy = true
        error = null
        info = null
        scope.launch {
            when (val r = AppState.api.login(username, password)) {
                is ApiResult.Ok -> AppState.onLoginSuccess(
                    r.data.username,
                    r.data.realName,
                    r.data.role,
                    r.data.mustChangePassword,
                )
                is ApiResult.Err -> error = r.message
            }
            busy = false
        }
    }
}
