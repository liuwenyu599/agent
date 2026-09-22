# 格式校验能力侦察报告（只读审计）

> 目标：判断「公文格式审校工作台」三栏页（单项应用 / 单项撤销 / 修改前后对比 / 重新校验 / 导出修正稿）后端到底能做到哪一步。
> 方式：读源码 + 读线上 SQLite（`server/data/judicial_app.db`）实测数据。**未改动任何源码。**
> 环境限制：本机 PATH 上的 Python 3.13 无 `python-docx`（`ModuleNotFoundError: No module named 'docx'`），项目运行环境 venv 不在仓库内 → **无法在本地实跑引擎**。以下结论凡涉及"运行行为"的，均标注为「源码判定」，未标「实测」的不要当作已验证。

---

## 0. 一句话结论

**检测能力：规则类检查项覆盖完整（12 项全覆盖），且每一项都有对应的自动修正实现。**
**缺口不在"能不能改"，而在三件事：① issue 没有唯一 id；② 没有任何接口返回"格式属性"（只有段落文本），所以"修改前后对比"目前拿不到真数据；③ 没有"重新校验"与"已应用状态持久化"。**
**好消息：现有 `apply_fixes()` 永远是「从原始文档 + 已接受集合」全量重放，不是增量叠加 → 「单项撤销」在语义上天然成立，不需要做反向操作。**

---

## ① 真实支持「检测」的检查项清单

引擎：`server/app/application/format_check/check_engine.py`
规则数据：`format_rules` 表（`checks` 为 JSON，**可配，不写死**），目标类型 `VALID_RULE_TARGETS` 在 `domain/format_check/entities.py:6-8`。

| # | 检查项 | 是否实现 | 实现位置（文件:行） | 可配 / 写死 |
|---|---|---|---|---|
| 1 | 字体（font_name） | ✅ | `check_engine.py:245-249` | **可配**（`checks.font_name`，取 eastAsia 优先 `:44-56`） |
| 2 | 字号（font_size_pt） | ✅ | `check_engine.py:251-255` | **可配**（容差 ±0.5pt） |
| 3 | 加粗（bold） | ✅ | `check_engine.py:257-261` | **可配** |
| 4 | 对齐（alignment） | ✅ | `check_engine.py:263-270` | **可配**（left/center/right/justify；未显式设置按左对齐处理 `:267`） |
| 5 | 首行缩进（first_line_indent_chars） | ✅ | `check_engine.py:279-294` | **可配**（按 `首行缩进pt ÷ 字号pt` 反算字符数，容差 ±0.3） |
| 6 | 行距（line_spacing_pt） | ✅ | `check_engine.py:272-277` | **可配**（只认固定值磅；倍数值会判为"未设置"） |
| 7 | 段前 / 段后（space_before_pt / space_after_pt） | ✅ | `check_engine.py:296-303` | **可配** |
| 8 | 页边距（上/下/左/右） | ✅ | `check_engine.py:191-223`（`_check_page`） | **可配**（`*_cm`，容差 ±0.05cm） |
| 9 | 页面尺寸（page_width_cm / page_height_cm） | ✅ 引擎支持 | `check_engine.py:200-201, 208-222` | **可配**，但**线上无默认规则**（实测 21 条规则里没有）→ 默认不检查 |
| 10 | 标题格式 | ✅ | `check_engine.py:129-133`（首个非空段落=标题）+ 走 `_check_paragraph` | **可配**，target=`title` |
| 11 | 正文格式 | ✅ | `check_engine.py:136, 152-154` | **可配**，target=`body` |
| 12 | 章节标题格式 | ⚠️ 部分 | `check_engine.py:146-151` | 仅 **一级「一、」** 与**二级「（一）」**；**三级「1.」不检查** —— `_RE_H3` 在 `:41` 定义了但**从未被调用**（grep 全文仅 3 处：定义 + H1 + H2），且 `VALID_RULE_TARGETS` 无 `heading3` |
| — | 落款 / 成文日期 | ✅ 仅对齐 | `check_engine.py:156-168` | 只对文末 1–2 段做 `alignment` 检查 |
| — | 多余空行 / 行尾空格 | ✅ | `check_engine.py:311-328` / `:330-342` | **可配**（`no_extra_blank_lines` / `no_trailing_spaces`） |
| — | AI 辅助（结构层次、重复段落、占位符、文号） | ✅ | `check_engine.py:366-425` | 写死 prompt；**`fix_hint` 恒为 `None`** |

