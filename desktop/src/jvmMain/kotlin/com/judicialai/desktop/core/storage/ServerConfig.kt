package com.judicialai.desktop.core.storage

import com.judicialai.desktop.core.logging.ClientLog
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File

/**
 * 服务器配置。全应用唯一地址来源，禁止在页面代码硬编码任何地址。
 * 持久化到用户应用配置目录（Windows: %APPDATA%/JudicialAIDesktop/server.json；
 * Linux 无 APPDATA 环境变量，回退到 ~/JudicialAIDesktop/server.json）。
 */
@Serializable
data class ServerConfig(
    val baseUrl: String = DEFAULT_BASE_URL,
    val connectTimeoutMillis: Long = 10_000,
    val requestTimeoutMillis: Long = 120_000,
) {
    val apiBase: String get() = baseUrl.trimEnd('/') + "/api/v1"

    companion object {
        /**
         * 内网生产地址。改这里等于改所有新装客户端的默认后端。
         * 交付版固定指向生产，本机8000 端口常被 VS Code 占用，且客户端不在
         * 服务器所在机器上，回环地址永远连不通。
         */
        const val DEFAULT_BASE_URL = "http://10.128.85.133:8000"

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
                val cfg = json.decodeFromString(serializer(), configFile.readText(Charsets.UTF_8))
                migrateLegacyDefaults(cfg)
            } catch (e: Exception) {
                ServerConfig()
            }
        }

        /**
         * 把历史遗留的回环地址自动升级为当前默认值。
         *
         * 为什么需要：`load()` 只在**文件不存在**时才用默认值。一旦用户（或旧版）
         * 落过盘，配置里就固化了当时的地址，后续升级包改默认值对它无效——
         * 表现为「明明装了新版，还是连 127.0.0.1 连不上」。
         *
         * **为什么回环地址可以一律迁移、而不必逐个精确匹配：**
         * 交付版客户端运行在**用户的办公机**上，后端在另一台内网服务器。
         * 用户机器上**永远不存在**本机后端服务，所以任何指向
         * `localhost` / `127.0.0.1` / `0.0.0.0` 的地址（不论端口、不论写法）
         * 都是无意义的残留值，不是用户的真实意图。
         * 唯一例外是开发机自测——那种场景不该用交付包。
         *
         * 非回环地址（内网 IP / 域名）一律不动：那是用户或管理员有意配置的，
         * 覆盖它等于擅自改变部署目标。
         *
         * 迁移后立即落盘，避免每次启动都判一次。
         */
        private fun migrateLegacyDefaults(cfg: ServerConfig): ServerConfig {
            if (!isLoopback(cfg.baseUrl)) return cfg
            val migrated = cfg.copy(baseUrl = DEFAULT_BASE_URL)
            save(migrated)
            ClientLog.info(
                "服务器地址已从无效的回环地址 ${cfg.baseUrl} 自动升级为 $DEFAULT_BASE_URL"
            )
            return migrated
        }

        /**
         * 判断地址是否指向本机回环。
         *
         * 覆盖 `127.0.0.1` / `localhost` / `0.0.0.0` / IPv6 回环 `::1`，
         * 任意端口、任意大小写、末尾斜杠都算。
         */
        private fun isLoopback(rawUrl: String): Boolean {
            // 去掉 scheme、末尾斜杠与路径，只留 host[:port]
            val host = rawUrl.trim().removePrefix("http://").removePrefix("https://")
                .substringBefore('/').substringBefore('\\').trim().trimEnd('/')
            val hostOnly = host.substringBeforeLast(':').trim('[', ']').lowercase()
            return hostOnly == "127.0.0.1" ||
                hostOnly == "localhost" ||
                hostOnly == "0.0.0.0" ||
                hostOnly == "::1" ||
                hostOnly == "::"
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

