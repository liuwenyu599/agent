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
import io.ktor.client.request.post
import io.ktor.client.request.put
import io.ktor.client.request.setBody
import io.ktor.http.ContentType
import io.ktor.http.Headers
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.contentType
import io.ktor.http.isSuccess
import io.ktor.serialization.kotlinx.json.json
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
            body?.let { (json.parseToJsonElement(it) as? JsonObject) }
                ?.get("detail")?.jsonPrimitive?.content
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
                        val user = LoginUser(
                            username = u?.get("username")?.jsonPrimitive?.content ?: username,
                            realName = u?.get("real_name")?.jsonPrimitive?.content ?: "",
                            role = u?.get("role")?.jsonPrimitive?.content ?: "user",
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

    /** GET /auth/check-first-user → {is_first: Boolean}，用于登录页「首次注册」Tab */
    suspend fun checkFirstUser(): Boolean {
        return try {
            client().use { c ->
                val r = c.get(configProvider().apiBase + Endpoints.Auth.CHECK_FIRST_USER)
                if (!r.status.isSuccess()) return false
                val obj = json.parseToJsonElement(r.body<String>()) as? JsonObject
                obj?.get("is_first")?.jsonPrimitive?.content == "true"
            }
        } catch (e: Exception) {
            false
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

    suspend fun get(path: String, params: Map<String, String> = emptyMap()) =
        req(HttpMethod.Get, path, null, params)

    suspend fun post(path: String, body: Any? = null, timeoutMs: Long? = null) =
        req(HttpMethod.Post, path, body, emptyMap(), timeoutMs)

    suspend fun put(path: String, body: Any? = null) = req(HttpMethod.Put, path, body)

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
    ): ApiResult<JsonElement> {
        val url = configProvider().apiBase + path
        return try {
            client(timeoutMs).use { c ->
                val r = c.submitFormWithBinaryData(url, formData {
                    for (f in files) {
                        append(fileField, f.readBytes(), Headers.build {
                            append(HttpHeaders.ContentDisposition,
                                "form-data; name=\"$fileField\"; filename=\"${f.name}\"")
                        })
                    }
                }) {
                    auth()
                    params.forEach { (k, v) -> parameter(k, v) }
                }
                val text = r.body<String>()
                if (r.status.isSuccess()) ApiResult.Ok(
                    if (text.isBlank()) JsonObject(emptyMap()) else json.parseToJsonElement(text))
                else ApiResult.Err(r.status.value, errMsg(r.status.value, text, null))
            }
        } catch (e: Exception) {
            ClientLog.error("上传 $path 失败", e)
            ApiResult.Err(null, friendlyMessage(e))
        }
    }

    // ---------- 下载 ----------

    suspend fun downloadGet(path: String, target: File, timeoutMs: Long = 300_000): ApiResult<String> {
        val url = configProvider().apiBase + path
        return try {
            client(timeoutMs).use { c ->
                val r = c.get(url) { auth() }
                if (r.status.isSuccess()) {
                    target.writeBytes(r.body())
                    ClientLog.info("下载成功 " + target.name)
                    ApiResult.Ok("已保存：" + target.absolutePath)
                } else ApiResult.Err(r.status.value, errMsg(r.status.value, r.body(), null))
            }
        } catch (e: Exception) {
            ClientLog.error("下载 $path 失败", e)
            ApiResult.Err(null, friendlyMessage(e))
        }
    }

    suspend fun downloadPost(path: String, body: Map<String, Any?>, target: File): ApiResult<String> {
        val url = configProvider().apiBase + path
        return try {
            client(300_000).use { c ->
                val r = c.post(url) {
                    auth(); contentType(ContentType.Application.Json); setBody(body.toJsonElement())
                }
                if (r.status.isSuccess()) {
                    target.writeBytes(r.body())
                    ClientLog.info("导出成功 " + target.name)
                    ApiResult.Ok("已保存：" + target.absolutePath)
                } else ApiResult.Err(r.status.value, errMsg(r.status.value, r.body(), null))
            }
        } catch (e: Exception) {
            ClientLog.error("导出 $path 失败", e)
            ApiResult.Err(null, friendlyMessage(e))
        }
    }

    /** 拉取图片字节（模板预览图等） */
    suspend fun imageBytes(pathOrUrl: String): ByteArray? {
        val url = if (pathOrUrl.startsWith("http")) pathOrUrl
        else configProvider().baseUrl.trimEnd('/') + pathOrUrl
        return try {
            client().use { c ->
                val r = c.get(url)
                if (r.status.isSuccess()) r.body<ByteArray>() else null
            }
        } catch (e: Exception) { null }
    }
}