**实测**（线上库 `format_rules` 21 条，`is_active=1`，`is_default=1`）：

```
页面上边距37mm/page  下边距35mm  左边距28mm  右边距26mm
标题：字号22pt 居中 小标宋 不加粗 段后0
正文：字号16pt 首行缩进2字符 行距28.8pt 段前段后0
一级标题：字号16pt 黑体 ；二级标题：字号16pt 楷体_GB2312
落款右对齐 / 成文日期右对齐
通用：无连续空行 / 无行尾空格
```

**关键结构性限制（写死，不可配）：**
- 段落属性只取**该段第一个非空 run** 作代表（`:230`），同段混排字体检测不到。
- 页面检查只取 `doc.sections[0]`（`:194`）。
- 只处理 `doc.paragraphs`，**表格、页眉页脚、页码、红头、文号、主送机关一律不检查**。

---

## ② 真实支持「自动修改」的检查项清单

入口：`FormatCheckEngine.apply_fixes()` `check_engine.py:428-489`
分发：`:451-476`；段落级 `_apply_paragraph_fix()` `:509-539`；页面级 `_apply_page_fix()` `:541-552`；字体 `_set_run_font()` `:492-507`

| 检查项 | 能否自动改 | 改法（证据位置） |
|---|---|---|
| 字体 | ✅ | `:515-516` → `_set_run_font(font_name=...)`：同时写 `run.font.name` 与原始 XML 的 `w:rFonts` 的 `ascii/hAnsi/eastAsia`（`:496-503`） |
| 字号 | ✅ | `:517-518` → `run.font.size = Pt(value)`（`:504-505`） |
| 加粗 | ✅ | `:519-520` → `run.font.bold = bool(value)`（`:506-507`） |
| 对齐 | ✅ | `:521-524` → `pf.alignment = _ALIGN_MAP[value]` |
| 首行缩进 | ⚠️ 能改但有单位 bug | `:527-535`：`pf.first_line_indent = Pt(12 * chars)`（**硬编码 12pt/字符**）+ 写 `w:firstLineChars` |
| 行距 | ✅ | `:525-526` → `pf.line_spacing = Pt(value)` |
| 段前 / 段后 | ✅ | `:536-539` → `pf.space_before / space_after = Pt(value)` |
| 页边距 | ✅ | `:541-552` → `setattr(sec, 'top_margin'…, Cm(value))`，**遍历全部 section** |
| 页面尺寸 | ✅（引擎层） | 同上，`page_width` / `page_height` 属性存在即可 setattr；线上无默认规则所以不会触发 |
| 行尾空格 | ✅ | `:466-471` 逐 run `r.text = r.text.rstrip()` |
| 多余空行 | ✅ | `:472-474` 收集索引 → `:478-484` **按索引降序删除** XML 节点（避免位移） |
| AI 类问题 | ❌ | `fix_hint` 为 `None` → `:456` 取不到 `htype`，直接跳过 |

**是 python-docx 直接改 run/paragraph 属性，不是文本替换/占位**（除 `trim_text` / `delete_paragraph` 两项确实是文本/节点操作）。

### 输出文件落盘规则（`application/format_check/service.py`）

| 产物 | 路径 | 位置 |
|---|---|---|
| 源文件（校验后保留） | `settings.DATA_DIR/format-check/{record_id}.docx` | `service.py:58-59`，`:107-108`（`tmp_path.replace(...)`） |
| 上传临时 | `{uuid4}_{原文件名}` | `service.py:85` |
| 预览稿 | `{record_id}_preview.docx`（**每次调用覆盖**） | `service.py:173` |
| 修正稿 | `{record_id}_fixed.docx`（**每次调用覆盖**） | `service.py:182` |
| 下载文件名 | `修正稿_{原文件名}` | `service.py:184` |
| 非 docx | 校验后 `unlink` 删除 | `service.py:109-110` |

实测 `server/data/format-check/` 下确有 `*.docx` 与 `*_fixed.docx` 成对存在。

### `accepted_indices` 的语义（关键）

