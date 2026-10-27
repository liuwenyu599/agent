package com.judicialai.desktop.features.personal

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.judicialai.desktop.app.AppState
import com.judicialai.desktop.core.network.ApiResult
import com.judicialai.desktop.core.network.Endpoints
import com.judicialai.desktop.core.utils.arr
import com.judicialai.desktop.core.utils.bool
import com.judicialai.desktop.core.utils.int
import com.judicialai.desktop.core.utils.obj
import com.judicialai.desktop.core.utils.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.serialization.json.JsonObject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/** 个人中心分区：全部来自后端真实接口，无本地假数据 */
enum class PersonalSection(val title: String) {
    RECENT("最近使用"),
    DOCS("我的文档"),
    FAVORITES("我的收藏"),
    SECURITY("账号安全"),
    SETTINGS("个人设置"),
    GUIDE("使用指南"),
    /**
     * 个性化（v3.3）：个人偏好层，只影响 AI 的表达方式、写作习惯与称呼，
     * 不改变科室归属 / 知识检索范围 / 角色权限 / 安全规则。
     * 内容区与「账号安全」同构：左分类 + 右内容 + 显式保存按钮，不使用 Dialog。
     */
    PERSONALIZATION("个性化"),
}

/**
 * 个人中心数据源：
 * - 最近使用：GET /dashboard/summary → recent
 * - 我的文档：GET /documents
 * - 我的收藏：后端当前无通用收藏接口，展示说明而不是伪造列表
 */
class PersonalViewModel {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    data class DocItem(val id: String, val title: String, val status: String, val updatedAt: String)
    data class WritingMemoryItem(
        val id: String, val scope: String, val documentType: String,
        val content: String, val enabled: Boolean, val canEdit: Boolean,
    )

    var section by mutableStateOf(PersonalSection.RECENT)
        private set

    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    var recent by mutableStateOf(listOf<DocItem>())
        private set
    var docs by mutableStateOf(listOf<DocItem>())
        private set

    var writingMemories by mutableStateOf(listOf<WritingMemoryItem>())
        private set
    var memoryScope by mutableStateOf("personal")
    var memoryDocumentType by mutableStateOf("")
    var memoryContent by mutableStateOf("")
    var memoryEditingId by mutableStateOf<String?>(null)
    var memoryBusy by mutableStateOf(false)
        private set
    var memoryError by mutableStateOf<String?>(null)
        private set

    val memoryScopes: List<Pair<String, String>> get() = buildList {
        add("personal" to "个人")
        if (AppState.role in setOf("knowledge_admin", "developer", "admin"))
            add("department" to "本科室")
        if (AppState.role in setOf("developer", "admin")) add("public" to "公共")
    }

    // ---- 个性化：个人偏好（GET / PUT Endpoints.Preferences.ME）----

    /** 写作风格选项：value 为提交值，text 为主文案，desc 为说明；由服务端 options 下发 */
    data class PrefStyleOption(val value: String, val text: String, val desc: String = "")

    /** 默认行为选项：key 为提交键；由服务端 options 下发 */
    data class PrefBehaviorOption(val key: String, val text: String, val desc: String = "")

    /** 系统固定行为：页面只做只读说明，不提供开关（做成开关即为关不掉/关了不生效的假功能） */
    data class PrefFixedBehavior(val key: String, val text: String, val note: String = "")

    /** 已保存快照：「有未保存的修改」判定与「恢复已保存值」的来源 */
    private data class PrefSnapshot(
        val assistantName: String = "",
        val workPreference: String = "",
        val writingStyle: String = "",
        val writingStyleCustom: String = "",
        val citeSources: Boolean = false,
        val confirmStructure: Boolean = false,
    )

    var prefLoading by mutableStateOf(false)
        private set
    var prefSaving by mutableStateOf(false)
        private set
    var prefError by mutableStateOf<String?>(null)
        private set
    var prefSavedHint by mutableStateOf<String?>(null)
        private set

