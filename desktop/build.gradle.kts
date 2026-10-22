// Linux 目标格式（Deb/Rpm）需要 TargetFormat；Windows 仍走 app image + Inno Setup
import org.jetbrains.compose.desktop.application.dsl.TargetFormat

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
            // ── Windows：app image + Inno Setup 安装包 ──
            // 不产出 jpackage 自带的 exe / msi：jpackage 的 --name 会同时决定
            // exe 名、安装目录名和快捷方式名，三者拆不开，快捷方式只能是英文。
            //   gradlew createDistributable  -> app image（YunFaZhiBan.exe + 自带 JRE）
            //   installer\build-installer.ps1 -> 云法智办-安装程序-<版本>.exe
            //
            // ── Linux（麒麟 / 统信UOS）：jpackage 产出 deb + rpm ──
            // ⚠️ jpackage **不支持交叉编译**：Linux 包必须在 Linux 上构建，
            //    ARM64 包必须在 ARM64 机器上构建（Windows 上打不出 deb）。
            //    构建线因此是三条：Windows x64 / Linux x64 / Linux aarch64。
            targetFormats(TargetFormat.Deb, TargetFormat.Rpm)

            packageName = "YunFaZhiBan"   // 必须是纯 ASCII：决定包名与安装目录名
            packageVersion = "1.1.4"      // 必须是数字（MSI 与 deb 版本号限制）
            vendor = "云法智办"
            description = "白云区司法局智慧办公平台"

            windows {
                // 图标仍由 jpackage 打进 app image，createDistributable 会用到
                iconFile.set(project.file("app_logo.ico"))
                menuGroup = "云法智办"
                // 与 installer/setup.iss 的 AppId 保持一致，覆盖安装才认得旧版本
                upgradeUuid = "4C45073E-DC1F-4261-A8AD-BB3F20C1926C"
            }

            linux {
                // deb/rpm 用 png，不能用 ico
                iconFile.set(project.file("app_logo.png"))
                packageName = "yunfazhiban"
                debMaintainer = "yunfazhiban@localhost"
                appCategory = "Office"
                menuGroup = "Office"
            }
        }
    }
}

