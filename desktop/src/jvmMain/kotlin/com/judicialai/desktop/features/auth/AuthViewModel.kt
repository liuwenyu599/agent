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

    /** 系统是否无用户（决定显示「首次注册」Tab） */
    var isFirstUser by mutableStateOf(false)
        private set

    init {
        scope.launch {
            isFirstUser = AppState.api.checkFirstUser()
        }
    }

    fun login(username: String, password: String) {
        if (username.isBlank() || password.isBlank()) {
            error = "请输入用户名和密码"; return
        }
        busy = true; error = null; info = null
        scope.launch {
            when (val r = AppState.api.login(username, password)) {
                is ApiResult.Ok -> AppState.onLoginSuccess(r.data.username, r.data.realName, r.data.role)
                is ApiResult.Err -> error = r.message
            }
            busy = false
        }
    }

    fun register(username: String, password: String, email: String, realName: String, department: String) {
        if (username.isBlank() || password.isBlank() || email.isBlank()) {
            error = "请填写完整信息"; return
        }
        busy = true; error = null; info = null
        scope.launch {
            when (val r = AppState.api.register(username, password, email, realName, department)) {
                is ApiResult.Ok -> AppState.onLoginSuccess(r.data.username, r.data.realName, r.data.role)
                is ApiResult.Err -> error = r.message
            }
            busy = false
        }
    }

    fun registerFirst(username: String, password: String, email: String, realName: String, department: String) {
        if (username.isBlank() || password.isBlank() || email.isBlank()) {
            error = "请填写完整信息"; return
        }
        busy = true; error = null; info = null
        scope.launch {
            when (val r = AppState.api.registerFirst(username, password, email, realName, department)) {
                is ApiResult.Ok -> {
                    isFirstUser = false
                    AppState.onLoginSuccess(r.data.username, r.data.realName, r.data.role)
                }
                is ApiResult.Err -> error = r.message
            }
            busy = false
        }
    }
}

