# 今日问题清单（供另一 AI 验证）— 修正版 v2

> 基于你给的清单合并修正，纠正 6 处硬错误。所有代码位置/commit 均已用 `git`、`grep` 实测核对。
> 核实时间：2026-10-06 23:35

## 0. 必读：部署时间线（决定"是否已验证"）

| 时间 | 事件 |
|---|---|
| 16:30 | 服务器最后 rebuild → 镜像 `20261006-162519-217f123`，部署的是 **`217f123`** |
| 17:46 / 18:13 / 18:43 | 修复 commit `d435813` / `3858661` / `93fe0f7`（均在 217f123 之后产生） |
| **18:30** | **用户跑 smoke_test 验收——服务器跑的是不含任何修复的 `217f123`** |
| 18:48 / 23:0x | 用户自己的 `079c356`（字体修复）/ `b929f43`（文档+脚本） |

**关键推论**：

1. 18:30 那次跑测中「`××`/`缺少事实依据`/`（参考`/`⚠️` 全 0 次」**不能证明修复有效**，只是该次模型生成恰好没吐这些串（run-to-run 方差）。
   **反证：同一份 `217f123` 在此前 T1/T2 吐了 `（缺少事实依据）×6`。**
2. 三件套值全来自 smoke 脚本第 93 行**硬编码的 `planned_context`** → **根本没触发 B1兜底逻辑**。
3. B2 是**桌面端**改动，smoke_test 是**纯 API 调用、完全绕过桌面端** → B2 未被验证。

→ **所有"已改"项在部署+rebuild 前，一律视为「未验证」。**

---

## 一、写作模块

| # | 现象 | 证据来源 | 真实性 | 状态 | 位置 |
|---|---|---|---|---|---|
| A1 | 点「新建任务」后主题/正文是上一个任务 | 用户截图 + 客户端复现 | ✅ 真实 | 🟡 已改未部署 | `WritingViewModel.kt` `openTask` 加 `pendingWritingTaskId` 护栏（`3858661`） |
| A2 | 落款重复两套（`××年××月/××日` + 机关/日期） | 用户截图 v4 | ✅ 真实 | 🟡 已改未部署 | `structured_field_service._canonicalize_body` 新增 `_PLACEHOLDER_LINE_RE`（`3858661`） |
| A3 | 日期占位符 `××` 未填充 | 同上截图 | ✅ 真实 | 🟡 已改未部署 | 同 A2（canonicalize 剥离）+ `_today_doc_date()`（`d435813`） |
| A4 | 发文机关名不全（"白云司法局"而非"广州市白云区司法局"） | 用户截图 | ✅ 真实 | ❌ **未修**（P1） | `seed_v3.py:121` `org.name` 值本身是简称 → **B1 兜底会给简称，本项仍会复现** |
| A5 | 结尾标点 `。，` 连用 | 用户截图（"…落实。，要及时…"） | ✅ 真实 | 🟡 已改未部署 | `postprocessor.fix_redundant_comma_after_period`（`3858661`） |
| A6 | 引用标注混入正文（`（缺少事实依据）`/`（参考资料1）`） | T1/T2 生成结果 | ✅ 真实 | 🟡 已改未部署 | P0：删 `task_service.py` `DRAFT_RULES`/`REVISION_RULES` 标注指令（`d435813`）；`canonicalize._INLINE_CITATION_RE`（`3858661`） |
| A7 | 格式三件套（标题/主送/落款/日期）缺失 | T1/T2 生成结果 | ✅ 真实 | 🟡 已改未部署 | `task_service.create_task` + `_default_authority()`（取 `org.name`）+ `_today_doc_date()`（`d435813`）；桌面端 planned_context 透传 + required 校验（B2，同 commit） |
| **A8** | **助手与文档状态不同步**（助手说"就差文种了"，文档已有 569 字 v2） | 用户截图 | ✅ 真实 | ❌ **未修**（P1） | ⚠️ **原始清单的 A7，改版中丢失，此处恢复**。助手对话上下文与文档状态未同步，待定位 |
| A9 | 乱码（`法??副校长`） | 用户首次贴的文本 | ✅ 真实（第二版消失） | ❌ 未修 | 待定位 |
| A10 | 字数失控（"要么太多要么太少"） | 用户口头反馈 | ⚠️ **未量化** | ❌ 未修 | 见 E2 |

> 编号说明：原始清单的 **A7（助手文档不同步）** 在改版中被替换为"三件套缺失"，该条已丢失；上表以 **A8** 恢复。

---

## 二、PPT 模块

