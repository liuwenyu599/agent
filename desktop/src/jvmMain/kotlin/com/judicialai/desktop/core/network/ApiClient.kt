package com.judicialai.desktop.core.network

import com.judicialai.desktop.core.logging.ClientLog
import com.judicialai.desktop.core.storage.ServerConfig
import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.engine.cio.CIO
import io.ktor.client.plugins.HttpRequestTimeoutException
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.request.HttpRequestBuilder
import io.ktor.client.request.delete
import io.ktor.client.request.forms.formData
import io.ktor.client.request.forms.submitFormWithBinaryData
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.parameter
import io.ktor.client.request.patch
import io.ktor.client.request.post
import io.ktor.client.request.preparePost
import io.ktor.client.request.put
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsChannel
import io.ktor.http.ContentType
import io.ktor.http.Headers
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.contentType
import io.ktor.http.isSuccess
import io.ktor.serialization.kotlinx.json.json
import io.ktor.utils.io.readUTF8Line
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.net.ConnectException

/**
 * 统一网络入口：所有业务 Repository 只能经由它访问服务器。
 * 安全约束：token 只存内存；日志不记敏感信息；地址一律来自 ServerConfig。
 */
class ApiClient(private val configProvider: () -> ServerConfig) {

    @Volatile
    var token: String? = null
        private set

    fun setToken(t: String?) { token = t }
    val loggedIn: Boolean get() = token != null

    private val json = Json { ignoreUnknownKeys = true }
    private fun Any?.toJsonElement(): JsonElement = when (this) {
        null -> JsonNull
        is JsonElement -> this
        is String -> JsonPrimitive(this)
        is Boolean -> JsonPrimitive(this)
        is Int -> JsonPrimitive(this)
        is Long -> JsonPrimitive(this)
        is Float -> JsonPrimitive(this)
        is Double -> JsonPrimitive(this)
        is Number -> JsonPrimitive(this.toString())
        is Map<*, *> -> JsonObject(
            this.entries
                .filter { it.key is String }
                .associate { (key, value) ->
                    key as String to value.toJsonElement()
                }
        )
        is Iterable<*> -> JsonArray(
            this.map { it.toJsonElement() }
        )
        is Array<*> -> JsonArray(
            this.map { it.toJsonElement() }
        )
        else -> JsonPrimitive(this.toString())
    }
    private fun client(timeoutMs: Long? = null): HttpClient {
        val cfg = configProvider()
        return HttpClient(CIO) {
            expectSuccess = false
            install(HttpTimeout) {
                connectTimeoutMillis = cfg.connectTimeoutMillis
                requestTimeoutMillis = timeoutMs ?: cfg.requestTimeoutMillis
                socketTimeoutMillis = timeoutMs ?: cfg.requestTimeoutMillis
            }
            install(ContentNegotiation) { json(json) }
        }
    }

    private fun friendlyMessage(e: Throwable): String = when (e) {
        is ConnectException -> "服务器不可达，请检查地址与网络"
        is HttpRequestTimeoutException -> "请求超时，请稍后重试"
        is java.io.IOException -> "连接失败：" + (e.message ?: "网络异常")
        else -> "请求失败：" + (e.message ?: "未知错误")
    }

    private fun errMsg(status: Int?, body: String?, e: Throwable?): String {
        if (e != null) return friendlyMessage(e)
        val detail = runCatching {
            // 本版本的 kotlinx 没有 JsonPrimitive.contentOrNull，这里统一兜一层
            fun prim(el: JsonElement?): String? =
                runCatching { el?.jsonPrimitive?.content }.getOrNull()
            val el = body?.let { json.parseToJsonElement(it) as? JsonObject }?.get("detail")
            when (el) {
                // 常规：{"detail": "中文提示"}
                is JsonPrimitive -> prim(el)
                // FastAPI 参数校验失败（HTTP 422）：detail 是 [{type,loc,msg,input}] 数组，
                // msg 是英文技术文案，不直接抛给用户，统一给中文提示；原始内容落日志便于排障。
                // 不兜住的话这里会因 jsonPrimitive 抛错而整段退化成「请求失败（HTTP 422）」。
                is JsonArray -> {
                    val first = el.firstOrNull() as? JsonObject
                    val loc = first?.get("loc")?.toString().orEmpty()
                    ClientLog.warn("请求参数不合法 status=$status loc=$loc msg=${prim(first?.get("msg"))}")
                    "请求参数不合法" + (status?.let { "（HTTP $it）" } ?: "")
                }
                // 写作质量门等业务错误：detail 为 {code,message,issues}。
                is JsonObject -> {
                    val message = prim(el["message"])?.takeIf { it.isNotBlank() }
                    val issues = (el["issues"] as? JsonArray).orEmpty()
                        .mapNotNull { issue ->
                            prim((issue as? JsonObject)?.get("message"))
                                ?.takeIf { it.isNotBlank() }
                        }.take(3)
                    listOfNotNull(message, issues.takeIf { it.isNotEmpty() }
                        ?.joinToString("；")).joinToString("\n")
                        .takeIf { it.isNotBlank() }
                }
                else -> null
            }
        }.getOrNull()
        return detail ?: "请求失败（HTTP $status）"
    }

