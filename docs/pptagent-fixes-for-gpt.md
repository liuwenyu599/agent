# PPTAgent / 部署 待修复项交接（给 GPT 实施）

> 本文档汇总「白云司法局智慧办公平台」PPTAgent 链路与部署中**已定位、已诊断、但尚未落地代码/配置**的问题。
> 每一项都附：**根因（已查实）**、**当前补丁措施（临时/已上的）**、**建议根治方向（让 GPT 改）**、**涉及文件与行号**、**是否本仓库可改**。
> 目标：可直接交给另一个 AI 实施，无需重新排查。

---

## 0. 给实施者的环境铁律（先做这些，否则必踩坑）

- 仓库根：`D:\Projects\judicial_app`；后端 `server/app/...`；桌面端 `desktop/src/jvmMain/kotlin/com/judicialai/desktop/`。
- **Python 解释器必须用 `D:\apps\anaconda3\python.exe`（3.11.7）**，PATH 上的 `python` 是 3.13 且缺 python-docx，用了必挂。
- **不要启动 / 重启 / 杀任何 8000 端口的 uvicorn**（上面跑着真实服务）。
- **不要 commit / push**（政务环境严禁 push GitHub；git 由主理人处理）。
- **不要碰 `.git` 目录**（该仓库元数据此前反复损坏）。
- **可改 vs 需服务器侧**：
  - ✅ **本仓库可改**（改完走部署流程）：`deploy/` 下脚本与 compose、`server/app/`、`desktop/`、仓库根 `.gitattributes`。
  - ⛔ **沙箱够不到，必须在服务器/容器内改**：`Research.yaml`（容器 `/usr/src/pptagent/deeppresenter/roles/Research.yaml` 与 `/tmp/Research.yaml`）、deeppresenter-sandbox 的 Python 执行包装、生产 `docker-compose.yml`（`/opt/justice-office/deploy/`）。这些项下面标了「⛔服务器侧」。

---

## 1. P0 / P1 待修复项（按优先级）

### 1.1 DeepPresenter-9B 不遵守「禁止 matplotlib」约束，仍用 PIL/matplotlib 生成图片
- **根因（已查实）**：
  1. **沙箱无执行层强制**：`deploy/pptagent/rebuild-images.sh:198-206 / 306-314` 反而给镜像装了 `fonts-noto-cjk`/`fonts-wqy-zenhei` 并写 `/root/.config/matplotlib/matplotlibrc`——即环境**支持且会运行** matplotlib，没有任何拦截。「禁止 matplotlib」只是 `Research.yaml` 里的一句**文本**约束，模型无视它零代价。
  2. **微调先验太强**：DeepPresenter-9B 训练分布里「画图表 = 写 matplotlib/PIL 的 Python → 存 png」，9B 对埋在超长 system prompt 里的负面约束遵循力弱，而「生成图表」这个即时目标显著性高得多。
  3. **无可靠替代路径**：Mermaid 表达**数据图**（柱状/折线）能力有限；模型没有「不用 matplotlib 也能出数据图」的可靠手段，只能回退已知方法。工作区实证：`server/data/pptagent_workspace/20260927/*/generate_chart*.py` 全是 `import matplotlib.pyplot as plt`；有一份（c287d1c0）还自注「I will use Mermaid for logic charts」却仍用 matplotlib 画数据图。
  4. **真问题在字体，不在 matplotlib**：模型生成脚本里硬编码 `plt.rcParams['font.sans-serif'] = ['DejaVu Sans']`，**覆盖**了镜像的 matplotlibrc，所以 CJK 字体装了也没用 → 当初才用「禁 matplotlib」绕过（见 1.2）。
