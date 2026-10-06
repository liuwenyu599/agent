# 云法智办 · 今日问题清单（供独立 AI 验证）

- **日期**：2026-10-06
- **仓库**：`D:\Projects\judicial_app`，分支 `app`
- **代码基线**：`217f123`（已部署）→ 我的修复 `d435813` / `3858661` / `93fe0f7`（**本地已提交，未 push、未部署**）
- **说明**：本文档区分「真实缺陷」与「误判/非产品缺陷」，每条给出可独立复核的代码位置与判定依据。

---

## ⚠️ 首要更正：上一轮我给出的「T3 写作验收通过」结论是**错的**

这是本文档最重要的一条，请勿沿用我先前的判断。

| 项 | 时间 | 说明 |
|---|---|---|
| 服务器最后一次 rebuild | **16:30** | 镜像 `justice-office-server:20261006-162519-217f123`，即部署的是 `217f123` 代码 |
| 我的写作修复 `d435813` | 17:46 | 在 217f123 之后 |
| 我的写作修复 `3858661` | 18:13 | 在 217f123 之后 |
| 用户跑 smoke_test 验收 | **18:30** | — |
| 桌面修复 `93fe0f7` | 18:43 | 在跑测之后 |

**后果**：

1. **18:30 跑测的服务器跑的是 `217f123` 代码，不含 A1/A2/A3/A5/A6/P0/B1 的任何修复**（这些在 `d435813`/`3858661`，从未 push/rebuild）。
2. 因此那次跑测里「`××`/`缺少事实依据`/`（参考`/`[参考`/`⚠️` 全部 0 次」**不能证明我的修复有效**——它只是**该次模型生成恰好没吐这些串**（run-to-run 方差）。证据：同一份 217f123 代码在此前的 T1/T2 跑测中吐了`（缺少事实依据）×6`。
3. 三件套值 `title`/`recipient`/`authority`/`document_date` 全部来自 smoke 脚本显式传入的 `planned_context`（脚本第 93 行硬编码了这四个值），**没有触发我的 B1 兜底逻辑**，因此也**不能证明 B1/B2 修复生效**。
4. B2 是**桌面端**改动，而 smoke_test.sh 是**纯 API 调用、完全不经过桌面端** → B2 的桌面修复被这次验证**完全绕过**。

**结论**：写作侧修复目前状态 = **代码已改+ 单测通过 + 真实环境完全未验证**。必须 push + rebuild 后重跑才算真验收。

---

## 一、已确认真实 + 已改代码（但**未部署验证**）

### P0｜正文被`（缺少事实依据）`污染 ★ 真实
- **现象**：正文出现`（缺少事实依据）×6` 等溯源标注。
- **根因（已定位）**：`server/app/application/writing/task_service.py` 的 `REVISION_RULES`(line 78) 与 `DRAFT_RULES`(line 90) 指令生成模型「用「⚠️ 缺少事实依据」标注」→ 模型把溯源标注直写进正文。溯源本应走独立通道（`_revise_reply` 报missing_fields + `_draft_followup` 追问 + `content_check`/`citation_warnings`）。
- **修复**：
  - `d435813`：删两处 prompt 的「标注」指令，保留"不得编造/不得自行填充"。
  - `3858661`：`structured_field_service._canonicalize_body` 新增 `_INLINE_CITATION_RE`，剥离行内标注 `（参考资料N）`/`（参考N）`/`（依据N）`/`[参考资料N]`/`（缺少事实依据）`/`⚠️ 缺少事实依据`（只匹配标记形态，避免误伤"缺少事实依据支撑"这类合法正文）。
- **验证现状**：单测 65 passed；**真实环境未验证（见上文更正）**。
- **复核建议**：部署后跑同一请示任务，确认正文 0 标注。

### A2｜落款重复两套 ★ 真实
- **现象**：`××年××月/××日` 与 `白云司法局/2025年` 两套落款叠加。
- **根因**：`××` 占位符**不是模板自带**（请示模板 `content_template` 无占位符），是**模型自写**；chrome 层（`docx_export._add_signature`/`_add_date`）又从 ctx 渲染真实落款 → 两套并存。`canonicalize` 只剥「与 ctx 完全相等」或匹配落款/日期正则的行，漏了 `××` 行。
- **修复**：`3858661` 新增 `_PLACEHOLDER_LINE_RE = ^[×XＸxｏ年月日\s]+$`，在 canonicalize 首部/主循环/尾部剥掉 `××` 类占位行，落款/日期只由 chrome 渲染一套。
- **验证现状**：单测过；真实环境未验证。