    /** 可编辑字段：由 UI 直接双向绑定 */
    var prefAssistantName by mutableStateOf("")
    var prefWorkPreference by mutableStateOf("")
    var prefWritingStyle by mutableStateOf("")
    var prefWritingStyleCustom by mutableStateOf("")
    var prefCiteSources by mutableStateOf(false)
    var prefConfirmStructure by mutableStateOf(false)

    /** 服务端下发的选项与文案；未下发时使用 companion 中的契约兜底值 */
    var prefStyleOptions by mutableStateOf(FALLBACK_STYLE_OPTIONS)
        private set
    var prefBehaviorOptions by mutableStateOf(FALLBACK_BEHAVIOR_OPTIONS)
        private set
    var prefFixedBehaviors by mutableStateOf(FALLBACK_FIXED_BEHAVIORS)
        private set
    var prefPermissionNotice by mutableStateOf(DEFAULT_PERMISSION_NOTICE)
        private set

    /** 长度上限：由服务端 options.limits 下发，UI 用它做即时拦截与提示 */
    var prefNameLimit by mutableStateOf(DEFAULT_NAME_LIMIT)
        private set
    var prefWorkLimit by mutableStateOf(DEFAULT_WORK_LIMIT)
        private set
    var prefCustomLimit by mutableStateOf(DEFAULT_CUSTOM_LIMIT)
        private set

    private var prefSnapshot by mutableStateOf(PrefSnapshot())

    /** 与已保存快照不一致即为「有未保存的修改」 */
    val prefDirty: Boolean
        get() = prefAssistantName != prefSnapshot.assistantName
            || prefWorkPreference != prefSnapshot.workPreference
            || prefWritingStyle != prefSnapshot.writingStyle
            || prefWritingStyleCustom != prefSnapshot.writingStyleCustom
            || prefCiteSources != prefSnapshot.citeSources
            || prefConfirmStructure != prefSnapshot.confirmStructure

    // ---- 账号安全：修改密码 ----
    var changing by mutableStateOf(false)
        private set
    var changeError by mutableStateOf<String?>(null)
        private set
    var changeSuccess by mutableStateOf<String?>(null)
        private set

    init {
        // 管理员重置过密码：打开个人中心时直接落在「账号安全」
        if (AppState.mustChangePassword) section = PersonalSection.SECURITY
    }

    fun select(section: PersonalSection) {
        this.section = section
        when (section) {
            // 个性化：每次进入都重新读取，保证与后端一致
            PersonalSection.PERSONALIZATION -> { loadPreferences(); loadWritingMemories() }
            // 这三个分区没有后端列表，不触发 load()
            PersonalSection.FAVORITES, PersonalSection.SETTINGS, PersonalSection.SECURITY, PersonalSection.GUIDE -> Unit
            else -> load()
        }
    }

    /**
     * 修改本人密码。强度规则与后端一致（≥8 位且同时包含大写字母、小写字母、数字、符号），
     * 这里只做即时反馈，最终以服务端校验为准；密码不落盘、不进日志。
     */
    fun changePassword(oldPassword: String, newPassword: String, confirm: String) {
        changeError = null
        changeSuccess = null
        if (oldPassword.isBlank() || newPassword.isBlank() || confirm.isBlank()) {
            changeError = "请填写完整"; return
        }
        if (newPassword != confirm) {
            changeError = "两次输入的新密码不一致"; return
        }
        if (newPassword == oldPassword) {
            changeError = "新密码不能与旧密码相同"; return
        }
        if (newPassword.length < 8
            || !newPassword.any { it.isUpperCase() }
            || !newPassword.any { it.isLowerCase() }
            || !newPassword.any { it.isDigit() }
            || !newPassword.any { !it.isLetterOrDigit() }) {
            changeError = "密码至少 8 位，且必须同时包含大写字母、小写字母、数字和符号"; return
        }
        changing = true
        scope.launch {
            when (val r = AppState.api.changePassword(oldPassword, newPassword)) {
                is ApiResult.Ok -> {
                    changeSuccess = "密码修改成功"
                    AppState.onPasswordChanged()
                }
                is ApiResult.Err -> changeError = r.message
            }
            changing = false
        }
    }

    fun clearChangeResult() {
        changeError = null
        changeSuccess = null
    }

