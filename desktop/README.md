# 云法智办 YunFaZhiBan（司法智能办公辅助平台 · 桌面端）

Compose Desktop 客户端，界面与交互 1:1 对齐 Web 端（Element Plus 风格）：
深色侧边栏（#16223f，可折叠）、56px 白色顶栏、蓝渐变登录页（登录/注册/首次注册三 Tab）、
首页 Banner + 快速入口六宫格、信息写作会话侧栏与气泡消息、模板中心搜索/分类/预览、
公文要素填写生成、格式校验统计卡与问题表、工作流模板卡片与节点生成、PPT 助手、
管理后台（数据概览/用户管理/知识库管理/文档审核/会话管理，仅管理员可见）。

## 架构

App + Core + Data + Design + Features 分层：

- `app/` 应用生命周期、全局状态（AppState）、导航（AppScreen/AppMenu）
- `core/` 跨业务基础设施：network（ApiClient/ApiResult/Endpoints）、storage（ServerConfig）、
  logging（ClientLog）、platform（文件选择）、utils（JsonExt）
- `data/` 数据层装配：Repositories 统一管理各 feature Repository 单例
- `design/` 设计系统：theme（Color/Typography/Shape/Theme，色值全部取自 Web 端 CSS）、
  components（AppSidebar/AppCard/StateViews）、layout（AppShell）
- `features/` 业务域，每个域自持 Screen + ViewModel + Repository：
  auth（登录）、dashboard（首页）、chat（智能写作）、knowledge（知识库）、
  templates（公文助手/模板中心）、formatcheck（格式校验）、ppt（PPT助手）、
  workflow（工作流）、admin（管理后台）、settings（服务器连接设置）

规则：
- Main.kt 只启动窗口，无业务逻辑
- feature 之间不互相访问内部 ViewModel/组件
- API/日志/配置/文件系统只在 core 与 Repository 中出现
- token 仅存内存；日志不记密码/token/文件内容；地址全部来自 ServerConfig
- 管理后台按角色显示（developer/knowledge_admin/admin），非管理员直接访问会被路由守卫拦回首页

## 运行

```bash
./gradlew run                   # 开发运行
./gradlew createDistributable   # 产出 app image（含自带 JRE）
                                #   -> build/compose/binaries/main/app/YunFaZhiBan/
```
Windows 安装包（中文名 + 中文桌面快捷方式）由 Inno Setup 从 app image 打包：

```powershell
.\installer\build-installer.ps1            # 先 createDistributable，再 iscc
.\installer\build-installer.ps1 -SkipBuild # 已有 app image 时只重打安装包
# -> build/installer/云法智办-安装程序-<版本>.exe
```

说明：jpackage 自带的 exe/msi **不再产出**——jpackage 的 `--name` 同时决定 exe 名、
安装目录名和快捷方式名，三者拆不开，快捷方式只能是英文 `YunFaZhiBan`。
所以 exe 名保持英文（jpackage 限制），中文显示名 / 桌面快捷方式 / 开始菜单
全部交给 `installer/setup.iss`。