### A3｜日期占位符 ×× 未填充 ★ 真实（与 A2 同源）
- **修复**：同A2（canonicalize 剥离）+ `d435813` 的 B1（`need_date` → `document_date` 默认今天，格式 `YYYY年M月D日`，用 `now_local()`）。
- **验证现状**：单测过；真实环境未验证。

### A5｜结尾标点「。，」连用 ★ 真实
- **现象**：`…认真研究落实。，要及时采取…`（句号后紧跟逗号）。
- **修复**：`3858661` `postprocessor.py` 新增 `fix_redundant_comma_after_period`（句号/叹号/问号后紧跟逗号→去逗号，含跨行），挂process 流水线 4.5 步。
- **复核提醒**：这是**通用标点规整**，未定位用户原始截图 `。，` 的精确拼接触发点。若要精确复现需用户提供原文。
- **验证现状**：单测过；真实环境未验证。

### A1｜新建任务串台（文档未清空）★ 真实（客户端）
- **根因**：`WritingViewModel.openTask` 在 `repo.getTask` 返回后**无条件** `applyResponse`/`content=`，未校验"此时 `pendingWritingTaskId` 是否仍指向自己"。点「新建任务」时若有旧任务恢复协程在途，旧正文被写回新任务（正是 `newTask()` 注释 L893 警告的竞态）。
- **修复**：`3858661` `WritingViewModel.kt` openTask 成功分支加护栏：`AppState.pendingWritingTaskId != id` 则 `return@launch` 放弃写入（仍走 `finally` 复位 busy/restoring）。
- **验证现状**：桌面 `compileKotlinJvm` BUILD SUCCESS；**客户端实测未做**（需桌面端点「新建任务」确认主题/正文为空）。

### B7｜AI 产物没回传，静默回退本地渲染 ★ 真实
- **根因链**：`B1`(Design 不 finalize) + `B6`(host 双 loop) → PPTAgent 无合法 pptx → 后端 `agent_job._finish`(agent_job.py:400-427) 各分支（error / outcome=None / 质量闸不过 / 重试无 pptx / 无产物）全部 `self._fallback_local(...)` → `status="succeeded"` + `job_renderer="local"`，用户无感。
- **透明度断点**：后端用 `job_renderer` 区分 `pptagent`/`local`/`pptagent_retry`，客户端也透传（`PptRepository.kt:245`、`PptJobState.kt:84/123/375`），但 `PptJobState.kt:670` `fun pptRendererNote(renderer: String?): String? = null` **恒返回 null** → 用户看不出拿到的是 AI 产物还是本地渲染。
- **修复**：`93fe0f7` 实现 `pptRendererNote`——`pptagent`/`pptagent_retry` → null；`local`/空/未知 → 返回告警文案。调用点 `PptAsyncWorkbench.kt:270` 已有 `Ink2` 样式承载。
- **性质**：**治标透明化**。治本（B1/B6）未修，AI 排版问题仍存在。
- **验证现状**：编译过；未在真机看到告警（需 B7 触发场景实测）。

---

## 二、真实 + 已定位但**未修**（PPT 治本，需第 2 批）

### B1｜卡在 inspect_slide 循环，无最终 pptx ★ 真实
- **现象**：Research finalize（出 manuscript.md/png/html/css 齐全）→ Design 启动 → `inspect_slide slide_02` 多轮报错（11 个→4 个）→ **无 finalize、无 pptx**。
- **排查线索**：`deploy/pptagent/roles/Design.yaml` 每页 inspect≤2 轮限制可能不足；`deeppresenter-host` `main.py` 的 `max_turns=10` 可能用完。
- **状态**：未修。

### B3｜重复关键字参数（B2 的真实根因）★ 真实
- **现象**：模型代码`ax.text(..., fontsize=18, fontweight='bold', color='#0E243E', color='#333333')`、`plt.title(..., fontsize=20, fontsize=20, ...)` → `SyntaxError: keyword argument repeated`。
- **用户订正**：这比 B2 的 `unterminated string literal` 更常见，v5 文档记错了病灶。
- **状态**：未修。

### B2｜`SyntaxError: unterminated string literal` 未拦
- **要求**：sandbox 执行层加 `ast.parse` 静态预检。
- **状态**：未修（与 B3 同一机制一起做）。