| # | 现象 | 证据来源 | 真实性 | 状态 | 位置 |
|---|---|---|---|---|---|
| B1 | 卡在 `inspect_slide` 循环，无最终 pptx | `fc037fd2` 日志：11 错→4 错，无 finalize | ✅ 真实 | ❌ 未修 | `deploy/pptagent/roles/Design.yaml`（每页 inspect≤2 轮可能不足）/ host `main.py` `max_turns=10` |
| B2 | `SyntaxError: unterminated string literal` 未拦 | ppt-host 日志 | ✅ 真实 | ❌ 未修 | sandbox 执行层缺 `ast.parse` 静态预检 |
| B3 | 重复关键字参数（**B2 的真实根因**）：`color=A, color=B`、`fontsize=20, fontsize=20` | 模型输出代码，日志可见 | ✅ 真实 | ❌ 未修 | 与 B2 同一机制，预检可一并拦 |
| B4 | 无限造图循环（`generate_images.py` 重写 3+ 次） | 08:58–09:02 日志 | ✅ 真实 | ❌ 未修 | 需"同一错误重复 2 次即中止"闸门 |
| **B5** | 质量闸误拦 Liberation Sans → AI 产物被拒 | 日志 + 代码 | ✅ 真实 | ✅ **已修并已 push** | ⚠️ **订正**：实际是 `service.py:309`（不是 315）；`079c356` 已把 `risky_fonts` 从 `("dejavu","liberation sans")` 改为 `("dejavu")` |
| B6 | 静默 fallback：AI 失败但用户不知道，拿到本地渲染 | `agent_job.py:_fallback_local` + `_finish`(400-427) 各分支 | ✅ 真实 | 🟡 治标已改未部署 | `PptJobState.kt` `pptRendererNote` 原恒返回 null；`93fe0f7` 已实现告警。**治本需修 B1/B7** |
| B7 | 一次 POST 触发两次 Research loop（`5c696953` 4 页 / `cf7ffcc7` 8 页，差 17 秒） | 日志：一次 POST + 两个 loop | ✅ 真实 | ❌ 未修 | **后端已排除**：`queued_agent_job.py:171-181` 同 doc_id 去重、`:183-188` 同用户 409 互斥；质量闸 1 次 `_retry_generate` 是**同页数**。反向线索：`loop-`名是 **PPTAgent host** 打的（后端线程名 `ppt-job-<docid8>` 不带 loop-）→ 指向 host 侧 `send_message` 被跑两次 |
| B8 | 重试失败信息 `null`（`PPTAgentError: 处理失败null`） | 日志 | ✅ 真实 | ❌ 未修 | `agent_job.py` `_retry_generate` 异常处理（异常信息未拼接） |
| B9 | DejaVu Sans 未被 YAML 约束拦住（模型输出 `fontname='DejaVu Sans'`） | 模型输出 | ✅ 真实 | ❌ 未修 | `deploy/pptagent/roles/Research.yaml` / `Design.yaml`（约束存在但未生效，需查是否被英文名绕过） |
| B10 | AI 产物含疑似不实数据（`1620件` / `85.2%`） | `cf7ffcc7` manuscript.md | ⚠️ **待人工核对，暂不定性为"编造"** | ❌ 未修 | ⚠️ **订正**：这是 PPTAgent 生成的**演示数据**，未核对原始材料，不能直接定性编造 |
| B11 | AI 产物 457K 未传到客户端，客户端拿到 39K 本地渲染版 | 目录对比 + fallback 日志 | ✅ 真实 | ⚠️ 同 B6（治标已改，治本未修） | 与 B6 同根（`_fallback_local`） |
| **B12** | `/api/v1/ppt/jobs/{id}` 端点 404（只有 `/status`、`/preview`） | 实测 grep：该裸路由计数 = 0 | ✅ 真实 | ❌ 未修（P2，非阻塞） | ⚠️ **原始清单的 B5，改版中丢失，此处恢复**。注：设计上 `doc_id == job_id`，可能是有意不提供 |

> 编号说明：原始清单的 **B5（`jobs/{id}` 404）** 在改版中被替换为"字体问题"；上表以 **B12** 恢复。

---

## 三、部署 / 环境

| # | 现象 | 真实性 | 状态 |
|---|---|---|---|
| C1 | `alembic_version.version_num` 是 `varchar(32)`，装不下 36 字符的 `014_template_format_profile_skeleton` → 事务回滚、列实际没加 | ✅ 真实（迁移失败日志） | ⚠️ 生产已手动 `ALTER ... TYPE VARCHAR(255)` + migrate 通过；**代码层未修**，新环境必踩。治本 = 新建 `015_widen_alembic_version_num.py`。⛔ **绝不能改名 014 的 revision**（生产库已记该版本号，改名会让 alembic 误判未应用而重跑加列报错） |
| C2 | 容器代码烤进镜像 `/app`，不在 `/opt/judicial_app` 挂载 → 改宿主机 + `docker restart` **不生效**，必须 rebuild | ✅ 真实（`docker inspect` 证据） | ✅ 已写进 `deploy/PRODUCTION_DEPLOYMENT.md`；每次部署后须核对镜像 ID |
| C3 | `/opt/judicial_app`（源码）与 `/opt/justice-office/deploy`（生产配置）易混淆 | ✅ 真实（操作中踩过） | ⚠️ 文档记录 |

---

## 四、我的误判（诚实列，供验证）

