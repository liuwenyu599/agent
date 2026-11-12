# 云法智办 (judicial_app) 整体说明与审查指引

> 目的：本文是给**接手审查的另一位 AI** 的自包含背景说明。
> 读完即可理解项目结构、近期改动、已知坑点与审查重点，无需再翻历史对话。
> 当前 HEAD：`28a429a`（分支 `app`）。最近一次向 GitHub 推送包含约 65 个提交。

---

## 0. 一句话定位

白云司法局智慧办公平台。后端 FastAPI + 桌面端 Compose Desktop，核心能力是
**智能写作 / 公文格式校验 / PPT 自动生成 / 工作流 / 知识库**，跑在本地优先 +
内网私有大模型（35B + bge-m3）之上。本仓库是「后端 + 桌面端 + 部署脚本」统一工程。

---

## 1. 技术栈与仓库结构

| 维度 | 内容 |
|---|---|
| 后端 | FastAPI (`server/`)；SQLAlchemy 2.0 + Alembic；开发用 SQLite，生产数据库在独立容器 `justice-db` |
| 向量库 | FAISS；embedding 维度必须 == 1024（`bge-m3`） |
| 桌面端 | Compose Desktop (`desktop/`)；Kotlin 仓储 `WorkflowRepository.kt` |
| 模型硬件 | 8× 昇腾 310P3（单卡 43GB）：`qwen35b-main`(davinci0,1 TP=2 :8010)、`bge-embedding`(:8006)、`qwen14b-rollback`(:8003)、27B 试用(:8011) |
| 部署 | Docker，代码**烤进镜像**（`COPY server/ /app/`，改宿主机 + restart 不更新）；扁平 tar 包 + `deploy/deploy_latest.sh` |
| AI 网关 | `LLMGateway` 抽象；`AI_PROVIDER` auto/mock → `QwenGateway` / `MockLLMGateway`。四套：文本/视觉/PPT/长文，文本·视觉·长文均指向 35B(:8010) |

关键路径：
- `server/app/application/ppt/` —— PPT 生成（主动区）
- `server/app/application/workflow/service.py` —— 工作流
- `server/app/interfaces/format_check.py`、`server/app/application/writing/` —— 格式校验 / 写作
- `server/app/infrastructure/ai/qwen.py` —— 模型网关与并发/重试
- `deploy/` —— 部署、备份、离线校验脚本

---

## 2. 核心模块与近期改动（主动区）

### 2.1 PPT 自动生成（designed 模式）

三模式：
- `adaptive`（无模板）/ `strict`（几何克隆）/ `designed`（**默认**：有模板克隆 + 引擎骨架兜底）。

`designed` 链路：
- 封面 / 目录 / 章节 / 结尾：沿用模板原版式。
- 正文页（`content`/`case`/`summary`/`chart`/`data`）：统一走 `_fill_readable_template_page`
  → 先试**模型构图** `_fill_model_regions_on_template`（仅 `content`/`case`/`summary` 生效，
  `chart`/`data` 自动退骨架）→ 失败/拒收退**引擎可读骨架**。
- 入口字段：`fallback_mode`(readable/learned/none，默认 readable) +
  `force_template_layout`(演示保底，优先级高于 fallback，skip_model=True 直接出旧样式)。
  对应 `dto.OutlineIn` 与桌面端 `vm.fallbackMode` / `vm.safeMode`。

关键文件：`page_authoring.py`(构图+重试+诊断)、`page_scene.py`(explain/audit/clamp_regions)、
`template_style.py`(风格摘要)、`svg_layer.py`(defusedxml + 渲染验证)、`image_media.py`(配图裁剪)、
`visual_primitives.py`、`ppt_engine.py`(选版/填充/成稿)。

诊断：`render_pptx/build_pptx_learned(diagnostics=[])` 逐页记
`composition=model|readable|none|learned`；`deploy/probe_ppt_designed.py` 量接受率/落地率/耗时/拒因
（**已知缺口：探针没传 reference_image，该分支未覆盖**）。

#### 2.1.1 选版器重构（`28a429a`）—— **重点审查对象**