### B4｜无限造图循环
- **现象**：同一 `generate_images.py` 被重写 3+ 次。
- **要求**：同一错误重复 2 次即中止。
- **状态**：未修。

### B6｜单次 POST /api/v1/ppt/jobs 起了两个 loop ★ 真实（已排除后端 submit）
- **现象**：客户端只发**一次** `POST /api/v1/ppt/jobs → 200`，服务器跑两个 loop：`10:04:05 loop-5c696953`(4 页，已 finalize) + `10:16:44 loop-cf7ffcc7`(8 页，仍在跑)，差 ~17 秒。
- **已定位（只读 grep）**：
  - 后端 `submit_job` 有**强去重**——`queued_agent_job.py:171-181` `_queue_position_locked(doc_id)` 同 doc_id 去重；`:183-188` `_USER_JOBS[user_id]` 同用户不同 doc_id 并发 → 409 拒绝。质量闸另有 1 次 `_retry_generate`（agent_job.py:346）但那是**同页数**重试。
  - `submit_job` 唯一入口：`interfaces/ppt.py:436`。另一处`queued_agent_job.py:281` `answer_clarification` 仅"回答澄清追问"时重入。
  - **反向线索**：`loop-xxxx` 是 **PPTAgent Gradio host** 打的 research loop 名；后端线程名是 `ppt-job-<docid8>`/`ppt-sse-<docid8>`（不带 loop-）。两个 loop 页数不同（4 vs 8）→ 双发**不在后端 submit**，在 **PPTAgent host 侧**（`send_message` 被其内部跑了两次 Research，或 host 自带 retry/fallback）。
- **状态**：未修。深挖方向在 PPTAgent 那台机（`deploy/pptagent/` 或仓库外）。

### B5｜`/api/v1/ppt/jobs/{id}` 端点 404
- **现象**：`/jobs/{id}` 404，但 `/jobs/{id}/status`、`/jobs/{id}/preview` 200。
- **状态**：未修（用户自评P2，非阻塞）。注：设计上 `doc_id == job_id`，可能是有意不提供该路由。

---

## 三、真实 + 未修（部署/流程类，非代码功能）

### C1｜alembic version_num 长度限制
- **事实**：迁移 `014_template_format_profile_skeleton` 的 revision ID 长 **36 字符 > `alembic_version.version_num` 默认 varchar(32)** → `UPDATE alembic_version` 写不进 → 事务回滚 → 列实际没加。
- **生产现状**：用户已**手动** `ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)` 解决，迁移已到位（POST-CHECK PASSED）。
- **代码状态**：**未修**。治本= 新建 `015_widen_alembic_version_num.py` 加宽列（本轮明确不做，记入 MEMORY 待独立提交）。新环境部署会踩。
- **红线**：**绝不能改名 014 的 revision**（生产库已记36 字符版本号，改名会让 alembic 误判 014 未应用而重跑加列报错）。

### C2｜假部署风险（机制，非 bug）
- **事实**：`justice-api` 代码**烤进镜像**（`deploy/Dockerfile` `COPY server/ /app/`），宿主机 `/opt/judicial_app` 只是源码暂存。改宿主机文件 + `docker restart` **不生效**，必须 rebuild 镜像。
- **状态**：已写进 `deploy/PRODUCTION_DEPLOYMENT.md`。每次部署后须 `docker inspect justice-api --format '{{.Image}}'` 核对镜像ID。

---

## 四、误判 / 非产品缺陷（不要去"修"）

### preflight 客户端告警 ★ 误报，已闭合
- preflight 报 `TIMEOUT_STATUS_MS` 偏低 + ppt 目录含 `job_error`。本机复核：
  - `TIMEOUT_STATUS_MS = 60_000L`（`PptRepository.kt:29`）≥ 30000 ✅。
  - 全 ppt feature 目录 grep `job_error` → **0 命中**；异步轮询终态判定纯靠 `PptJobState.kt:30/86` `TERMINAL_JOB_STATUSES` + `applyStatus` 映射 `s.status`；`error_msg` 仅作人类可读失败文案（`PptRepository.kt:241`、`PptJobState.kt:125`）。`PptViewModel.kt:687`的 `"error"->` 属`runOutline` 同步大纲流老路径，与异步 job 无关。✅ 告警以证据闭合。