- **当前补丁措施**：`Research.yaml` 写「禁止 matplotlib，改 Mermaid」（文本约束，**无效**）；镜像装了 CJK 字体 + matplotlibrc（但被模型运行时覆盖）。
- **建议根治（二选一，推荐 A）**：
  - **A. 字体在源头修 + 允许 matplotlib（与模型自然路径一致，最稳）**：在 sandbox 执行任何生成的 `.py` 前，加一个**清洗步骤**——删除/忽略脚本里所有 `plt.rcParams[...font...]` / `rcParams['font.sans-serif']` / `font.family` 的赋值行（因为镜像 matplotlibrc 已配置 CJK 字体），让 matplotlib 用系统 CJK 字体正常渲染中文。然后**撤掉「禁止 matplotlib」那条 prompt 约束**（它与模型先验打架，反而拖慢且无效）。清洗步骤可加在 deeppresenter-sandbox 的 `write_file`/执行包装里（与 `rebuild-images.sh` 已有的 `write_file` 补丁同源）。
  - **B. 执行层强制禁 matplotlib**：sandbox 执行前 strip `import matplotlib` / `from PIL` / `import PIL`，逼模型走 Mermaid 或失败重试。缺点：数据图 Mermaid 表达力弱，可能反复失败。
- **涉及文件**：`Research.yaml`（⛔服务器侧 `/usr/src/pptagent/deeppresenter/roles/`）、`deploy/pptagent/rebuild-images.sh`（仓库内，字体/matplotlibrc/ write_file 补丁段）、deeppresenter-sandbox 执行包装（⛔服务器侧）。
- **验收**：重新跑一次含数据图的 PPT 生成，确认产物用 matplotlib 渲染出中文图（方案 A）或完全改用 Mermaid（方案 B），且不再出现「中文方块」。

### 1.2 PPTAgent LLM 调用 ~71 秒、上下文接近 16K 上限
- **根因（已查实）**：
  1. **上下文顶到 16K**：PPTAgent 是多轮 agent loop，每轮把**完整 `Research.yaml`（role 很大）+ 累计 history + materials（RAG/上传）+ 当前任务**拼起来；后端 `server/app/infrastructure/ai/qwen.py:26-27` 有「上下文预算保护」，会砍 history、截断 system 来硬塞进 `MODEL_CTX_LIMIT`（DP9B = 16384）→ 总是贴着上限走。
  2. **71 秒主因：DP9B 的 vLLM 没开前缀缓存**。`deploy/pptagent/docker-compose.yml:33` 的 vLLM 启动参数只有 `--max-model-len 16384`，**没有 `--enable-prefix-caching`**，也没有 `--tensor-parallel-size`（默认 1，单设备）。于是**每次调用都把约 16K 的 system+history 重新 prefill 一遍**（prefill 主导延迟），9B 在单设备上 decode 也慢 → 合计 ~71s。
  3. **耦合**：「禁止 matplotlib」这句就躺在那个每轮重发的巨大 prefix 里；让禁令更显著只会进一步拉长上下文 → 更慢。
- **当前补丁措施**：`--max-model-len` 从 32768 降到 16384（避免溢出，#4 修复）；`MODEL_CTX_LIMIT` 配置；qwen.py 上下文预算保护（砍 history）。
- **建议根治**：
  - DP9B vLLM 加 **`--enable-prefix-caching`**（通过 `deploy/pptagent/docker-compose.yml:35` 的 `PPT_LLM_EXTRA_ARGS` 注入，或写死在 command 里）——system+history 命中缓存，免重复 prefill，延迟应大幅下降。
  - history 做**摘要/裁剪**而非全量重发（减少每轮 prefix 体积）。
  - 多卡时 `--tensor-parallel-size > 1`。
- **涉及文件**：`deploy/pptagent/docker-compose.yml:33/35`（仓库内可改）、`server/app/infrastructure/ai/qwen.py:26-27`（后端上下文预算）。
- **验收**：跑一次 PPT 生成，观察单次 LLM 调用耗时（应从 ~71s 显著下降）与上下文长度（应低于 16K 或命中缓存后延迟下降）。