**它是 issue 数组下标，不是段落索引。**
证据：`service.py:174` `self.engine.apply_fixes(path, record.issues or [], accepted_indices, out_path)` → `check_engine.py:454` `issue = issues[idx]` → 再从 `issue["paragraph_index"]` 取段号（`:457`）。

即：前端传 `[0,1,2]` = 应用 `record.issues` 的第 0/1/2 条；每条自己知道要改哪一段（或哪页）。

### `preview_fix` 返回什么（**重点**）

```python
# service.py:170-175
def preview_fix(self, record_id, accepted_indices, user):
    fixed = self.engine.apply_fixes(path, record.issues or [], accepted_indices, out_path)
    return {"paragraphs": [{"index": i, "text": t} for i, t in enumerate(fixed)]}
```

**不是逐段 before/after 对照。** 它只有"应用后的全文段落文本"。`apply_fixes` 最后一行 `check_engine.py:489`：

```python
return [p.text for p in DocxDocument(str(out_path)).paragraphs]
```

⚠️ **致命点：绝大多数格式修正（字体/字号/加粗/对齐/缩进/行距/间距/页边距）根本不改变段落文本。** 也就是说，对 12 项里的 9 项，`preview-fix` 返回的 before/after 文本**完全一致、没有任何差异**，对比栏会是空白。只有 `trim_text` 与 `delete_paragraph` 会体现为文本/段落数变化。

→ **`preview_fix` 不能直接复用为"修改前后对比"的数据源。** 它是"改完之后的文本预览"，不是 diff。

---

## ③ issue 的真实数据结构（实测）

表：`format_check_records`（`infrastructure/database/models/format_check.py:26-37`），`issues` 是 **JSON 列，不是关联表**。

实测 dump（`server/data/judicial_app.db`）：

```json
{
  "location": "正文", "element": "结构层次",
  "current": "二、支出功能分类科目、三、项目分配依据…",
  "expected": "应使用统一的结构层次序号，如“一、”“（一）”“1.”",
  "suggestion": "将“二、”“三、”改为…",
  "source": "ai", "severity": "warning",
  "paragraph_index": null, "fix_hint": null
}
```

字段清单（实测 key 集合，9 个）：

| 字段 | 有？ | 说明 |
|---|---|---|
| `location` | ✅ | 人类可读位置，如「第3段（一级标题）」「页面设置」「文末（成文日期）」 |
| `element` | ✅ | 检查项名，如「字号」「对齐方式」「首行缩进」 |
| `current` / `expected` | ✅ | **已格式化的人类可读字符串**（`_fmt_value` `:59-75`：如 `16磅` / `居中` / `缩进2字符` / `未设置`）→ **这就是现成的 before/after 文案** |
| `suggestion` | ✅ | 建议文案 |
| `source` | ✅ | `rule` / `ai` |
| `severity` | ✅ | 来自规则（实测有 `error` / `warning` / `info` 三档） |
| `paragraph_index` | ✅ 但可能为 `null` | 段落下标；**页面级与 AI 级为 `null`** |
| `fix_hint` | ✅ 但可能为 `null` | `{"type":"paragraph","field":"font_size_pt","value":16}` / `{"type":"page","field":"top_margin_cm","value":3.7}` / `{"type":"trim_text"}` / `{"type":"delete_paragraph"}` / `null` |
| **`id`** | ❌ **没有** | **决定性问题：单项 apply/undo 目前只能靠数组下标定位** |
| `type` | ❌ 没有 | 只有 `element`（中文名）与 `fix_hint.type` |
| `before` / `after` | ❌ 没有 | 但有语义等价的 `current` / `expected` |

**`fix_hint` 的 4 种 type**（`check_engine.py:221 / 242 / 325 / 341 / 419`）：`page`、`paragraph`、`trim_text`、`delete_paragraph`。

---

## ④ `/format-check/*` 全部接口契约（以源码为准）

`server/app/interfaces/format_check.py`，统一前缀 `/api/v1`。除规则 CRUD 用 `require_admin_or_above` 外，全部 `Depends(get_current_user)`。