- **旧**：`_layout_score` 内 if/elif 硬编码打分链，新增版式要加 if。
- **新**：声明式 `_LAYOUT_AFFINITY` 注册表（`ppt_engine.py:478`），`_eval_affinity_rule`
  解释单条规则（kind 包括 image_bonus / statement / pair / n_eq / n_ge / n_range / quoted /
  cards_range / cards_ge / rows_ge / timeline_ge / process_ge / point_len_le_all / balance）。
  **未在其中声明的版式（封面/目录/章节/结尾等）直接以 `weight` 基础分兜底**——保证新增/未知版式
  永不崩溃、且不低于中性基线。
- **验证**：`test_layout_score_characterization.py` + `layout_baseline.json`（684 条冻结基线 = 36 版式 × 19 slide，2/2 通过）。
  取值与历史 if 分支逐分对齐。
- **已核验（独立复算，可闭环）**：见 `docs/LAYOUT_SELECTOR_VERIFICATION.md`。
  - 用重构前父提交 `78fa1b4` 的旧 `_layout_score`（if/elif 版）对同样的 36 版式 × 19 slide 重算，
    **684/684 与基线零偏差（容差 1e-9）**——证明基线确实反映旧代码行为，故「新代码与基线一致」
    即**旧 if/elif → 新注册表行为等价**，而非新代码自洽。
  - 声明版式 **18 个**（非 19）；未声明走 `weight` 兜底 **18 个**（非 17）；`LAYOUT_CATALOG` 共 **36 个**；
    声明中无指向不存在版式的死声明。
  - 全 catalog `weight` 范围 **0.6–1.3**，最高 `section.number`(1.3)，中性偏保守；`recent -1.3` /
    `used -0.30×n` 惩罚对兜底版式同样生效（`ppt_engine.py:579-581` 在规则循环之外）。
  - 两处历史遗留（已冻结、非回归，建议加注释）：`image_bonus` 无图记 0.0 而非负分；
    `data.cards` 的 `else` 为唯一正分兜底 `+0.2`。
- **审查要点（均已关闭）**：
  1. 各新规则与历史 if 分支**逐分一致**：✅ 旧代码重算 684/684 一致。
  2. 新增版式**只加一条数据、零 if 增长**：✅ 18 条声明 + `_eval_affinity_rule` kind 分发。
  3. 兜底 `weight` 中性、无异常高分：✅ 0.6–1.3 且惩罚通用。

### 2.2 工作流数据同步（`9e56971`）

- **双存储**：`WorkflowInstance.basic_info`（权威数据源）+ `NodeInstance.content`（节点正文）。
  `_get_upstream_contents` 显式跳过「基础信息」节点。
- **问题**：桌面端 `createInstance` 传空的 `workflow_context`，`updateNode` 只写 `ni.content`、
  **无写 `basic_info` 路径** → 服务端 `generate_node` 拿不到「基础信息」，生成内容缺上下文。
- **修复**：`generate_node` 新增 `_get_basic_info_node_content` 兜底（`service.py:566`），
  `basic_info` 空时从「基础信息」节点正文回退取数注入生成提示。
- **已根治（方案 B，后端 `update_node` 同步写，改一处更省）**：编辑「基础信息」类型节点时，
  `update_node`（`service.py:425-430`）现在把自由文本解析为结构化 `basic_info` 写回实例
  （新增 `_parse_basic_info_text:438-457`），修复实例列表/详情回显丢失，并让 `generate_node`
  不再依赖节点正文回退。**桌面端 `WorkflowRepository.kt` 无需改动**即获此修复（basic_info 由后端在 saveNode 时同步）。
- **已核验（独立读码，见 `docs/WORKFLOW_SYNC_VERIFICATION.md`）**：
  1. `update_node`（`service.py:412`）仅写 `ni.content`，**确认无写 `basic_info` 路径**——缺口属实。
  2. 兜底触发条件 `ctx_text == "（未填写）"`（`generate_node` 内，现 443–449）即 `basic_info` **全空**才回退；
     `_build_context_text`（现 554）至少返回非空串「（未填写）」，故原 `not ctx_text` 分支是死条件（已顺手删除）。
  3. `_get_basic_info_node_content`（现 566）按 `"基础信息" in nd.name` 子串匹配、取**列表序第一个**有正文节点——
     确认属实；与 `_get_upstream_contents`（现 582）的跳过匹配是同一套脆弱子串逻辑。
  4. `_get_upstream_contents`（现 582）对上游正文截到 2000/1500 字符，但**兜底基础信息原样注入**——不对称，已修。
  5. `_instance_to_dict`（现 632）回读 `workflow_context/basic_info = _get_workflow_context(inst)`（即 `inst.basic_info`），
     **确认 basic_info 长期为空时桌面端实例列表/详情回显丢失**——这是兜底修不了的二阶面，须桌面端根治。