### 1.3 「暂无 token 数据」被误判为追问（P1，偶发）
- **根因（已查实）**：`server/app/infrastructure/ppt/ppt_agent_client.py` 已有 `strip_token_stats()`（:268）两层过滤 + `_question_from()`（:956）调用它，但**漏了短状态行「暂无 token 数据」**：
  - 整块判定 `find_token_stats_block()`（:251）要求行内同时有 token 词 + 统计词（`_TOKEN_STATS_WORD_RE` :202：`统计|用量|使用量|消耗|概况|usage|statistics`），「暂无 token 数据」只有「数据」无「统计」→ 不匹配。
  - 逐行兜底 `_TOKEN_STAT_LINE_RE`（:206）要求**同行带数字**（`_DIGIT_RE` :207），「暂无 token 数据」无数字 → 不剔除。
  - 于是它作为 `question` 透出 → `server/app/application/ppt/agent_job.py:340` `if outcome.question.strip():` 把任务判成 `awaiting_clarification`，弹给用户。
- **当前补丁措施**：已有 token 统计**整块**剔除 + 逐行剔除（针对「## Token 使用统计」整块，对短状态行无效）。
- **建议根治**：在 `_question_from()` / `strip_token_stats()` 增加**「非追问状态语」识别**——匹配 `暂无\s*token` / `no\s*token\s*data` 等直接丢弃；或更稳：**cleaned 文本若不含问号（？/?）且为纯状态陈述，则视为无追问**（不设置 awaiting_clarification）。
- **涉及文件**：`server/app/infrastructure/ppt/ppt_agent_client.py:956` + `:268`、`server/app/application/ppt/agent_job.py:340`（均在仓库内）。
- **验收**：构造/复现一次「暂无 token 数据」返回，确认 API 不再弹追问、任务正常走到成功或回退。

### 1.4 多 worker `_is_active` 误判 → 客户端 2 秒显示「失败」（临时措施牺牲并发）
- **根因（已查实）**：`server/app/application/ppt/agent_job.py:49` 的 `_RUNNING` 是**模块级内存字典**，每个 uvicorn worker 进程各一份。`submit` 落到 worker A、`poll` 落到 worker B 时，B 的 `_RUNNING` 里没有该 doc → `_is_active()`（:85）返回 False → `:186 if status in ("pending","running") and not _is_active(doc.id): status="failed"` 误判失败。
- **当前补丁措施**：`--workers 4` → `--workers 1`（生产 `docker-compose.yml` 已改，**待重启**：`docker rm -f justice-api justice-migrate` + `docker compose --env-file .env up -d`）。
- **建议根治（推荐短期方案）**：把「线程是否还活着」的判定从跨进程内存字典改为**基于 DB + 心跳陈旧度**。
  - `_apply_progress` 心跳已在 `:304` 每轮刷新 `job_progress_at`；stall watchdog 在 `:295` 超 `stall_limit` 秒直接 `_fail`。
  - 将 `:186` 改为：`(now_local() - job_progress_at) > stall_limit` 才判 failed，**不再用 `_is_active`**。这样 `--workers N` 也能安全并发，`_RUNNING` 仅保留作本地去重 best-effort（`:107` 去重可接受极小竞态）。
  - 中长期：PPT 长任务本不该放 web worker 内的 daemon 线程（`runner.run` 跑在 `threading.Thread`，`:127`），应迁到独立 task queue（arq/celery/RQ + Redis），web 层只提交与查状态。
- **涉及文件**：`server/app/application/ppt/agent_job.py:186` + `:49`（仓库内）、生产 `docker-compose.yml`（⛔服务器侧 `/opt/justice-office/deploy/`）。
- **验收**：恢复 `--workers N`（N>1）后，多用户/连续提交不再误判失败；心跳正常。

### 1.5 PPTAgent `/tmp/Research.yaml` 英文段缩进错误（line 86，⛔服务器侧）
- **根因（已查实）**：之前给的 python 修正脚本**只匹配中文行**，没匹配英文段（`en:`）的三条约束行，导致英文段缩进漏掉，YAML 仍报错（line 31 的 zh 段修好后，line 86 的 en 段仍坏）。报错：`yaml.parser.ParserError`（expected block end, but found '-'）。
- **当前补丁措施**：中文段已补 4 空格（已修）；英文段三条约束行**未修**（待服务器侧重跑脚本）。
- **建议根治**：扩展修正脚本，使其**同时匹配中英文段**的三条约束行（`FORBIDDEN: apt install...` / `matplotlib scripts MUST use Chinese fonts...` / `If matplotlib outputs "Glyph missing..." do NOT apt install...`）补缩进；修完后重拷回容器并 `python3 -c "import yaml; yaml.safe_load(open(...))"` 验证 line 86 不再报错。
- **涉及文件**：容器 `/tmp/Research.yaml` 与 `/usr/src/pptagent/deeppresenter/roles/Research.yaml`（⛔服务器侧，沙箱够不到）。
- **验收**：YAML 可解析，PPTAgent 正常启动。