| Method | Path | 请求 | 响应 | 权限 |
|---|---|---|---|---|
| POST | `/format-check/check` | `multipart: file`；query `use_ai:bool=true`、`rule_ids:str?`（逗号分隔） | `{id, record_id, filename, file_type, ai_used, check_mode:"rule"\|"ai_only", issue_count, issues:[…含 fix_hint], rules_used:[{id,name,target}]}` | 登录 |
| GET | `/format-check/records` | query `page=1&page_size=20` | `{total, page, page_size, data:[{id, filename, file_type, issue_count, rule_issue_count, ai_issue_count, created_at}]}` | 登录（按 user_id 隔离 `service.py:129`） |
| GET | `/format-check/records/{id}` | — | `{id, filename, file_type, issues, issue_count, rule_snapshot, created_at}` | 本人或 `ADMIN_OR_ABOVE`（`service.py:135-141`） |
| GET | `/format-check/records/{id}/paragraphs` | — | `{paragraphs:[{index, text}]}` ← **只有文本，没有格式属性** | 同上；非 docx → 400；源文件丢失 → **410** |
| POST | `/format-check/preview-fix` | `{record_id, accepted_indices:[int]}` | `{paragraphs:[{index, text}]}`（应用**之后**的全文） | 同上；**每次覆盖写 `{id}_preview.docx`** |
| POST | `/format-check/fix` | `{record_id, accepted_indices:[int]}` | `FileResponse` → `修正稿_{filename}.docx` | 同上 |
| GET | `/format-check/rules` | — | `[{id,name,target,checks,severity,is_default,is_active,remark,created_at}]` | 登录 |
| POST | `/format-check/rules` | `RuleRequest{name,target,checks:dict,severity,is_default,is_active,remark}` | `{id, message}` | **管理员** |
| PUT | `/format-check/rules/{id}` | 同上 | `{message}` | **管理员** |
| DELETE | `/format-check/rules/{id}` | — | `{message}` | **管理员**（硬删除） |

**没有的接口**：`DELETE /records/{id}`、**`POST /records/{id}/recheck`**、`PATCH /records/{id}`、`GET /records/{id}/modifications`、任何返回段落格式属性的接口。

---

## ⑤ 依赖与可行性

`server/requirements-server.txt:36-43`：`python-docx==1.2.0`、`python-pptx==1.0.2`、`lxml==6.1.1`、`openpyxl==3.1.5`
`server/requirements-kylin.txt:43,50`：`python-docx==1.2.0`、`lxml==6.1.1  # [需验证] 含 C 扩展`

**技术上全部可做**（`python-docx` 已支持）：字体 ✅、字号 ✅、加粗 ✅、对齐 ✅、首行缩进 ✅、行距 ✅、段前段后 ✅、页边距 ✅、页面尺寸 ✅。且**引擎里已经全部写好了**（见 ②）。

---

## ⑥ 是否已有「应用单项修改 / 撤销」机制

**结论：完全没有"修改状态"机制，但"按集合重放"的引擎语义已经天然支持撤销。**

- 服务端**没有任何地方**持久化"哪些已应用"：`format_check_records` 表只有 `issues / issue_count / *_issue_count`，**无 `applied_indices`、无 `modifications`、无 `current_file`**。
- 已应用集合只存在于**桌面端内存**：`FormatCheckViewModel.accepted: Set<Int>`（`features/formatcheck/FormatCheckViewModel.kt:29`），且 `openRecord()` 里默认 `accepted = issues.indices.toSet()`（**默认全选**）。
- 桌面端**从未调用 `/preview-fix`**：`Endpoints.FormatCheck.PREVIEW_FIX` 常量存在（`Endpoints.kt:95`），但 `FormatCheckRepository.kt` 里**没有**对应方法（只读到 `check / records / paragraphs / fix / rules*`）。
- `fix_document` 与 `preview_fix` **每次都从原始文件 `{id}.docx` 重放**（`service.py:172, 181` → `_get_record_docx`）→ **同一集合重复调用结果幂等；集合里去掉一项 = 撤销。** 这是本轮最重要的可复用性质。

---

## ⑦ Web 版参考实现

**仓库内不存在 Web 版格式校验前端源码。** 全仓 `*.vue/.js/.jsx/.ts/.tsx` 命中 0（唯一 `.html` 是 `deliverables/` 下的静态原型稿）。

现有可参考物（都是**静态原型，无真实逻辑**，不能当实现参考）：