    // ---------- 连接测试 ----------

    suspend fun checkConnection(): ApiResult<String> {
        val url = configProvider().baseUrl.trimEnd('/') + "/docs"
        return try {
            client().use { c ->
                val r = c.get(url)
                if (r.status.isSuccess()) ApiResult.Ok("连接成功（HTTP " + r.status.value + "）")
                else ApiResult.Err(r.status.value, "服务器响应异常（HTTP " + r.status.value + "）")
            }
        } catch (e: Exception) {
            ClientLog.warn("连接测试失败：" + friendlyMessage(e))
            ApiResult.Err(null, friendlyMessage(e))
        }
    }

    // ---------- 登录 / 注册 ----------

    /** 登录成功后服务器返回的用户信息（对应 auth.py 的 user 对象） */
    data class LoginUser(
        val username: String,
        val realName: String,
        val role: String,
        /** 管理员重置过密码后为 true，客户端需强制引导修改密码 */
        val mustChangePassword: Boolean = false,
    )

    /**
     * POST /auth/login {username, password}
     * 成功响应：{access_token, user:{id, username, real_name, role}}
     */
    suspend fun login(username: String, password: String): ApiResult<LoginUser> {
        return try {
            client().use { c ->
                val r = c.post(configProvider().apiBase + Endpoints.Auth.LOGIN) {
                    contentType(ContentType.Application.Json)
                    setBody(mapOf("username" to username, "password" to password))
                }
                val text = r.body<String>()
                if (r.status.isSuccess()) {
                    val obj = json.parseToJsonElement(text) as? JsonObject
                    val t = obj?.get("access_token")?.jsonPrimitive?.content
                        ?: obj?.get("token")?.jsonPrimitive?.content
                        ?: (obj?.get("data") as? JsonObject)?.get("access_token")?.jsonPrimitive?.content
                    if (t != null) {
                        setToken(t)
                        val u = obj?.get("user") as? JsonObject
                        val mustChange = obj?.get("must_change_password")
                            ?.jsonPrimitive?.content?.toBooleanStrictOrNull()
                            ?: u?.get("must_change_password")
                                ?.jsonPrimitive?.content?.toBooleanStrictOrNull()
                            ?: false
                        val user = LoginUser(
                            username = u?.get("username")?.jsonPrimitive?.content ?: username,
                            realName = u?.get("real_name")?.jsonPrimitive?.content ?: "",
                            role = u?.get("role")?.jsonPrimitive?.content ?: "user",
                            mustChangePassword = mustChange,
                        )
                        ClientLog.info("登录成功")
                        ApiResult.Ok(user)
                    } else ApiResult.Err(r.status.value, "登录响应中未找到 token")
                } else ApiResult.Err(r.status.value, errMsg(r.status.value, text, null))
            }
        } catch (e: Exception) {
            ClientLog.error("登录失败", e)
            ApiResult.Err(null, friendlyMessage(e))
        }
    }

    /** GET /auth/check-first-user → {is_first: Boolean}，用于登录页「首次注册」Tab。
     * 连接失败不能伪装成“已有用户”，否则首次部署时会把管理员创建入口静默隐藏。
     */
    suspend fun checkFirstUser(): ApiResult<Boolean> {
        return try {
            client().use { c ->
                val r = c.get(configProvider().apiBase + Endpoints.Auth.CHECK_FIRST_USER)
                if (!r.status.isSuccess()) {
                    ApiResult.Err(r.status.value, "无法确认系统初始化状态，请检查服务器连接")
                } else {
                    val obj = json.parseToJsonElement(r.body<String>()) as? JsonObject
                    ApiResult.Ok(obj?.get("is_first")?.jsonPrimitive?.content == "true")
                }
            }
        } catch (e: Exception) {
            ClientLog.warn("检查首次部署状态失败：${e.message ?: e::class.simpleName}")
            ApiResult.Err(null, friendlyMessage(e))
        }
    }

