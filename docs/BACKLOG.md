# 待办清单（2026-09-30）

状态说明：【待确认】= 我核到的现状与"待办"描述不符，需要主理人指明具体所指，避免改错方向。

---

## 1. 经费预核算 + 后处理校正范围扩展（本次新增，P2）

**背景**：本次（commit `09818d8` / `77a5bee`）在写作后处理里补了算术校正——修正「明确乘法表达式 = X 万」的机械算错。

实测案例：`1336人×150元×12个月=239.85万元` → 校正为 `240.48万元`。
根因：原正则只允许「数字 + 空白 + 运算符」，真实写法里数字后夹着中文量词（人/元/个月），**完全匹配不到**，算错也检测不出。已加 `_AMOUNT_UNIT = (?:[\u4e00-\u9fa5]{0,3})` 容忍量词。

### 第一层：起草前计算（治本）

**思路**：模型不该算数。程序算好，模型只引用。

1. **提取**：从**用户输入**（要素表单 / 指令原文）+ **RAG 证据**（本次检索到的材料）里提取确定的数量关系
   - 典型形态：人数 × 标准 × 期限（`1336人 × 150元/月 × 12个月`）、分项金额、单价 × 数量
   - 只提取**因子都能确定**的关系，缺任何一个就不算（避免程序编造）
2. **计算**：`Decimal` 精确算，**不用 float**（现有 `fix_simple_multiplication_amounts` 已用 Decimal，沿用）
3. **注入**：结果作为**已核实事实**写进起草指令，措辞固定为：

   ```
   经程序核算：1336人×150元/月×12个月＝240.48万元，正文中涉及该金额必须使用此数字。
   ```

**关键约束**：
- 注入的是"事实"不是"建议"，措辞要强约束（"必须使用此数字"）
- 必须标**来源**（用户输入 / 哪份 RAG 材料），与现有「外部事实必须有来源」规则一致；来源不明的**不注入**
- 与现有 prompt 第 12) 条不冲突：程序核算结果属于"已核实"，不是模型自述
- 注入位置：`_build_draft_instruction()`，建议作为独立段落放在「严格要求」之前，优先级最高

### 第二层：落库前校验兜底（扩展现有后处理器）

**思路**：模型仍可能写错（换写法、漏用注入值），落库前再校正一遍。

把校正范围从「单一连乘」扩展到经费高频句式：

| 句式 | 例子 | 状态 |
|---|---|---|
| 连乘 | `1336人×150元×12个月=239.85万元` | ✅ 已做（含中文量词容忍） |
| 分项求和 | 「一、…120万；二、…119.85万；**合计** 239.85万」分项和 ≠ 合计 | ⬜ 待做 |
| 人均 × 人数 | `人均150元/月 × 1336人 × 12个月 = …` | ⬜ 待做 |
| 标准 × 期限 | `150元/月 × 12个月 = 1800元` | ⬜ 待做 |
| 单价 × 数量 | `800元/件 × 320件 = 25.6万元` | ⬜ 待做 |
| 单位一致性 | 同段 `万元` / `元` 混用、数量级差 10⁴ | ⬜ 待做 |
| 占比 | 各项占比之和 ≠ 100% | ⬜ 待做 |
| 年度口径 | 「2027 年度」经费配「2026 年」落款 | ⬜ 待做（现只提示未来年份 > 今年+1） |

**⚠️ 校正日志目前不落库（真缺口，必须一并修）**：
`task_service.py:838` 拿到 `events`，但只在 `:894` 放进 **API 响应**（`"postprocess_events": events`）——**没写进 `ctx`、没随任务落库**。对比同段的 `citation_warnings`（:843 写进 ctx）和 `references`（:862 写进 ctx）都落了库。
→ 需加 `ctx["postprocess_events"] = events`，否则刷新页面 / 翻历史版本就查不到"这次改了什么"。

**涉及文件**：
- `server/app/application/writing/postprocessor.py` — `fix_simple_multiplication_amounts()`（:371）、`_MUL_AMOUNT_RE`（:362）；新增求和 / 人均 / 标准×期限 pattern
- `server/app/application/writing/task_service.py` — `:838` / `:894` events 落库；`:1146` `_build_draft_instruction()` 第一层注入点
- `server/app/application/writing/content_check.py` — 只标记不修改，适合放"疑似但无法确证"的项
- 测试：`server/tests/test_writing_guardrails.py`

**原则**：只在**等号 / 合计 / 共计 / 应为**这类明确结果语境下改，普通统计数字不猜（避免误改真实数据）。

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