1. **「T3 写作验收通过、A2/A3/A6 真实 E2E 确认修复」——错。** 服务器跑的是 `217f123`，不含修复；那次"全 0 次"是 run-to-run 方差。详见第 0 节。
2. **「`××` 占位符来自模板 `content_template`」——错。** 请示模板 `content_template` **不含** `××`；那是**模型自写**的占位落款。
3. **「本环境无 SSH 密钥、无法 push」——错。** 密钥一直在 `C:\GitSSH\idea_github`。根因：用 **Bash 沙箱**判断文件存在性，而沙箱 C 盘视图是残缺的（`ls /c` 只有 `Program Files`，`/c/GitSSH` 报不存在，而 `[ -d ]` 返回 true 自相矛盾）；**`Glob`/`Read` 走真实文件系统**立刻可见。→ **判断文件存在必须用 `Glob`，不能用 Bash 的 `ls`/`[ -d ]`。**
4. **巡检显示 PPT「stage=None pages=None」连 21 次疑似卡死——错。** 脚本读的是不存在的字段；`agent_job.job_status` 真实字段是 `phase`/`current_page`/`total_pages`(+`renderer`)。→ **"显示 None" ≠ "产品卡住"。**
5. **`grep -c $'\r'` 误报"含 278 处 CR"——错。** 该 Cygwin bash 里 `$'\r'` 展开为空模式，返回的是**总行数**。实测 `tr -cd '\r' | wc -c` = **0**，文件本来就是 LF。正确测法：`tr -cd '\r' < f | wc -c`。

---

## 五、未验证 / 待确认（不能当 bug）

| # | 事项 | 状态 |
|---|---|---|
| E1 | 写作数据准确性 | 用户**未确认**，不能当"数据编造" |
| E2 | 字数控制（A10） | 用户口头反馈，**未量化** |
| E3 | 生成质量"不够直接用" | 主观判断，**需具体案例定位** |

---

## 六、Commit 与部署状态

**远端 `origin/app` HEAD = `b929f43`**（服务器 pull 后应得此 SHA）

| Commit | 内容 | 部署状态 |
|---|---|---|
| `d435813` | P0+B1+B2：落款/日期兜底、正文标注移除、模板参数透传、桌面 required 校验 | 🟡 已 push，**未部署** |
| `3858661` | A1/A2/A3/A5/A6：落款去重、日期填充、标点、引用出正文、串台防抖 | 🟡 已 push，**未部署** |
| `93fe0f7` | B6 治标：本地渲染回退对用户可见 | 🟡 已 push，**未部署** |
| `079c356` | B5：质量闸不再误拦 Liberation Sans（`service.py:309`） | 🟡 已 push，**未部署** |
| `b929f43` | 文档 + 巡检脚本入库 | 🟡 已 push，**未部署** |

→ **生产当前仍是 `217f123`，上表 5 个修复全部未生效。**

### 部署命令（服务器执行）

```bash
cd /opt/judicial_app
git fetch origin app && git merge --ff-only origin/app   # 两段式，勿用 git pull
git rev-parse --short HEAD                # 应为 b929f43
docker build -f deploy/Dockerfile -t justice-office-server:20261006-b929f43 .
# 改 /opt/justice-office/deploy/docker-compose.yml 的 api image: 指向新标签
cd /opt/justice-office/deploy && docker compose --env-file .env up -d
```

---

## 七、给验证 AI 的提示

**能独立核验的**：代码位置（文件+行号已列）、commit hash、日志证据（job ID `fc037fd2`/`5c696953`/`cf7ffcc7`）、`git ls-remote origin app` 远端 SHA。

**不能核验、需业务方参与的**：数据准确性（E1/B10 需对照原始材料）、质量能否交付（E2/E3 主观）。

**建议顺序**：

```
① pull + rebuild 到 b929f43
② 跑 preflight / postcheck
③ 重跑 server/scripts/smoke_test.sh → 验证 A2/A3/A6/A7 + B5/B6
④ PPT 第2 批治本：B3→B2 预检 + B4 闸门；B1 finalize；B7 host 侧双 loop；B8/B9
⑤ 业务方评 E1-E3
```

**未决风险**：C1（新环境必踩）、B10（PPT 侧数据真实性未定性）、A4（`org.name` 是简称，B1 兜底会给简称）、A8（助手/文档不同步未修）。

---

## 订正记录（相对你给的上一版）

| # | 上一版问题 | 本版修正 |
|---|---|---|
| 1 | B5 说 "service.py:315 补丁**未打**" | 实际 **line 309**，且 `079c356` **已修已 push** |
| 2 | 只列 3 个 commit + "待打字体补丁" | 远端实为 **5 个**，HEAD=`b929f43`；字体补丁已打 |
| 3 | 原始 **A7（助手文档不同步）** 丢失 | 恢复为 **A8** |
| 4 | 原始 **B5（`jobs/{id}` 404）** 丢失 | 恢复为 **B12** |
| 5 | B10 定性为"数据编造" | 改为 ⚠️ 待人工核对，不定性 |
| 6 | 缺部署时间线更正 | 新增**第 0 节** |
| 7 | 表格多行缺竖线闭合；「我的误判」空白；`A11` 悬空引用 | 全部表格已修（7 张表列数一致、无未闭合行）；填 5 条误判；移除无此条目的 A11 引用 |