    /** POST /auth/register；成功返回 {access_token, user}（自动登录） */
    suspend fun register(
        username: String, password: String, email: String,
        realName: String, department: String,
    ): ApiResult<LoginUser> = authPost(
        Endpoints.Auth.REGISTER,
        mapOf("username" to username, "password" to password, "email" to email,
            "real_name" to realName, "department" to department, "role" to "user"),
        fallbackName = username,
    )

    /** POST /auth/register-first（系统首个用户=系统管理员；成功返回 {access_token, user}） */
    suspend fun registerFirst(
        username: String, password: String, email: String,
        realName: String, department: String,
    ): ApiResult<LoginUser> = authPost(
        Endpoints.Auth.REGISTER_FIRST,
        mapOf("username" to username, "password" to password, "email" to email,
            "real_name" to realName, "department" to department, "role" to "developer"),
        fallbackName = username,
    )

    private suspend fun authPost(
        path: String, body: Map<String, String>, fallbackName: String,
    ): ApiResult<LoginUser> {
        return try {
            client().use { c ->
                val r = c.post(configProvider().apiBase + path) {
                    contentType(ContentType.Application.Json); setBody(body)
                }
                val text = r.body<String>()
                if (r.status.isSuccess()) {
                    val obj = json.parseToJsonElement(text) as? JsonObject
                    obj?.get("access_token")?.jsonPrimitive?.content?.let { setToken(it) }
                    val u = obj?.get("user") as? JsonObject
                    ApiResult.Ok(LoginUser(
                        username = u?.get("username")?.jsonPrimitive?.content ?: fallbackName,
                        realName = u?.get("real_name")?.jsonPrimitive?.content ?: "",
                        role = u?.get("role")?.jsonPrimitive?.content ?: "user",
                    ))
                } else ApiResult.Err(r.status.value, errMsg(r.status.value, text, null))
            }
        } catch (e: Exception) {
            ApiResult.Err(null, friendlyMessage(e))
        }
    }

    // ---------- 通用 JSON ----------

    /**
     * GET。默认沿用全局超时（用户在设置页可调，不在这里改）；
     * 轮询类接口由调用方显式传更小的 [timeoutMs]，让卡住的请求快速失败进入重试。
     */
    suspend fun get(
        path: String, params: Map<String, String> = emptyMap(), timeoutMs: Long? = null,
    ) = req(HttpMethod.Get, path, null, params, timeoutMs)

    suspend fun post(path: String, body: Any? = null, timeoutMs: Long? = null) =
        req(HttpMethod.Post, path, body, emptyMap(), timeoutMs)

