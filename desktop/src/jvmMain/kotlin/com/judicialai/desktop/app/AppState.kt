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

    var screen by mutableStateOf(AppScreen.HOME)

    /** 普通聊天中识别到写作意图时，跳转到工作台携带的一句话需求 */
    var pendingWritingIntent by mutableStateOf<String?>(null)

    // ---- 导航形态 ----
    /** 全局导航抽屉（点击顶部品牌名打开） */
    var navDrawerOpen by mutableStateOf(false)

    /** 工作区导航是否折叠为图标条 */
    var navCollapsed by mutableStateOf(false)

    /** 工作区导航宽度（可拖拽调节，范围 180–360dp） */
    var navWidth by mutableStateOf(236f)

    /** 个人中心抽屉（右上角入口） */
    var personalCenterOpen by mutableStateOf(false)

    /** 工作区导航是否被固定展开（固定后不随页面切换自动收起） */
    var navPinned by mutableStateOf(true)

    /** 导航搜索词：仅用于过滤导航项，不做任何假数据搜索 */
    var navQuery by mutableStateOf("")

    /** 管理后台直达 Tab（对应 AdminScreen 内 TabRow） */
    var adminTab by mutableStateOf(0)

    /** 待办数量（来自 /approvals/counts，未取到时为 0，前端不臆造） */
    var todoCount by mutableStateOf(0)

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

    /** 所属科室名称（来自 /dashboard/summary 或 /organization/me，未取到时为空，UI 不臆造） */
    var departmentName by mutableStateOf("")
    /** 所属科室代码（后端下发；用于科室空间与检索范围） */
    var departmentCode by mutableStateOf("")
    /** 当前科室 Agent 名称（后端下发，未配置时为空） */
    var agentName by mutableStateOf("")
    /** 后端下发的知识作用域（GLOBAL / DEPT:x），仅展示，前端不参与权限判断 */
    var knowledgeScopes by mutableStateOf(listOf<String>())

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
        this.screen = AppScreen.HOME
        this.navDrawerOpen = false
    }

    fun logout() {
        api.setToken(null)
        loggedIn = false
        username = ""
        realName = ""
        role = "user"
        departmentName = ""
        departmentCode = ""
        agentName = ""
        knowledgeScopes = emptyList()
        screen = AppScreen.HOME
        navDrawerOpen = false
    }

    /** 统一导航入口：设置页面 + 管理后台 Tab + 关闭抽屉 */
    fun navigate(screen: AppScreen, adminTab: Int = 0) {
        this.adminTab = adminTab
        this.screen = screen
        this.navDrawerOpen = false
        this.navQuery = ""
    }
}

