package com.judicialai.desktop.core.logging

import com.judicialai.desktop.core.storage.ServerConfig
import java.io.File
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/**
 * 客户端日志：写入用户应用配置目录 logs/。
 * 红线：禁止记录密码、Token、Authorization 头、文件内容、敏感司法数据。
 */
object ClientLog {
    private val timeFmt = DateTimeFormatter.ofPattern("HH:mm:ss.SSS")

    private fun logFile(): File {
        val dir = File(ServerConfig.configDir, "logs").apply { mkdirs() }
        return File(dir, "client-" + LocalDate.now() + ".log")
    }

    private fun write(level: String, msg: String, e: Throwable?) {
        val line = buildString {
            append(LocalDateTime.now().format(timeFmt))
            append(" [").append(level).append("] ").append(msg)
            e?.let { append(" | ").append(it.javaClass.simpleName).append(": ").append(it.message) }
        }
        try { logFile().appendText(line + "\n", Charsets.UTF_8) } catch (_: Exception) { }
    }

    fun info(msg: String) = write("INFO", msg, null)
    fun warn(msg: String) = write("WARN", msg, null)
    fun error(msg: String, e: Throwable? = null) = write("ERROR", msg, e)
}