- **本轮已修的边界（低风险、已通过回归测试 `test_generate_node_falls_back_to_basic_info_node_content`）**：
  - 边界①（中）：兜底基础信息**截断到 2000 字**，与上游对齐，避免长粘贴撑爆 `max_tokens=3000` 预算。
  - 边界④（低）：兜底段在 prompt 内加注「（回退自基础信息节点原文，自由文本，请提炼规范公文表述）」，
    修正「唯一权威数据源」措辞与自由文本实际形态不符的问题。
  - **桌面端根治（根因修复）**：`update_node` 在「基础信息」节点编辑时把自由文本解析为结构化
    `basic_info` 写回实例（`service.py:425-430` + `_parse_basic_info_text:438-457`），回显丢失已修。
    回归见 `test_update_node_on_basic_info_node_syncs_basic_info`（全文 `test_workflow_contract.py` 28 passed）。
- **仍待决策 / 待根治（未改，标注为产品决策）**：
  - 边界②（中）：本根治采用「基础信息节点即权威源、整段覆盖」语义，已规避「半空 basic_info 压制更全正文」问题
    （节点正文现在直接成为 basic_info，不再有中间态）；仅当未来桌面端改为**结构化字段直传** `workflow_context`
    并与节点正文并存时，才需重新评估叠加策略。
  - 边界③（低）：子串匹配误伤/多节点取首——`update_node` 与 `_get_basic_info_node_content` / `_get_upstream_contents`
    仍共用 `"基础信息" in nd.name`；根治项未改此匹配（保持一致即可工作），建议后续用节点 `stage` 或显式类型标识替代名称子串。
- **审查要点（已核验）**：服务端兜底回退边界已读码确认并修两处；桌面端漏写须根治（见上）。

### 2.3 异步化与并发治理

- **已异步**：写作 / 对话 / OCR。
- **仍同步阻塞（待改）**：`format_check.py:56`（`asyncio.run` 包 `check_upload`）、
  `ppt.py:247`（`analyze_materials`）。⚠ 在 async 路由里调 `asyncio.run` 会新建 event loop、
  **阻塞 worker 线程**，应改为 `await`。
- **并发模型**（`afc4175`）：本地 PPT 队列 `_MAX_CONCURRENT_JOBS=2`（进程内 FIFO 排队）；
  同一 `QwenGateway` 模型池跨线程共享并发上限 `MODEL_MAX_CONCURRENCY=4`；
  后台 PPT 给交互式写作**预留 1 个请求名额**（`_rag_heavy_slots=2`），避免做 PPT 时写作饿死。
- **429 退避重试**（`qwen.py`）：最多 3 次（1/2/4s 指数退避），瞬时限频不再直接判整页失败。
  ⚠ 仍受 vLLM `--max-num-seqs` 与单端点共用约束——根治靠给 PPT/VISION 起独立 35B 副本
  并设 `PPT_MODEL_URL` / `VISION_MODEL_URL`。
- **已知缺口**：无全局多用户调度层；**50 人并发瓶颈在 35B 单端点 + 线程池**；
  临时上传文档**无定期清理机制**（无 apscheduler/celery），会永久占磁盘，孤儿附件未级联删。

#### 2026-11-12 生产实测与整改（35B 单端点 `10.128.85.133:8010`）

低强度只读压测（长上下文构图 ≈3k token 输入 / 800 token 输出，交互式写作短请求 64 token）：

| 场景 | 墙钟 | 写作短请求 TTFT |
| --- | --- | --- |
| 单条长构图 | 27.8s | — |
| 2 条构图并行 | 52.1s（串行约 55.6s，几乎无收益） | — |
| 4 条构图并行 | 64.0s（串行约 111s，省 47s） | — |
| **2×PPT 长构图 + 4×写作** | 54.2s | **9.39s** |
| 4×写作基线 | 5.0s | 2.47s |

结论：**单 35B 端点的 decode 吞吐是瓶颈，不是应用层并发数**。盲目把构图批次并行化
只会让交互式写作 TTFT 劣化约 3.8 倍（vLLM 把长短请求 batch 在一起，应用层管不到）。
据此整改：