    fun loadWritingMemories() {
        memoryError = null
        scope.launch {
            when (val r = AppState.api.get(Endpoints.WritingMemories.LIST)) {
                is ApiResult.Ok -> writingMemories = r.data.obj()?.get("items").arr()
                    .mapNotNull { it.obj() }.map { item ->
                        WritingMemoryItem(
                            id = item["id"].str(), scope = item["scope"].str(),
                            documentType = item["document_type"].str(),
                            content = item["content"].str(), enabled = item["enabled"].bool(),
                            canEdit = item["can_edit"].bool(),
                        )
                    }
                is ApiResult.Err -> memoryError = r.message
            }
        }
    }

    fun editWritingMemory(item: WritingMemoryItem) {
        if (!item.canEdit) return
        memoryEditingId = item.id
        memoryScope = item.scope
        memoryDocumentType = item.documentType
        memoryContent = item.content
        memoryError = null
    }

    fun clearWritingMemoryForm() {
        memoryEditingId = null
        memoryScope = "personal"
        memoryDocumentType = ""
        memoryContent = ""
    }

    fun saveWritingMemory() {
        if (memoryBusy) return
        val content = memoryContent.trim()
        if (content.isEmpty() || content.length > 500 || memoryDocumentType.length > 100) {
            memoryError = "请填写 1 至 500 字的记忆内容，文种不超过 100 字"
            return
        }
        memoryBusy = true
        memoryError = null
        val editing = memoryEditingId
        scope.launch {
            val r = if (editing == null) AppState.api.post(Endpoints.WritingMemories.LIST,
                mapOf("scope" to memoryScope, "document_type" to memoryDocumentType.trim(),
                      "content" to content))
            else AppState.api.patch(Endpoints.WritingMemories.item(editing),
                mapOf("document_type" to memoryDocumentType.trim(), "content" to content))
            when (r) {
                is ApiResult.Ok -> { clearWritingMemoryForm(); loadWritingMemories() }
                is ApiResult.Err -> memoryError = r.message
            }
            memoryBusy = false
        }
    }

    fun setWritingMemoryEnabled(item: WritingMemoryItem, enabled: Boolean) {
        if (memoryBusy || !item.canEdit) return
        memoryBusy = true
        scope.launch {
            when (val r = AppState.api.patch(Endpoints.WritingMemories.item(item.id),
                                             mapOf("enabled" to enabled))) {
                is ApiResult.Ok -> loadWritingMemories()
                is ApiResult.Err -> memoryError = r.message
            }
            memoryBusy = false
        }
    }

    fun deleteWritingMemory(item: WritingMemoryItem) {
        if (memoryBusy || !item.canEdit) return
        memoryBusy = true
        scope.launch {
            when (val r = AppState.api.del(Endpoints.WritingMemories.item(item.id))) {
                is ApiResult.Ok -> { clearWritingMemoryForm(); loadWritingMemories() }
                is ApiResult.Err -> memoryError = r.message
            }
            memoryBusy = false
        }
    }

    // ---------- 个性化：个人偏好 ----------

    /** GET /preferences/me：进入「个性化」分区时调用，后端未下发选项时保留契约兜底值。 */
    fun loadPreferences() {
        prefLoading = true
        prefError = null
        prefSavedHint = null
        scope.launch {
            when (val r = AppState.api.get(Endpoints.Preferences.ME)) {
                is ApiResult.Ok -> applyPreferences(r.data.obj())
                is ApiResult.Err -> prefError = r.message
            }
            prefLoading = false
        }
    }