| 文件 | 形态 | 要点 |
|---|---|---|
| `deliverables/desktop-v31-product-preview.html:771-838` | 桌面 v3.1 原型 | **已是三栏**：`fc-l` 问题列表（含错误/警告/建议图标）→ `fc-c` 文档正文预览（bad/warnx 高亮）→ `fc-r` 「问题解释 + 修改建议（当前 / 建议 两行对照）+ 应用建议 / 忽略此项 + 已通过项」。底部注明：「应用建议」调用后端真实的 `/preview-fix` 与 `/fix`；前端不虚构自动修复能力。 |
| `deliverables/app-ui-preview.html:470-498` | 旧 Web 原型 | 两栏：得分卡 + 「一键修正」+ 问题明细表。无对比、无撤销。 |
| `desktop/.../features/formatcheck/FormatCheckScreen.kt` | **真实客户端** | 三个 Tab（校验结果 / 历史记录 / 规则管理）+ StatCard（已选修正 = `vm.accepted.size`）+ 勾选 + 导出修正稿。**非三栏工作台**，`Endpoints.kt:90-99` 已备齐全部端点。 |

**用户给的"三栏 + 修改前/当前版本 + 已修改 6 项"参考截图在本仓库中不存在对应实现**（全仓 grep「修改前 / 当前版本 / 已修改 / 撤销修改 / 份修改」在 `.html/.md/.kt` 中 0 命中）。它要么是外部产品参考，要么是尚未落盘的稿子 —— **建议向用户确认截图来源**，不要假设有现成实现可搬。

---

## ⑧ gap 清单

### A. 只能检测、不能自动改

| 项 | 原因 |
|---|---|
| 全部 AI 类问题（结构层次、重复段落、占位符、文号格式、要素缺失） | `fix_hint` 恒为 `None`（`check_engine.py:419`），无定位（`paragraph_index=null`）也无执行动作 |
| PDF / txt / md | 引擎只对 docx 落原文（`service.py:107-110`），`_get_record_docx` 直接 400（`:153-159`） |

### B. 完全没实现（本轮必须新建能力）

| # | gap | 影响 | 证据 |
|---|---|---|---|
| G1 | **issue 无唯一 id** | 单项 apply/undo 只能靠数组下标；一旦客户端过滤/排序/分页，下标即失效 | 实测 issue key 集合无 `id` |
| G2 | **没有任何接口返回"格式属性"** | "修改前后对比"拿不到真数据 —— `/paragraphs` 只有 `text`，`/preview-fix` 只有改后 `text`，而 12 项里 9 项的修正**不改变文本** | `service.py:166-168, 175`；`check_engine.py:489` |
| G3 | **无「已应用状态」持久化** | 刷新/重开记录后 `applied` 丢失；无法支撑"已修改 6 项"这种需要服务端认可的计数 | `models/format_check.py:26-37` 无相关列 |
| G4 | **无「重新校验」接口** | 修正后想复检只能把修正稿**重新上传**（生成新 record），拿不到"同一份文档的二次校验" | `interfaces/format_check.py` 无 recheck；`check` 只接受 multipart |
| G5 | 无记录删除/清理 | `_preview.docx` / `_fixed.docx` 反复覆盖但无回收 | — |
| G6 | 三级标题「1.」不检查 | `_RE_H3` 定义未用；`VALID_RULE_TARGETS` 无 `heading3` | `check_engine.py:41` vs `:146-151` |
| G7 | 页面尺寸无默认规则 | 引擎支持（`:200-201`）但线上 21 条规则里没有 | 实测 DB |
| G8 | 表格 / 页眉页脚 / 页码 / 红头 / 文号 / 主送机关 全不检查 | 引擎只遍历 `doc.paragraphs` | `check_engine.py:122` |

### C. 已存在的缺陷（会直接破坏"重新校验"体验，必须一并处理）

