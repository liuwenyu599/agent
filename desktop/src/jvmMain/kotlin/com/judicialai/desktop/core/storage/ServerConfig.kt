package com.judicialai.desktop.core.storage

import com.judicialai.desktop.core.logging.ClientLog
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File

/**
 * 服务器配置。全应用唯一地址来源，禁止在页面代码硬编码任何地址。
 * 持久化到用户应用配置目录（Windows: %APPDATA%/JudicialAIDesktop/server.json）。
 */
@Serializable
data class ServerConfig(
    val baseUrl: String = "http://127.0.0.1:8000",
    val connectTimeoutMillis: Long = 10_000,
    val requestTimeoutMillis: Long = 120_000,
) {
    val apiBase: String get() = baseUrl.trimEnd('/') + "/api/v1"

    companion object {
        private val json = Json { prettyPrint = true; ignoreUnknownKeys = true }

        val configDir: File by lazy {
            val appData = System.getenv("APPDATA")
            val base = if (!appData.isNullOrBlank()) File(appData)
            else File(System.getProperty("user.home"))
            File(base, "JudicialAIDesktop").apply { mkdirs() }
        }

        private val configFile: File get() = File(configDir, "server.json")

        fun load(): ServerConfig {
            return try {
                if (!configFile.isFile) return ServerConfig()
                json.decodeFromString(serializer(), configFile.readText(Charsets.UTF_8))
            } catch (e: Exception) {
                ServerConfig()
            }
        }

        fun save(cfg: ServerConfig) {
            try {
                configFile.writeText(json.encodeToString(serializer(), cfg), Charsets.UTF_8)
            } catch (e: Exception) {
                ClientLog.error("保存服务器配置失败", e)
            }
        }
    }
}