### Edit「返回成功但未落盘」 ★ 真实陷阱（流程问题）
- **事实**：`d435813` 之前，上一轮对 `task_service.py` 的 P0/B1 编辑**未真正写入文件**（grep 复核发现 `REVISION_RULES`仍含标注指令、B1 块完全缺失）。
- **教训**：改完必须 `grep` 复核标记词 + `git diff` 确认。已在各轮执行。

### smoke_test.sh 的 3 个脚本自身 bug ★ 真实（脚本非产品）
1. **步骤 6 自检读错 key**：读 `d.get("context")`，真实字段是 **`task_context`** → title/recipient/authority/date 全打印空 `''`，误以为三件套没填。已修。
2. **步骤 10 compile 非法 target**：发 `target="公文正文"` → 400。合法 `VALID_RULE_TARGETS = title/body/heading1/heading2/page/signature/date/general/content`。已改 `heading1`。
3. **步骤 15 PPT 轮询读错字段（最误导）**：读 `stage`/`pages`，但 `agent_job.job_status`(agent_job.py:199-209) 真实字段是 **`phase`/`current_page`/`total_pages`(+`renderer`)**，压根没有 `stage`/`pages` → 连打 21 次 `stage=None pages=None`，**看着像 PPT 卡死，实际任务正常 running 推进**。已改真实字段 + 新增 renderer 终态判定。
- 内嵌 python 注意：f-string 里 `d.get(\"...\")` 嵌套转义引号在 Python 3.12 前是 SyntaxError（`bash -n` 查不出），已改 `%` 格式化。

---

## 五、观察项 / 待定（未定性，不建议直接当 bug 修）

### `XXX号` 文号占位符（真实出现，但系统自愈）
- **现象**：18:30 跑测步骤 5「任务对话」被质量门拦下 `WRITING_QUALITY_GATE_D`，issues含「占位符：['XXX号']」+「正文偏短（755 字 < 800）」。
- **解读**：模型偶发在正文留**文号占位符 `XXX号`**（A3 的邻近形态，A3 修的是日期 `××`）。质量门**正确拦住了**这一版；随后显式 draft 输出干净——**系统自愈**。
- **待定**：是否把 `XXX号` 纳入 canonicalize 剥离。已加进脚本特征串便于盯。

### A4｜发文机关名不全 `白云司法局` → 应为 `广州市白云区司法局`（P1，未真正解决）
- **重要交互**：B1 兜底用的 `org.name` 配置值本身就是简称 `"白云区司法局"`（`seed_v3.py:121`）。**用户在桌面端不填主送时，B1 兜底会给出简称，不是规范全称** → A4 仍会复现。
- **跑测为何没暴露**：18:30 跑测中 authority/recipient 来自脚本显式传入的 `planned_context`（全称`广州市白云区司法局`），**绕过了 B1 兜底**。
- **待定**：是否把 `org.name` 改成规范全称，或引入独立的"规范机关名"配置。

### content_check unverified 引用（正常，非 bug）
- 2 条引用（财政局资产管理指导意见、内部管理制度汇编）未在 KB 命中 → `unverified`，review 级。引用核验正常工作。

---

## 六、唯一未闭合签字条件

- **客户端实跑 2 页PPT + 10 页 PPT 两次端到端验收**（桌面端 `.\gradlew.bat run`，admin 登录；admin 代建账号首登须改密）。**需 Windows 桌面端人工完成**，是当前唯一挡住签字的条件。

---

## 复核指引（给验证 AI）

1. **git 核对**：修复提交 `d435813`/`3858661`/`93fe0f7`；`app` 分支 `ahead origin/app by 4`（含用户自己的 `079c356` 字体修复）——**全部未 push**，故生产仍是 `217f123`。
2. **未push 是本文档"未部署验证"栏的依据**；要验证修复，先 push + 服务器 rebuild + 重跑 smoke_test.sh。
3. **勿沿用我先前"T3 写作验收通过"的口头结论**——见文档开头更正，那次跑测未含修复代码。
4. **待你独立确认的重点**：
   - P0/A2/A3/A5/B1/B7 的修复逻辑是否正确（尤其 `_INLINE_CITATION_RE` 只匹配标记形态、`_PLACEHOLDER_LINE_RE` 是否会误伤合法正文）；
   - A1 护栏是否引入新竞态；
   - A4 与 B1 的 `org.name` 简称问题是否需一并解决；
   - B6 双 loop 是否真在 PPTAgent host 侧（本文档只给了后端排除证据，host 侧未验证）。