### 1.6 PPT 默认生成年限 + 地点（白云司法局）+ 落款当前日期（桌面端功能，未实施）
- **需求（用户原话）**：给 PPT 生成加默认「生成年限 = 当前年份」「地点/单位 = 白云司法局」「落款 = 当前日期」。
- **根因/现状**：桌面端已有 `reportDate`/`presenter` 注入机制，但缺年限/地点字段与默认值。
  - `desktop/src/jvmMain/kotlin/com/judicialai/desktop/features/ppt/PptViewModel.kt:110` 有 `reportDate` 等入口字段；`:370 outlineBody()` 拼 content；`:966 buildJobMessage()` 拼 message；UI 在 `PptScreen.kt:336-349` 用 `OutlinedTextField` 呈现。
  - `now_local()` 不在桌面端，需引入 `java.time.LocalDate`。
- **建议根治（仓库内可改）**：
  1. `PptViewModel.kt` 新增 `var generationYear`(默认今年) + `var location`(默认"白云司法局")；`init` 中用 `java.time.LocalDate.now()` 灌默认值，并把 `reportDate` 默认填成今天（`YYYY-MM-DD`）作落款日期。
  2. `outlineBody()`（:370）与 `buildJobMessage()`（:966）各加两行，把「年度 / 单位·地点」拼进上下文。
  3. `PptScreen.kt:336-349` 那一行再加两个 `OutlinedTextField`（年度、单位/地点）。
- **涉及文件**：`desktop/.../features/ppt/PptViewModel.kt`、`PptScreen.kt`（仓库内；本地无 JDK 17，编译闸靠 CI）。
- **验收**：新建 PPT 页年限/地点已预填，落款日期为当天；生成的大纲/消息含年度与单位。

### 1.7 公文写作 文种混用 / 内容跑题（P1 反馈，待反馈开发）
- **根因（已查实）**：平台对「通知」vs「工作要点」文种识别与内容边界弱，易混；发文字号 `xx司发〔2026〕xx号` 为模板残留（发文机关是「区委依法治区办」，不用「司」字号，且不能留 xx 占位）；落款时间未填实。
- **当前补丁措施**：无（待明天反馈开发）。
- **建议根治（prompt 约束）**：加强 prompt 边界——文种约束 + 内容约束 + 禁止全年工作部署。纠正版模板：以「中共广州市白云区委全面依法治区委员会办公室」名义；文种=通知、主送=各镇街/各部门、发文字号=云法治办发〔2026〕X号；只写「报告内容 / 报送要求 / 工作要求」三部分；禁止写全年工作部署、禁止重复标题、禁止保留 xx 占位符。
- **涉及文件**：`server/app/application/writing/*`（postprocessor.py、task_service.py、intent_interpreter.py 等，仓库内）。
- **验收**：生成的通知文种正确、内容为报告/报送事项而非工作要点，发文字号无占位、落款为实日期。

---

## 2. P2 / 配置根治项

### 2.1 镜像补丁未落仓（capture.js / schemas.js / write_file / 字体 / matplotlib）
- **根因（已查实）**：`deploy/pptagent/rebuild-images.sh:81-206` 每次运行重新给上游镜像打补丁，但**补丁不落仓**——只活在镜像里，靠脚本对上游镜像做字符串替换；`rebuild-images.sh:94 assert old in src` 一旦上游镜像变更就失败。
- **当前补丁措施**：修复脚本每次重打补丁（本质「灾后恢复工具」，生产禁用红线，仅兜底）。
- **建议根治**：把补丁固化为**自有 Dockerfile**（基于 pin 住的上游 tag，`COPY`/`SED` 确定性打补丁），被改文件内容存进仓库，不再依赖运行时字符串匹配。即把「恢复工具」升级为「构建工件」。
- **涉及文件**：`deploy/pptagent/rebuild-images.sh`（仓库内，含补丁逻辑）、`deploy/pptagent/Dockerfile`（若新建）。

