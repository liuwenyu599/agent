// TargetFormat：恢复 jpackage 原生 exe/msi 打包时才需要，见下方 nativeDistributions 注释
// import org.jetbrains.compose.desktop.application.dsl.TargetFormat

plugins {
    kotlin("multiplatform") version "2.0.21"
    id("org.jetbrains.compose") version "1.7.0"
    id("org.jetbrains.kotlin.plugin.compose") version "2.0.21"
    kotlin("plugin.serialization") version "2.0.21"
}

repositories {
    google()
    mavenCentral()
    maven("https://maven.pkg.jetbrains.space/public/p/compose/dev")
}

kotlin {
    jvmToolchain(17)

    jvm()

    sourceSets {
        val jvmMain by getting {
            dependencies {
                implementation(compose.desktop.currentOs)
                implementation(compose.material)
                implementation(compose.materialIconsExtended)

                implementation("io.ktor:ktor-client-core:3.0.1")
                implementation("io.ktor:ktor-client-cio:3.0.1")
                implementation("io.ktor:ktor-client-content-negotiation:3.0.1")
                implementation("io.ktor:ktor-serialization-kotlinx-json:3.0.1")

                implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
                implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.9.0")
                implementation("org.jetbrains.kotlinx:kotlinx-coroutines-swing:1.9.0")

                // 本地数据层（用户业务数据与模型运行缓存分离，schemaVersion 迁移）
                implementation("org.xerial:sqlite-jdbc:3.46.1.3")
            }
        }
    }
}

compose.desktop {
    application {
        mainClass = "com.judicialai.desktop.MainKt"

        nativeDistributions {
            // 不再产出 jpackage 自带的 exe / msi 安装包：
            // jpackage 的 --name 会同时决定 exe 名、安装目录名和快捷方式名，三者拆不开，
            // 快捷方式只能是英文。安装包统一交给 installer/setup.iss（Inno Setup 6）：
            //   gradlew createDistributable  -> app image（YunFaZhiBan.exe + 自带 JRE）
            //   installer\build-installer.ps1 -> 云法智办-安装程序-<版本>.exe
            // 若哪天真需要 jpackage 原生包，把下面这行和文件头的 import 一起加回来：
            // targetFormats(TargetFormat.Msi, TargetFormat.Exe)

            packageName = "YunFaZhiBan"   // 必须是纯 ASCII：决定 exe 文件名（jpackage 限制）
            packageVersion = "1.0.0"      // 必须是数字（MSI 版本号限制）
            vendor = "云法智办"

            windows {
                // 图标仍由 jpackage 打进 app image，createDistributable 会用到
                iconFile.set(project.file("app_logo.ico"))
            }
        }
    }
}

