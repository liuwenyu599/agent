# WSL2 本地打包 Linux（麒麟/统信）客户端 · 操作手册

> 全程在**你自己的 Windows 机器**上完成，**不需要连服务器**。
> 目标：产出 `yunfazhiban-1.1.0.deb`（x86_64），供麒麟 / 统信 UOS 安装。
> 依据：`desktop/build-linux.sh`（已合入 `8032c02`）。

---

## 前置：为什么建议在 WSL 里做，而不是借 Linux 机器

| | WSL2 | 借物理机 |
|---|---|---|
| 准备成本 | 本机装一下即可 | 要借/租、要装 JDK |
| 产物可读性 | 产物直接在 `D:\` 下，取用方便 | 要拷贝回来 |
| 适合阶段 | **首次打通链路、排错** | 最终正式打包 |

---

## 第 1 步：确认 WSL2 已安装

在 **PowerShell** 里跑：

```powershell
wsl --status
wsl -l -v
```

看 `VERSION` 列，**必须是 2**。

### 如果没有或版本是 1

```powershell
wsl --install -d Ubuntu-22.04
```

装完**重启电脑**，然后：

```powershell
wsl --set-version Ubuntu-22.04 2      # 把已有 WSL1 转成 WSL2
```

---

## 第 2 步：装 JDK 与打包工具

打开 **Ubuntu**（开始菜单搜 Ubuntu，或 `wsl -d Ubuntu-22.04`）：

```bash
sudo apt update
sudo apt install -y openjdk-17-jdk fakeroot rpm
```

验证：

```bash
java -version        # 应为 17.x
which fakeroot       # 必须有，jpackage 打 deb 靠它设置文件属主
```

> ⚠️ `fakeroot` 缺了会在打包时报错，这是最常见的第一个坑。

### 建议：换国内镜像（Gradle 拉依赖慢）

```bash
sudo sed -i 's@//.*archive.ubuntu.com@//mirrors.tuna.tsinghua.edu.cn@g' /etc/apt/sources.list
sudo apt update
```

---

## 第 3 步：把项目拷进 WSL 原生目录（重要提速点）

**不要**在 `/mnt/d/...` 下直接跑 Gradle——WSL 访问 Windows 文件系统很慢，Gradle 大量小文件读写会慢到无法忍受。

```bash
mkdir -p ~/build
cp -r /mnt/d/Projects/judicial_app ~/build/
cd ~/build/judicial_app/desktop
```

> 副本与主仓库会分叉，**打包完不要把构建产物拷回主仓库**，只取 `.deb` 即可。

---

## 第 4 步：预热 Gradle 依赖（关键，只做一次）

首次构建会下载 Linux 版原生库（`skiko-awt-runtime-linux-x64` 等），这一步必须联网。

```bash
cd ~/build/judicial_app/desktop
chmod +x gradlew
./gradlew packageDeb --no-daemon
```

**这一条命令基本决定成败**，把全部输出保存下来：

```bash
./gradlew packageDeb --no-daemon 2>&1 | tee ~/build/deb-build.log
```

- **能跑完** → 后面用 `--offline` 就不需要网了
- **失败** → 把 `~/build/deb-build.log` 的**末尾 50 行**贴给我

---

## 第 5 步：用封装脚本打包（推荐）

依赖预热成功后，走现成脚本（它会自动探测架构、检查 JDK/图标、拦截架构误配、核对包的 Architecture 字段）：

```bash
cd ~/build/judicial_app/desktop
bash build-linux.sh 2>&1 | tee ~/build/linux-build.log
```

### 成功长这样

```
==> 0/5 环境自检
  [ OK ] 构建机架构：x86_64（将产出 x86_64 包）
  [ OK ] JDK 17
  [ OK ] 包名 YunFaZhiBan / 版本 1.1.0 / 图标 app_logo.png 齐备
==> 1/5 编译 Kotlin（JVM）
==> 2/5 打包原生分发（x86_64）
==> 3/5 收集产物
  [ OK ] deb: .../yunfazhiban-1.1.0-amd64.deb (xxx MB)
==> 4/5 校验包架构
  [ OK ] deb 声明架构：amd64
```

---

## 第 6 步：取回产物

```bash
# 产物在 WSL 内，先确认
ls -lh ~/build/judicial_app/desktop/build/compose/binaries/main/deb/

# 拷回 Windows 桌面
cp ~/build/judicial_app/desktop/build/compose/binaries/main/deb/*.deb /mnt/c/Users/$USER/Desktop/
```

Windows 侧路径：`C:\Users\小鱼\Desktop\`

---

## 第 7 步：装到目标机器验证

把 `.deb` 拷到目标 Linux 机器，然后：

```bash
sudo dpkg -i yunfazhiban-1.1.0-amd64.deb

# 若报缺依赖
sudo apt-get install -f     # 麒麟 / Ubuntu
# sudo dnf install -f      # 统信 / 欧拉

# 查客户端配置（Linux 下 APPDATA 不存在，落在用户主目录）
cat ~/JudicialAIDesktop/server.json
# 把 baseUrl 改成 http://10.128.85.133:8000
```

连通判定（地址通了返回 2xx）：

```bash
curl -o /dev/null -s -w '%{http_code}\n' http://10.128.85.133:8000/docs
```

写作台现在按服务端公文格式规则选择字体。目标麒麟机器上检查中文字体：

```bash
fc-match 'Noto Serif CJK SC'
fc-match 'Noto Sans CJK SC'
```

若没有仿宋、楷体等公文字体，客户端会选用已安装的 Noto 中文字体；
建议在目标机部署获许可的公文字体或系统提供的 Noto CJK 字体，并打开一份通知与导出 Word 对照检查。

---

## 排错速查

| 报错关键字 | 原因 | 处理 |
|---|---|---|
| `fakeroot: command not found` | 缺 fakeroot | `sudo apt install fakeroot` |
| `Cannot find libskiko-linux-x64.so` | 原生库没下下来 | 联网重跑第 4 步 |
| `Unsupported class file major version` | JDK 版本不对 | 确认是 17 |
| `no root filesystems found` | 构建在 `/mnt/` 下 | 按第 3 步拷到 `~/build` |
| Gradle 卡在下载不动 | 网络慢 | 用国内镜像，或加代理 |
| `dpkg-deb: not found` | 校验步骤跳过 | 不影响打包，可忽略 |

---

## 之后（内网环境）

第一次成功、依赖已缓存后，**断网也能构建**：

```bash
./gradlew packageDeb --offline
```

若要把缓存带进内网：

```bash
tar czf gradle-cache-$(date +%Y%m%d).tgz -C ~ .gradle    # 约数百 MB
```

内网机器解包到 `~/.gradle` 后用 `--offline` 即可。

---

## 成功标准

- [ ] WSL2 + JDK 17 + fakeroot 就绪
- [ ] `packageDeb` 首次联网跑通
- [ ] `build-linux.sh` 输出 `[ OK ] deb 声明架构：amd64`
- [ ] `.deb` 拷回 Windows 桌面
- [ ] 目标机器 `dpkg -i` 成功、客户端界面正常显示
- [ ] `~/JudicialAIDesktop/server.json` 的 `baseUrl` 已指向生产