| # | 缺陷 | 源码判定 | 后果 |
|---|---|---|---|
| B1 | **首行缩进修正单位不一致** | 检测按 `缩进pt ÷ 字号pt` 反算字符（`:288-290`，正文字号 16pt）；修正却写 `Pt(12 × chars)`（`:529`，硬编码 12pt/字符）。对"2 字符"：检测期望 32pt，实际写 24pt → 复检得 `24/16 = 1.5`，与期望 2 差 0.5 > 容差 0.3 → **重新校验仍报同一问题** | 「应用修改 → 重新校验 → 问题还在」，直接击穿工作台可信度（**源码判定，未实跑**） |
| B2 | 段落属性只取首个非空 run（`:230`），修正却作用于**全部 run**（`:514`） | 混排段落检测与修正口径不一致 | 复检可能仍报 |
| B3 | 页面检查只看 `sections[0]`（`:194`），修正却遍历全部 section（`:547`） | 多节文档口径不一致 | 同上 |
| B4 | `seed_v3.py:176-183` 引用 `FormatRuleModel.ruleset`，但 `models/format_check.py` **没有 `ruleset` 字段**（迁移 `004` 加过、`downgrade` 又删了） | `seed_format_rules` 会抛 `AttributeError`，被 `run_all` 的 try/except 吞掉（`:220-225`） | **线上 21 条规则是历史遗留灌入的，新环境重灌会静默失败** → 降级成"AI 全面审查" |

---

## ⑨ 引入 Modification / originalDocument / currentDocument 的最小改动落点

### 核心判断：`Modification` 应**计算**出来，不要**存**下来

理由：① `record.issues` 落库后不可变；② `before` / `after` 现成就是 `issue.current` / `issue.expected`；③ `applied` 就是"下标是否在已应用集合里"。存一份 `Modification` 表会和 `issues` 双写、漂移。**只需持久化一个集合。**

### 推荐方案 B：按「原始文档 + 已应用集合」重新生成（**推荐**）

| | 方案 A：服务端持久化 currentDocument（增量叠加） | 方案 B：按集合重放（**推荐**） |
|---|---|---|
| 引擎改造 | 需要"在当前稿上再改一次"，即 `apply_fixes` 源路径要能指向 `_current.docx` | **零改造** —— 就是现有 `apply_fixes` 的语义 |
| 撤销 | 必须实现**反向操作**（字体/字号/对齐可反，但 `delete_paragraph` 删掉的内容不可逆；且叠加后无法回到中间态） | **天然正确**：集合里删掉一项即可，因为每次都从原始稿重放 |
| 一致性 | 并发/失败重试会破坏中间态，需要事务与文件锁 | 幂等，重放即可恢复 |
| 存储 | 每个中间态一个文件 | 只多一个 `_current.docx`（按需生成）或干脆不落盘 |
| 代价 | 大 | 每次全量重放：O(issue 数) + 一次 docx 读写。公文 docx 通常 <1MB，**可接受**（实测 `FORMAT_CHECK_MAX_SIZE` 上限 20MB） |

→ **结论：采用方案 B。不实现反向操作式撤销。**

### 具体落点（最小改动）

**1）表 / 迁移（新增 1 列，不动既有列）**
- `format_check_records` 增 `applied_indices`（JSON，默认 `[]`）、`updated_at`（DateTime）
- 新迁移 `008_v33_format_check_applied.py`，`down_revision="007_v32_agent_layers"`，沿用 `007` 的 inspector 守卫风格

**2）issue 加稳定 id（改 1 处）**
- `service.py:96-104` 落库前给每个 issue 补 `"index": i`（最小）或 `"id": f"{record.id}#{i}"`（更稳，推荐）
- 位置：`check_upload()` 内 `issues = result["issues"]` 之后、`self.records.add(...)` 之前
- 老记录兼容：`get_record` 下发时若缺 `index`，按下标补

**3）服务层新增 2 个方法（`service.py`）**
- `set_applied(record_id, indices, user)` → 校验下标范围 → 写 `applied_indices` → 返回全量 `modifications`
- `build_modifications(record)` → 由 `issues` + `applied_indices` 计算：
  `Modification{issueId, location(issue.location), element(issue.element), type(issue.fix_hint?.type ?? "manual"), before(issue.current), after(issue.expected), applied(index ∈ applied_indices), appliedAt, fixable(bool)}`

**4）新增「格式属性」读取（补 G2，这是对比栏的唯一真数据源）**
- 新增 `_paragraph_props(p)`：复用引擎已有的读取逻辑（`_run_font_name` `:44`、`run.font.size`、`run.bold`、`p.alignment`、`pf.line_spacing`、`pf.first_line_indent`、`pf.space_before/after`）
- 新增 `GET /format-check/records/{id}/paragraph-properties` → `[{index, text, props:{font_name, font_size_pt, bold, alignment, line_spacing_pt, first_line_indent_pt, space_before_pt, space_after_pt}}]`
- `POST /preview-fix` 响应**扩展**（向后兼容，保留 `paragraphs`）：`paragraphs[i].props` 同上；并增 `page_props`
- 客户端 diff = `paragraph-properties`（before） vs `preview-fix.paragraphs[i].props`（after）