    /**
     * PUT /preferences/me：显式保存（与「账号安全」的「确认修改」一致，不做自动保存）。
     * 长度先本地拦截（避免用户写半天被打回），最终仍以后端校验为准；
     * 保存成功后用后端返回值回写全部字段与快照，dirty 归零。
     */
    fun savePreferences() {
        if (prefSaving) return
        prefError = null
        prefSavedHint = null

        val name = prefAssistantName.trim()
        val work = prefWorkPreference.trim()
        val custom = prefWritingStyleCustom.trim()
        when {
            name.length > prefNameLimit -> {
                prefError = "助手称呼不能超过 ${prefNameLimit} 字"; return
            }
            work.length > prefWorkLimit -> {
                prefError = "工作偏好不能超过 ${prefWorkLimit} 字"; return
            }
            prefWritingStyle == STYLE_CUSTOM && custom.length > prefCustomLimit -> {
                prefError = "自定义说明不能超过 ${prefCustomLimit} 字"; return
            }
        }

        prefSaving = true
        val body: Map<String, Any?> = mapOf(
            "assistant_name" to name,
            "work_preference" to work,
            "writing_style" to prefWritingStyle,
            "writing_style_custom" to custom,
            "behaviors" to mapOf(
                "cite_sources" to prefCiteSources,
                "confirm_structure" to prefConfirmStructure,
            ),
        )
        scope.launch {
            when (val r = AppState.api.put(Endpoints.Preferences.ME, body)) {
                is ApiResult.Ok -> {
                    applyPreferences(r.data.obj())
                    prefSavedHint = "已保存，后续生成会按你的偏好执行"
                }
                is ApiResult.Err -> prefError = r.message
            }
            prefSaving = false
        }
    }

    /** 恢复已保存值：把当前编辑值回滚到最近一次服务端确认的快照。 */
    fun resetPreferences() {
        val s = prefSnapshot
        prefAssistantName = s.assistantName
        prefWorkPreference = s.workPreference
        prefWritingStyle = s.writingStyle
        prefWritingStyleCustom = s.writingStyleCustom
        prefCiteSources = s.citeSources
        prefConfirmStructure = s.confirmStructure
        prefError = null
        prefSavedHint = null
    }

    /** 默认行为勾选：按服务端下发的 key 读写，未知 key 一律返回 false，不臆造开关。 */
    fun prefBehaviorChecked(key: String): Boolean = when (key) {
        "cite_sources" -> prefCiteSources
        "confirm_structure" -> prefConfirmStructure
        else -> false
    }

    fun setPrefBehavior(key: String, checked: Boolean) {
        when (key) {
            "cite_sources" -> prefCiteSources = checked
            "confirm_structure" -> prefConfirmStructure = checked
            else -> Unit
        }
        prefSavedHint = null
    }

    /** 把后端返回体写入编辑态 + 快照（保存成功后也走这里，保证 dirty 归零）。 */
    private fun applyPreferences(root: JsonObject?) {
        val o = root ?: return
        prefAssistantName = o["assistant_name"].str()
        prefWorkPreference = o["work_preference"].str()
        prefWritingStyle = o["writing_style"].str()
        prefWritingStyleCustom = o["writing_style_custom"].str()
        val behaviors = o["behaviors"].obj()
        prefCiteSources = behaviors?.get("cite_sources").bool()
        prefConfirmStructure = behaviors?.get("confirm_structure").bool()

        val options = o["options"].obj()
        val styles = options?.get("writing_style").arr().mapNotNull { it.obj() }.map { d ->
            PrefStyleOption(
                value = d["value"].str(),
                text = d["text"].str().ifBlank { d["value"].str() },
                desc = d["desc"].str(),
            )
        }
        if (styles.isNotEmpty()) prefStyleOptions = styles

        val behaviorOpts = options?.get("behaviors").arr().mapNotNull { it.obj() }.map { d ->
            PrefBehaviorOption(
                key = d["key"].str(),
                text = d["text"].str().ifBlank { d["key"].str() },
                desc = d["desc"].str(),
            )
        }
        if (behaviorOpts.isNotEmpty()) prefBehaviorOptions = behaviorOpts

        val limits = options?.get("limits")?.obj()
        prefNameLimit = limits?.get("assistant_name").int().takeIf { it > 0 } ?: DEFAULT_NAME_LIMIT
        prefWorkLimit = limits?.get("work_preference").int().takeIf { it > 0 } ?: DEFAULT_WORK_LIMIT
        prefCustomLimit =
            limits?.get("writing_style_custom").int().takeIf { it > 0 } ?: DEFAULT_CUSTOM_LIMIT

        val fixed = o["fixed_behaviors"].arr().mapNotNull { it.obj() }.map { d ->
            PrefFixedBehavior(
                key = d["key"].str(),
                text = d["text"].str().ifBlank { d["key"].str() },
                note = d["note"].str(),
            )
        }
        if (fixed.isNotEmpty()) prefFixedBehaviors = fixed

        val notice = o["permission_notice"].str()
        if (notice.isNotBlank()) prefPermissionNotice = notice

        prefSnapshot = snapshot()
    }