### 2.2 Research.yaml 缩进易复发（连踩两次）
- **根因（已查实）**：手写 `zh: |` / `en: |` 字面块 + 嵌套 `- ` 列表，缩进极易错；且修正脚本只匹配中文行。
- **当前补丁措施**：每次手补 4 空格（临时）。
- **建议根治**：① 改完 `python3 -c "import yaml; yaml.safe_load(open(path))"` 校验；② 用 `yaml.dump` 从 Python 结构**生成** `Research.yaml`，不手写字面块；③ preflight（`deploy/preflight-production.sh` 等）增加「校验 `pptagent/roles/*.yaml` 全部可解析」。
- **涉及文件**：`Research.yaml`（⛔服务器侧）、`deploy/preflight-production.sh`（仓库内）。

### 2.3 CRLF 换行符（.sh 带 \r，在 Linux 执行报错）
- **根因（已查实）**：Windows 编辑 `.sh` 带 `\r\n`，Linux 执行报 `/usr/bin/env: "bash\r": 没有那个文件或目录`。
- **当前补丁措施**：`sed -i 's/\r$//'` 修 94 个文件（事后补救）。
- **建议根治**：仓库根加 **`.gitattributes`**（`*.sh text eol=lf`，可加 `*.py text` `*.kt text` 等），让 git 提交/检出统一换行，从根上杜绝；可再加 pre-commit 钩子拒绝含 CRLF 的 shell 脚本。
- **涉及文件**：仓库根 `.gitattributes`（**当前不存在**，已确认 Glob 无；仓库内可建）。

---

## 3. 已处理 / 已上线（不要重做，仅供参考）

- ✅ **PPT 客户端误判失败的心跳修复**（`agent_job.py:303-305` 加 `self._set(job_progress_at=now_local())`）—— 已落地并实际上线，镜像 `justice-office-server:20260929-113829-heartbeat`。
- ✅ **`--workers 1` 改完待重启**（见 1.4，生产 compose 已改）。
- ✅ **页数被模板覆盖**（`max(2,min)` + 硬约束 prompt）—— 实测 4 页任务出 4 页。
- ✅ **DP9B 上下文溢出**（16385>16384）—— `--max-model-len 16384` 已设。
- ✅ **PPT_AGENT_WORKSPACE_DIR 配错** —— `.env` 改 `/data/pptagent`。
- ✅ **镜像 tag 混乱** —— 唯一 tag `justice-office-server:20260929-c3fe90e` 体系。
- ✅ **preflight `find` 找错文件** —— 固定路径 `/usr/src/app/dist/tools/schemas.js`。

---

## 4. 待办部署动作（给主理人 / GPT 收尾）

1. **重建同步 tar**：之前打的 `D:/judicial_app_c3fe90e.tar.gz` 是按旧 HEAD 打的，不含后续未提交改动；下次服务器同步需从当前工作树重新打 tar（或先 commit 再打）。
2. **`--workers 1` 重启**：`docker rm -f justice-api justice-migrate` + `docker compose --env-file .env up -d` + `curl http://127.0.0.1:8000/health` 验证（见 1.4）。
3. **DP9B 加 prefix caching**：改 `deploy/pptagent/docker-compose.yml` 后重建 `justice-deeppresenter-9b` 镜像（见 1.2）。
4. 政务环境**严禁 push GitHub**；所有改动走 tar 覆盖 + 镜像重建，不依赖 git 推送。

---

*整理时间：2026-09-29。本文件由主理人（team lead）据对话诊断汇编，未做任何代码改动；根因与行号均经实查。*