    /**
     * 流式 POST（SSE）：用于写作起草等长耗时生成。
     * 逐行解析 `data: {...}` 事件并回调给调用方；整流结束返回 Ok(Unit)。
     * 「取消生成」走协程取消：CancellationException 原样上抛，不当作错误。
     * HTTP 层失败（含 404，服务端未部署流式接口）返回 Err，由调用方决定回退。
     */
    suspend fun postStream(
        path: String, body: Any?, timeoutMs: Long = 600_000,
        onEvent: (JsonObject) -> Unit,
    ): ApiResult<Unit> {
        val url = configProvider().apiBase + path
        return try {
            var failure: ApiResult.Err? = null
            client(timeoutMs).use { c ->
                c.preparePost(url) {
                    auth()
                    contentType(ContentType.Application.Json)
                    setBody(body.toJsonElement())
                }.execute { r ->
                    if (!r.status.isSuccess()) {
                        failure = ApiResult.Err(r.status.value,
                            errMsg(r.status.value, r.body(), null))
                        return@execute
                    }
                    val channel = r.bodyAsChannel()
                    while (!channel.isClosedForRead) {
                        val line = channel.readUTF8Line() ?: break
                        if (!line.startsWith("data:")) continue
                        val payload = line.substring(5).trim()
                        if (payload.isEmpty()) continue
                        runCatching { json.parseToJsonElement(payload) as? JsonObject }
                            .getOrNull()?.let(onEvent)
                    }
                }
            }
            failure ?: ApiResult.Ok(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ClientLog.error("流式请求 $path 失败", e)
            ApiResult.Err(null, friendlyMessage(e))
        }
    }

    suspend fun put(path: String, body: Any? = null) = req(HttpMethod.Put, path, body)

    /** 局部更新（重命名等）：与 PUT 完全同构，仅 HTTP 方法不同 */
    suspend fun patch(path: String, body: Any? = null) = req(HttpMethod.Patch, path, body)

    /**
     * POST /auth/change-password {old_password, new_password, confirm_password}
     * 服务端校验旧密码与复杂度；客户端不缓存、不记录任何密码明文。
     */
    suspend fun changePassword(oldPassword: String, newPassword: String): ApiResult<String> =
        when (val r = post(Endpoints.Auth.CHANGE_PASSWORD, mapOf(
            "old_password" to oldPassword,
            "new_password" to newPassword,
            "confirm_password" to newPassword,
        ))) {
            is ApiResult.Ok -> ApiResult.Ok("")
            is ApiResult.Err -> r
        }

    suspend fun del(path: String) = req(HttpMethod.Delete, path, null)

    private suspend fun req(
        method: HttpMethod, path: String, body: Any?,
        params: Map<String, String> = emptyMap(), timeoutMs: Long? = null,
    ): ApiResult<JsonElement> {
        val url = configProvider().apiBase + path
        return try {
            client(timeoutMs).use { c ->
                val r = when (method) {
                    HttpMethod.Get -> c.get(url) { auth(); params.forEach { (k, v) -> parameter(k, v) } }
                    HttpMethod.Delete -> c.delete(url) { auth() }
                    HttpMethod.Put -> c.put(url) {
                        auth()
                        contentType(ContentType.Application.Json)
                        body?.let { setBody(it.toJsonElement()) }
                    }
                    HttpMethod.Patch -> c.patch(url) {
                        auth()
                        contentType(ContentType.Application.Json)
                        body?.let { setBody(it.toJsonElement()) }
                    }
                    else -> c.post(url) {
                        auth()
                        contentType(ContentType.Application.Json)
                        body?.let { setBody(it.toJsonElement()) }
                    }
                }
                val text = r.body<String>()
                when {
                    r.status.isSuccess() -> ApiResult.Ok(
                        if (text.isBlank()) JsonObject(emptyMap()) else json.parseToJsonElement(text))
                    r.status.value == 401 -> {
                        setToken(null)
                        ApiResult.Err(401, "登录已过期，请重新登录")
                    }
                    else -> ApiResult.Err(r.status.value, errMsg(r.status.value, text, null))
                }
            }
        } catch (e: CancellationException) {
            // 「取消生成」是用户主动操作，不是网络失败：原样上抛让协程正常结束，
            // 不能吞掉转成 Err——否则 ViewModel 会把 "Job was cancelled" 当报错弹给用户
            throw e
        } catch (e: Exception) {
            ClientLog.error(method.value + " " + path + " 失败", e)
            ApiResult.Err(null, friendlyMessage(e))
        }
    }

    private fun HttpRequestBuilder.auth() {
        token?.let { header(HttpHeaders.Authorization, "Bearer $it") }
    }

    // ---------- 上传 ----------

    suspend fun upload(
        path: String, fileField: String, files: List<File>,
        params: Map<String, String> = emptyMap(), timeoutMs: Long = 300_000,
        formFields: Map<String, String> = emptyMap(),
    ): ApiResult<JsonElement> {
        val url = configProvider().apiBase + path
        return try {
            client(timeoutMs).use { c ->
                val r = c.submitFormWithBinaryData(url, formData {
                    formFields.forEach { (key, value) -> append(key, value) }
                    for (f in files) {
                        append(fileField, f.readBytes(), Headers.build {
                            append(HttpHeaders.ContentDisposition,
                                "form-data; name=\"$fileField\"; filename=\"${f.name}\"")
                        })
                    }
                }) {
                    auth()
                    params.forEach { (key, value) -> parameter(key, value) }
                }
                val text = r.body<String>()
                if (r.status.isSuccess()) ApiResult.Ok(
                    if (text.isBlank()) JsonObject(emptyMap()) else json.parseToJsonElement(text))
                else ApiResult.Err(r.status.value, errMsg(r.status.value, text, null))
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ClientLog.error("上传 $path 失败", e)
            ApiResult.Err(null, friendlyMessage(e))
        }
    }

    // ---------- 下载 ----------

    /**
     * 落盘下载内容并校验，避免「服务端 200 但内容是错误页」时给用户一个坏文件：
     * - 目标目录不存在 → mkdirs；
     * - 空响应体 → 不写文件，返回可读错误；
     * - `expectDocx` 且内容前 4 字节不是 zip 魔数 `PK\x03\x04` → 丢弃，不写出 .docx；
     * - 写盘后校验 `length() > 0`。
     * 返回 null 表示成功；返回非 null 为给用户看的错误提示。
     */
    private fun writeDownloadChecked(body: ByteArray, target: File, expectDocx: Boolean): String? {
        if (body.isEmpty()) {
            ClientLog.error("下载内容为空，未写出 " + target.name)
            return "服务端返回内容为空，未生成文件"
        }
        if (expectDocx && !isZipDocx(body)) {
            val head = body.take(8).joinToString(" ") { "%02X".format(it.toInt() and 0xFF) }
            ClientLog.error("下载内容不是有效 docx（前 8 字节=$head），已丢弃，未写出 " + target.name)
            return "服务端返回的不是有效的 docx 文件，已取消保存"
        }
        target.parentFile?.mkdirs()
        target.writeBytes(body)
        if (target.length() <= 0L) {
            ClientLog.error("文件写入后为空：" + target.absolutePath)
            return "文件写入失败，目标文件为空"
        }
        return null
    }

    /** docx（OOXML）是 zip，魔数固定为 PK\x03\x04 */
    private fun isZipDocx(body: ByteArray): Boolean =
        body.size >= 4 && body[0] == 0x50.toByte() && body[1] == 0x4B.toByte() &&
            body[2] == 0x03.toByte() && body[3] == 0x04.toByte()

    suspend fun downloadGet(path: String, target: File, timeoutMs: Long = 300_000): ApiResult<String> {
        val url = configProvider().apiBase + path
        return try {
            client(timeoutMs).use { c ->
                val r = c.get(url) { auth() }
                if (r.status.isSuccess()) {
                    val err = writeDownloadChecked(r.body(), target,
                        expectDocx = target.name.endsWith(".docx", ignoreCase = true))
                    if (err != null) ApiResult.Err(r.status.value, err)
                    else {
                        ClientLog.info("下载成功 " + target.name)
                        ApiResult.Ok("已保存：" + target.absolutePath)
                    }
                } else ApiResult.Err(r.status.value, errMsg(r.status.value, r.body(), null))
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ClientLog.error("下载 $path 失败", e)
            ApiResult.Err(null, friendlyMessage(e))
        }
    }

    /**
     * POST 导出（请求体 + 落盘文件）。
     *
     * [timeoutMs] 默认 5 分钟（与加参数前完全一致，其它调用点行为不变）。
     * PPTAgent 这类 5–15 分钟的长任务由调用方显式传更长的超时（见 PptRepository），
     * 这里**不改全局默认超时**：全局超时是用户在设置页可调的，动它会波及所有接口。
     * 另：socketTimeoutMillis 与 requestTimeoutMillis 绑的是同一个值（见 client()），
     * 所以放宽请求超时不会出现「socket 空闲超时先炸」。
     */
    suspend fun downloadPost(
        path: String, body: Map<String, Any?>, target: File, timeoutMs: Long = 300_000,
    ): ApiResult<String> {
        val url = configProvider().apiBase + path
        return try {
            client(timeoutMs).use { c ->
                val r = c.post(url) {
                    auth(); contentType(ContentType.Application.Json); setBody(body.toJsonElement())
                }
                if (r.status.isSuccess()) {
                    val err = writeDownloadChecked(r.body(), target,
                        expectDocx = target.name.endsWith(".docx", ignoreCase = true))
                    if (err != null) ApiResult.Err(r.status.value, err)
                    else {
                        ClientLog.info("导出成功 " + target.name)
                        ApiResult.Ok("已保存：" + target.absolutePath)
                    }
                } else ApiResult.Err(r.status.value, errMsg(r.status.value, r.body(), null))
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ClientLog.error("导出 $path 失败", e)
            ApiResult.Err(null, friendlyMessage(e))
        }
    }

    /**
     * 拉取图片字节（模板预览图、PPT 逐页预览图等）。
     *
     * 带上 token：预览图接口（/ppt/preview/...、/ppt/jobs/{id}/preview/{i}，后者返回的是
     * PPTAgent 的真实字节，实测为 jpg 但由 Skia 按字节嗅探解码，不依赖扩展名与 MIME）
     * 都是 `Depends(get_current_user)`，不带 Authorization 会 401，
     * 界面上就永远是「生成中」占位图而看不到图。
     */
    suspend fun imageBytes(pathOrUrl: String): ByteArray? {
        val url = if (pathOrUrl.startsWith("http")) pathOrUrl
        else configProvider().baseUrl.trimEnd('/') + pathOrUrl
        return try {
            client().use { c ->
                val r = c.get(url) { auth() }
                if (r.status.isSuccess()) r.body<ByteArray>() else null
            }
        } catch (e: Exception) { null }
    }
}