    private fun snapshot(): PrefSnapshot = PrefSnapshot(
        assistantName = prefAssistantName,
        workPreference = prefWorkPreference,
        writingStyle = prefWritingStyle,
        writingStyleCustom = prefWritingStyleCustom,
        citeSources = prefCiteSources,
        confirmStructure = prefConfirmStructure,
    )

    companion object {
        /** 写作风格取值：与后端枚举一致，UI 只比较字符串，不另建映射表 */
        const val STYLE_CUSTOM = "custom"

        /**
         * 以下为服务端 options / permission_notice 未下发时的兜底值，
         * 取值与接口契约 §6.1 完全一致；服务端一旦下发即被覆盖，桌面端不自行推导开关。
         */
        private const val DEFAULT_NAME_LIMIT = 20
        private const val DEFAULT_WORK_LIMIT = 600
        private const val DEFAULT_CUSTOM_LIMIT = 200
        private const val DEFAULT_PERMISSION_NOTICE =
            "个人偏好只影响 AI 的表达方式、写作习惯与称呼，" +
                "不改变你的科室归属、知识检索范围、角色权限与系统安全规则。"

        private val FALLBACK_STYLE_OPTIONS = listOf(
            PrefStyleOption("concise_formal", "简洁正式", "篇幅紧凑、结论先行，去除铺陈与重复表述"),
            PrefStyleOption("rigorous_detailed", "严谨详细", "论证充分、层次分明，数据与依据完整"),
            PrefStyleOption("custom", "自定义", "按补充说明执行"),
        )

        private val FALLBACK_BEHAVIOR_OPTIONS = listOf(
            PrefBehaviorOption("cite_sources", "回答时附相关依据",
                "在回答中标注结论来自哪份资料或条款"),
            PrefBehaviorOption("confirm_structure", "生成正式文稿前先确认结构",
                "先给出结构提纲并等待确认，再展开成文"),
        )

        private val FALLBACK_FIXED_BEHAVIORS = listOf(
            PrefFixedBehavior("prefer_dept_template", "优先使用本科室模板",
                "系统已固定为本科室模板优先、其次公共模板，此处不提供开关"),
        )
    }

    fun load() {
        loading = true
        error = null
        scope.launch { loadRecent() }
        scope.launch { loadDocs() }
        loading = false
    }

    private suspend fun loadRecent() {
        when (val r = AppState.api.get(Endpoints.Dashboard.SUMMARY)) {
            is ApiResult.Ok -> {
                val o = r.data.obj() ?: return
                recent = o["recent"].arr().mapNotNull { it.obj() }.map { d ->
                    DocItem(
                        id = d["id"].str(),
                        title = d["title"].str().ifBlank { "未命名文档" },
                        status = d["status"].str(),
                        updatedAt = d["updated_at"].str().take(16).replace("T", " "),
                    )
                }
            }
            is ApiResult.Err -> Unit
        }
    }

    private suspend fun loadDocs() {
        when (val r = AppState.api.get(Endpoints.Documents.LIST,
                mapOf("page" to "1", "page_size" to "50"))) {
            is ApiResult.Ok -> {
                val root = r.data.obj()
                val list = (root?.get("items") ?: root?.get("data")).arr()
                docs = list.mapNotNull { it.obj() }.map { d ->
                    DocItem(
                        id = d["id"].str(),
                        title = d["title"].str().ifBlank { "未命名文档" },
                        status = d["status"].str(),
                        updatedAt = d["updated_at"].str().take(16).replace("T", " "),
                    )
                }
            }
            is ApiResult.Err -> Unit
        }
    }
}