- 新增 `ppt_admission.py` 全局闸门：所有 PPT 专用模型调用（大纲/构图/修复）统一过闸，
  上限恒 `< MODEL_MAX_CONCURRENCY`，至少一个模型名额留给交互式写作。
- `page_authoring.py` 首轮构图批次并行改为**默认关闭的灰度开关**
  `PPT_COMPOSITION_PARALLEL=1`；开启后按组并行且受闸门总量约束，带模板图的首批仍单独跑。
- `queued_agent_job.py` 增加 `PPT_QUEUE_MAX`（默认 50，超限立即 409 明示人数）、
  `PPT_QUEUE_TIMEOUT`（默认 1800s，超时自动取消并清用户归属）、
  基于实测作业均值的 `estimated_wait_seconds` 与 `queue_stats()`；
  后台线程补 `set_model_request_user`，让模型池 per-user 公平调度对 PPT 生效。
- `PPT_MODEL_SLOT_TIMEOUT=300` 让等闸门的请求有明确超时，不无限挂住 HTTP 线程；
  `main.lifespan` 把 AnyIO 工作线程池配额由默认 40 放宽到
  `WEB_THREADPOOL_TOKENS=120`，避免 50 人同时排队时连写作/状态轮询都排不进来。
- 修正 4 套真母版版式指纹撞车（14 套模板恢复 14 个唯一指纹）。
- 回归：`-k ppt` = **665 passed / 5 failed**，5 条均为既有基线（4 条记录在案 +
  1 条 `test_status_is_queryable_and_reaches_terminal` 经 HEAD 复跑确认为顺序依赖的
  既有失败），本轮新增 10 条测试全过。

⚠ 仍**不能承诺** designed 模式降到 10 分钟以内、也不能承诺 50 人同时流畅：
需 root 读取容器内 `[PPT 任务耗时]` / `[PPT 构图耗时]` 分段日志，并在给 PPT 起独立
35B 副本后重做混合压测。当前单端点下 50 人应理解为「有序排队 + 明确等待时间」，
不是「50 路同时生成」。

### 2.4 公文格式校验（`b13ddbd` / `366f71d` / `1c42ed7`）

- `check_engine.py`：确定性规则 + 自动修正 + 35B 语义；`official_document_format.py`：GB/T 9704。
- **短板（设计层）**：结构项不查、语义 `fix_hint` 恒 null、形态割裂、redesign 真机未验证。
- `1c42ed7`：写作台**后台自动校验**改稿。
- `366f71d`：内容校验（**文本非多模态**）+ 公平多用户工作流 + 写作依据溯源
  （可点击链接 + 命中高亮）。

---

## 3. 测试基线

- 全量约 **938 passed** 起。本机注定/偶发失败（**勿改**）：
  `test_sqlite_backup_*`、`test_faiss_delete_*`、
  `test_stream_encoding::test_complete_stream_yields_multiple_chunks`、
  `test_full_acceptance::TestWritingTaskFlow::test_save_manual_version`(409)。
- PPT 子集 `pytest -k ppt`：**631 passed / 4 failed**（4 条是既有基线，非本轮回归）：
  2 个 learned 过期测试（`content` 已不走 learned 默认）、1 个小图表豁免缺口、
  1 个图表守卫断言文案。
- 新测试模块须在 `conftest` 的 `_SEED_USERNAMES` 加一行（key=模块名），否则退 seedadmin→401。
- 管理员代建账号首登须改密否则 403；登录限流器是进程单例 → conftest 按模块 reset。
- pytest 无配置文件 → 只收集 `Test*` 类。⚠ **PPT 测试会真连生产内网**（`server/.env`
  `PPT_AGENT_URL`）→ 新模块用 autouse fixture 置空。
- 运行：`cd server && CODEBUDDY_SAFE_DELETE_ENABLED=0 D:/apps/anaconda3/python.exe -m pytest -q`

---

## 4. 部署与出网闸

- **镜像构建非目录挂载**：`COPY server/ /app/`，改宿主机 + restart 不更新。权威 = `deploy/deploy_latest.sh`。
- `pack_release.py` 产**扁平包**，解包不能 `--strip-components`；
  显式排除 `server/data`、`desktop/build`、`deploy/offline`、`deliverables`；
  入库 `*.sh` 缺执行位 → 打包阶段补 0755；跳过断链符号链接 `training/data/raw`。
