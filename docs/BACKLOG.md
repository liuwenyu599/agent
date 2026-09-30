# 待办清单（2026-09-30）

状态说明：【待确认】= 我核到的现状与"待办"描述不符，需要主理人指明具体所指，避免改错方向。

---

## 1. 数值计算正确性（通用，不限经费）—— 借助工具，不靠文本正则（本次新增，P1）

**范围修正**：不只是经费。任何数量关系算错都是 bug——金额、人数、面积、时长、比例、增长率、合计、人均、单位换算。

**手段修正**：**不能拿"正则匹配中文句子"当主力**。句式无穷尽，漏网是必然。
本次实证：`1336人×150元×12个月=239.85万元`（正确 240.48万）——原正则只允许「数字+空白+运算符」，被中文量词（人/元/个月）卡死，**完全匹配不到**，算错了也检测不出。已临时加 `_AMOUNT_UNIT = (?:[\u4e00-\u9fa5]{0,3})` 容忍量词，但这仍是"猜句式"，换一种写法照样漏。

**正确做法：程序算，模型只引用。**

### L0（最优，前提待确认）：真·工具调用

- **现状**：`chat` 表有 `tool_calls` 字段（`migrations/a112a03b86f2:257`、`models/chat.py:39`、`domain/chat/entities.py:24`），
  但 `infrastructure/ai/` 只有 `qwen.py` + `mock.py`，**全链路没有任何工具调用实现**——字段是预留的，从没用起来。
- **要做**：给写作链路加 `calculate` 工具（入参算式字符串 → 出参 `Decimal` 结果）；LLM 客户端支持 `tools` 参数与多轮工具结果回灌。
- **⚠️ 前置待确认**：生产 8003（qwen2.5-14B / vLLM）是否开了 `--enable-auto-tool-choice` + `--tool-call-parser=<parser>`。
  **没开则模型根本不会产出 tool_calls，L0 直接不可行 → 走 L1。**
- **风险**：14B 量级工具调用成功率不稳定；多轮回灌拉长链路，与 `docs/pptagent-fixes-for-gpt.md` §1.2 的 ~71s / 16K 上下文问题叠加。

### L1（推荐，不依赖模型能力）：结构化算式标记 + 程序求值

1. **prompt 约束**：凡涉及计算，**禁止心算**，必须写成固定标记，**只给算式不给结果**：
   ```
   <calc>1336*150*12/10000</calc>
   ```
   （单位换算也写进算式，直接出"万元"；模型不需要知道 1万=10000 怎么换算）
2. **程序求值**：`ast.parse` + **节点白名单**（数字 / `UnaryOp` / `BinOp: + - * /`），**严禁 `eval`**；用 `Decimal` 算，**不用 float**。
3. **回填**：把标记替换为格式化结果，正文保留可读算式（如「1336×150×12＝240.48万元」）。
4. **失败处理**：标记不合法 / 解析失败 → **不猜**，交给 L2 兜底，并在质量门提示"存在未核算的算式"。

**为什么比正则强**：标记是模型**主动产出**的固定格式，不是我们反向去猜自然语句——覆盖率与句式无关，换任何中文写法都不会漏。

### L2（兜底，降级为副手）：落库前校验 + 日志

现有后处理**从"主力"降为"兜底"**：

| 句式 | 例子 | 状态 |
|---|---|---|
| 连乘 | `1336人×150元×12个月=239.85万元` | ✅ 已做（含中文量词容忍） |
| 分项求和 | 「一、…120万；二、…119.85万；**合计** 239.85万」分项和 ≠ 合计 | ⬜ 待做 |
| 单位数量级 | 同段 `万元` / `元` 混用、差 10⁴ | ⬜ 待做 |
| 占比 | 各项占比之和 ≠ 100% | ⬜ 待做 |
| 年度口径 | 「2027 年度」经费配「2026 年」落款 | ⬜ 待做（现只提示未来年份 > 今年+1） |

**⚠️ 校正日志目前不落库（真缺口，必须一并修）**：
`task_service.py:838` 拿到 `events`，但只在 `:894` 放进 **API 响应**（`"postprocess_events": events`）——**没写进 `ctx`、没随任务落库**。对比同段的 `citation_warnings`（:843 写进 ctx）和 `references`（:862 写进 ctx）都落了库。
→ 需加 `ctx["postprocess_events"] = events`，否则刷新页面 / 翻历史版本就查不到"这次改了什么"。

### 涉及文件

| 层 | 文件 | 说明 |
|---|---|---|
| L0 | `server/app/infrastructure/ai/qwen.py`、新增 tool 执行器 | 需先确认 vLLM 参数 |
| L1 | `server/app/application/writing/postprocessor.py`（新增 `eval_calc_marks()`）、`task_service.py:1146` `_build_draft_instruction()` | 加 `<calc>` 约束与求值回填 |
| L2 | `postprocessor.py:371` `fix_simple_multiplication_amounts()`、`content_check.py` | 只标记/只改明确语境 |
| 日志 | `task_service.py:838 / :894` | events 落库 |
| 测试 | `server/tests/test_writing_guardrails.py` | 覆盖：算式精度、非法标记、单位换算 |

### 原则（不可破）

- **程序算，模型引用**——不让模型心算
- **`Decimal`，不用 float**
- **严禁 `eval`**，用 `ast` 节点白名单
- 只在**等号 / 合计 / 共计 / 应为**这类明确结果语境下改，**普通统计数字不猜**（避免误改真实数据）

---

## 2. 工作台起草注入知识库范文（结构 / 格式 / 用语模仿，P1）

