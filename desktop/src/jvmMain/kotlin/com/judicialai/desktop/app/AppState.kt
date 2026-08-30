package com.judicialai.desktop.app

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.core.network.ApiClient
import com.judicialai.desktop.core.storage.ServerConfig

/**
 * 应用全局状态：当前页面、服务器配置、登录态、当前用户。
 * token 只在 ApiClient 内存中，不落盘；用户信息仅保存展示所需字段。
 */
object AppState {

    var screen by mutableStateOf(AppScreen.DASHBOARD)

    var serverConfig by mutableStateOf(ServerConfig.load())
        private set

    var loggedIn by mutableStateOf(false)
        private set

    var username by mutableStateOf("")
        private set

    var realName by mutableStateOf("")
        private set

    var role by mutableStateOf("user")
        private set

    /** 全应用唯一网络入口 */
    val api: ApiClient by lazy { ApiClient({ serverConfig }) }

    /** 对应 Web 端 AppLayout.isAdmin：developer / knowledge_admin / admin */
    val isAdmin: Boolean get() = role in setOf("developer", "knowledge_admin", "admin")

    val displayName: String get() = realName.ifBlank { username.ifBlank { "用户" } }

    /** 对应 Web 端角色映射 */
    val roleText: String
        get() = when (role) {
            "developer" -> "系统管理员"
            "knowledge_admin" -> "知识管理员"
            "admin" -> "管理员"
            "user" -> "普通用户"
            else -> role
        }

    fun updateServerConfig(cfg: ServerConfig) {
        serverConfig = cfg
        ServerConfig.save(cfg)
    }

    fun onLoginSuccess(username: String, realName: String, role: String) {
        this.username = username
        this.realName = realName
        this.role = role
        this.loggedIn = true
        this.screen = AppScreen.DASHBOARD
    }

    fun logout() {
        api.setToken(null)
        loggedIn = false
        username = ""
        realName = ""
        role = "user"
        screen = AppScreen.DASHBOARD
    }
}