**5）接口（新增 3 个，改 0 个既有语义）**
| Method | Path | Body / 响应 |
|---|---|---|
| `PUT` | `/format-check/records/{id}/applied` | `{applied_indices:[…]}` → `{applied_indices, modifications:[Modification], applied_count}` |
| `GET` | `/format-check/records/{id}/modifications` | `{modifications:[Modification], applied_count, total}` |
| `GET` | `/format-check/records/{id}/paragraph-properties` | `{paragraphs:[{index,text,props}], page:{…}}` |
| `POST` | `/format-check/records/{id}/export` | 可选：把 `/fix` 改成不带 body、直接用持久化的 applied 集合（**建议保留 `/fix` 原样**，避免破坏桌面端现有调用） |

**6）「重新校验」（G4）最小解**
- 不再新增"免重传复检"接口。改为：工作台「重新校验」= 把当前修正稿（`_fixed.docx`）**重新 POST `/format-check/check`**，前端拿到新 record 后**提示"已生成第 N 次校验记录"**，并在新旧记录间做 issue 收敛对比（纯前端，用 issues 数组比对即可）。代价最小且不新增后端状态机。
- 前提：先修 B1（首行缩进单位 bug），否则复检必然还在报警。

**7）桌面端落点**
- `FormatCheckRepository.kt`：补 `previewFix()`、`paragraphProperties()`、`setApplied()`、`modifications()`
- `FormatCheckViewModel.kt`：`accepted` 改为 `Set<String>`（issueId）或保留 `Set<Int>`（下标，与后端一致即可）；新增 `modifications`、`propsBefore`、`propsAfter`
- `FormatCheckScreen.kt`：三栏重构（`AppShell` 内，不动导航）

---

## ⑩ 明确不做的事

1. **本轮不实现 AI 类问题的自动修正** —— 它们的 `fix_hint` 为 `null`、无段落定位、改法不可判定；只作为"建议"展示。
2. **本轮不实现 PDF / txt / md 的修正** —— 引擎只对 docx 保留源文件，`_get_record_docx` 直接 400。
3. **本轮不实现"反向操作式撤销"** —— 采用按集合重放，撤销=改集合，不做 inverse apply。
4. **本轮不实现三级标题「1.」检查** —— `_RE_H3` 未接线且 `VALID_RULE_TARGETS` 无 `heading3`，属于新增能力，不在本次范围。
5. **本轮不实现表格 / 页眉页脚 / 页码 / 红头 / 文号 / 主送机关检查** —— 引擎只遍历 `doc.paragraphs`，属引擎级扩展。
6. **本轮不实现页面尺寸默认规则** —— 引擎已支持，只差规则数据；如需要由管理员在「规则管理」里加一条 `page_width_cm` / `page_height_cm` 即可，**不改代码**。
7. **本轮不修改 `/format-check/fix` 的既有请求/响应语义** —— 桌面端正在调用，保持兼容。
8. **本轮不动 HOME、不动 Agent/RAG、不动模型服务**（用户明确要求）。
9. **不把 `Modification` 建成实体表** —— 它是 `issues × applied_indices` 的派生视图，建表会造成双写与漂移。

---

## 附：待确认

1. 用户参考截图（三栏 + 修改前/当前版本 + 已修改 6 项）的来源 —— 仓库内无对应实现，需确认是外部产品参考还是新稿。
2. 「修改前后对比」要对比到什么粒度：**段落文本**（现有 `/paragraphs` 已够）还是**格式属性**（需新增 `paragraph-properties`）？按审校场景应是后者，但需产品确认。
3. B1（首行缩进单位 bug）与 B4（seed 规则引用不存在的 `ruleset`）是否在本轮修 —— 二者都会直接影响"重新校验"与"新环境部署"，**建议本轮修**，但属 bugfix 需你点头。
4. 本地无法实跑引擎（PATH 上 Python 3.13 无 `python-docx`）；B1/B2/B3 为**源码判定**，建议在测试环境用一份真实公文档实跑确认后再动手。