- **切镜像实际走 `.env` 的 `SERVER_IMAGE`**：`deploy_latest.sh` 第 6 步 sed 会报
  「没找到镜像标签」AssertionError——该步失败可忽略，改 `.env` 的 `SERVER_IMAGE` 再 `up -d` 即可。
- 数据库在独立容器 `justice-db`；备份走 `deploy/backup-production.sh`；生产 compose 是服务器专属文件，
  已版本化 `deploy/production.docker-compose.yml`。
- ⚠ **默认 `127.0.0.1:8001` 是容器 loopback 陷阱**，必须填宿主 LAN IP。日志 `/data/justice/logs/server.log`。
- ⛔ **生产内网严禁出网**：源码走 tar 覆盖，禁 git/push；服务器 `git fetch/pull` 必失败。
  流程 = Windows `git archive HEAD`(扁平) → scp → 服务器 `tar xzf`(无 strip) → build。
  空气闸：出网机 build → save → scp → load → 设 `SERVER_IMAGE` → `up -d`。
- ⚠ `preflight-production.sh` 的 `expect` 硬编码旧模型布局，改模型布局须同步。
- 路由全集用 `app.openapi()["paths"]`（159 条）；`app.routes` 仅 8 条会误报。
  具名端点须注册在 `/{id}` 之前。`/api/v1/training/*` 必须 404（`test_deployment_route_contract.py` 反向断言）。

---

## 5. 环境铁律（给审查/运行者）

- Bash 沙箱 FS ≠ 真实 FS，判断存在性用 Glob/Read。
- 测 CRLF：**禁用** `grep -c $'\r'`；用 `tr -cd '\r' < f | wc -c`。
  Python `open(p,'w')` 写 CRLF，改 `.sh`/`.py` 用 `open(p,'wb')`。
- Python `D:\apps\anaconda3\python.exe`(3.11.7)；PATH 的 3.13 缺 python-docx。
- ⚠ `.py` 会被写 CRLF 而 `.gitattributes` 要 LF → 假改动；**Edit 改完必须 grep 复核**。
- ⚠ 往服务器贴脚本防零宽字符（`\u200b \ufeff \u00a0`）；贴完 `py_compile` + 计数。
- Gradle 需 `env -u JAVA_HOME`。
- 迁移已到 021（`015_widen_alembic_version` 在库，绝不改名 014 revision）；alembic 必须 `cd server/`。

---

## 6. 建议审查者重点核查清单

1. **选版器**（`ppt_engine.py:478` 起）：✅ **已关闭**。详见 `docs/LAYOUT_SELECTOR_VERIFICATION.md`——
   `_LAYOUT_AFFINITY` 与历史 if 分支逐分一致（旧代码重算 684/684）、新增版式零 if 增长、
   兜底 `weight` 中性。等价性已用父提交 `78fa1b4` 旧代码复算闭环。
2. **工作流同步**：✅ **已核验 + 已修复（含根治）**。详见 §2.2 / `docs/WORKFLOW_SYNC_VERIFICATION.md`——
   服务端兜底边界（截断、标注、死分支）已修；**桌面端根治已完成**：`update_node` 在「基础信息」节点编辑时
   同步解析写回 `basic_info`（`service.py:425-430`），回显丢失已修复，**桌面端 `WorkflowRepository.kt` 无需改动**。
   回归 `test_workflow_contract.py` 全文 **28 passed**。剩余仅为低优先产品决策（边界③子串匹配健壮性）。
3. **异步阻塞**：`format_check.py:56`、`ppt.py:247` 的 `asyncio.run` 在 async 路由内是否应改 `await`。
4. **并发与资源**：50 人场景下 35B 单端点是否瓶颈；临时文档清理与孤儿附件级联删。
5. **未证实项（不可凭历史记录断言）**：designed 模式耗时是否降到 10 分钟以内、
   生产承载人数——须在生产 35B 读取分段耗时 + 做 PPT/写作混合压测后才能下结论。

---

## 7. 已知缺口（roadmap，非 bug）

- PPT：版式库扩容 + 选版器；图表扩类 + KPI 看板；几何审计 + 35B 视觉复检；释放 davinci5,6。
- 多智能体写作 `WRITING_AGENT_GRAPH_ENABLED` 灰度。
- 修复 4 个 PPT 基线测试（2 learned 过期 + 1 小图表豁免 + 1 图表守卫断言文案）。