**现状**：`task_service._retrieve()`（:1281）已在检索范文/材料（:411 定义，:681 / :711 / :908 调用），检索结果进了 `sources`。但起草 prompt 里只有**一句软约束**：

```
6) 语言规范、正式、符合党政机关公文写作惯例；同文种知识库范文命中时优先参考其体例和固定用语；
```
（:1243）—— 范文正文**没有**作为 few-shot 注入 instruction，模型只能靠自己"记得"体例。

**要做**：把命中的范文作为**结构化 few-shot** 注入 `_build_draft_instruction()`：
1. 只抽**骨架**：一级条目序列（如"一、发放依据 / 二、发放对象 / …"），不整篇塞
2. 抽**固定用语**：开头引据句式、条目起始词、结尾结语
3. 显式约束"模仿其结构粒度与用语，不得照抄事实数据"
4. **长度预算**：DP9B 上下文只有 16K，范文骨架需截断（建议 ≤300 字），否则会挤压 history、加剧 ~71s 延迟（见 `docs/pptagent-fixes-for-gpt.md` §1.2）

**涉及文件**：`server/app/application/writing/task_service.py`（:1146 `_build_draft_instruction`、:1281 `_retrieve`）

---

## 3. xlsx 解析补上（交付阻塞项，P0）【待确认】

**我核到的现状：后端知识库链路已支持 xlsx。**
- `server/app/application/knowledge/document_service.py:374` — `if suffix == 'xlsx':` 分支已存在
- commit `6e02415 fix(knowledge): add xlsx parsing without regressing existing extractors`
- `server/app/core/config.py:221` — `SUPPORTED_DOC_TYPES` 已含 `.xlsx`
- PPT 材料链路：`server/app/application/ppt/service.py:1003-1041` 用 openpyxl 已实现
- 用户批量导入：`server/app/interfaces/users.py:130` 用 openpyxl 已实现

**需要确认**"阻塞"具体指哪一条：
- [ ] 桌面端（Kotlin）上传/预览 xlsx？
- [ ] 数据资产批量导入（`training/service.py`）的 xlsx 分支？
- [ ] 某个具体文件解析仍失败（有报错样例？）
- [ ] 已修但**未部署到生产**（生产镜像未更新 → 表现为"线上仍不支持"）

---

## 4. 模板预览页结构字段解析修复（P1）

**根因已定位**：服务端 `structure` 的正式结构是**对象数组** `[{name, guide}, ...]`，但列表/预览页把它当**字符串数组**读。

```kotlin
// desktop/.../features/templates/TemplatesScreen.kt:554
val structure = t["structure"].arr().map { it.str() }.filter { it.isNotBlank() }
```
`it.str()` 对 `{"name":"一、…","guide":"…"}` 取到空串 → `filter` 后为空 → **"章节结构"整块不渲染**。

**已存在的正确写法**（二选一复用）：
- `TemplatesViewModel.kt:61-69` `normalizePreviewStructure()`：`item.obj()?.get("name").str().ifBlank { item.str() }` —— 但它只对 `preview` 生效（:74/:77），列表里的原始对象 `t` 没走这一步。
- `TemplatesScreen.kt:708` 编辑弹窗：`editing?.get("structure").arr().mapNotNull { it.obj() }` —— 正确。

**修法**：把 :554 改成与 ViewModel 一致的兼容读法（对象取 `name`，兜底取字符串）；或让列表渲染统一走 `normalizePreviewStructure()`。

**注意**：不能顺手把保存路径也改成字符串数组——`guide` 等结构化字段会丢（ViewModel 注释已明确警告）。

**涉及文件**：`desktop/src/jvmMain/kotlin/com/judicialai/desktop/features/templates/TemplatesScreen.kt:554`、`TemplatesViewModel.kt:57-69`
**验证**：沙箱无 JDK 17，无法本地编译；需打包机 `./gradlew compileKotlinJvm` 验证。

---

## 5. 批量导入用户名校验（P2）【待确认】

**我核到的现状：校验已存在。**
- `server/app/interfaces/users.py:114` — `_USERNAME_RE = re.compile(r"^[A-Za-z0-9]{3,32}$")`
- `:209` — `if not _USERNAME_RE.fullmatch(username):` 逐行校验并给出行号级报错
- `:98` — 表头别名映射（username / 用户名 / 账号）

**可能的缺口**（需确认要补哪个）：
- [ ] 规则过严：**不允许中文、下划线、点、连字符**。司法局实际账号若含中文（如"张三"）或 `zhang_san` 会被拒
- [ ] 无**文件内跨行重复**检测（同一份表里两个同名，会有一行失败在 create 阶段，报错不够前置）
- [ ] 无**与库内已有用户**的提前查重（目前靠 `create_user` 返回错误，非前置校验）
- [ ] 全角字符未归一（全角数字/字母会被判非法）
- [ ] 邮箱格式未校验（只查非空，:205）

**涉及文件**：`server/app/interfaces/users.py:114 / :195-224`

---

## 附：本次会话已交付（供对照）

| commit | 内容 |
|---|---|
| `77a5bee` | fix(writing): 字数要求不得抵消函件结构约束 |
| `09818d8` | fix(writing): 补齐三处后处理漏网 + 函件口气约束 |
| `10f1776` | fix(pptagent): Research.yaml 撤销与模型先验对抗的 matplotlib 禁令 |
| `b709f40` | chore: PPTAgent 部署脚本与交接文档入库 |
| `552344e` | feat(desktop): Inno Setup 中文安装包「云法智办」 |

**⚠️ 后端改动（`09818d8` / `77a5bee`）需重启后端才生效**，uvicorn 不带 `--reload` 不会加载新代码。
