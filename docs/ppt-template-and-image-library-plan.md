# PPT 模板包与图库建设方案

> 需求来源：何总提出「加 PPT 模版和图库」。
> 范围确认：① 模板 = 真母版 .pptx 模板包（非只扩配色主题），**来源为用户自行采购**；② 图库 = 公共预置图库 + 现有个人素材库增强；③ 本文件只出方案，实施另行安排。
> 适用分支：`app`（FastAPI `server/` + Compose Desktop `desktop/`）。

---

## 0. 一句话结论

这两件事**都不是从零造轮子**：

- 模板：上传 .pptx → 学习版式 → 克隆填充的链路**已完整存在**（`render_pptx` 判定 `base_pptx + layout_library` 即走 `build_pptx_learned`），目前只缺「模板包本体」和「种子时把内置模板也走一遍学习」两步。
- 图库：个人素材库已存在（上传/匹配/配图），缺的是「公共池」这一层数据与入口，不涉及渲染器改造。

真正的工作量在**内容（设计好的 pptx）+ 数据模型 + 前端入口**，不在算法。

---

## 1. 现状核对（代码依据）

### 1.1 模板

| 事项 | 现状 | 代码位置 |
|---|---|---|
| 内置模板 | 7 套（政务汇报深蓝/红、政策解读、培训课件、经验交流、总结汇报、法治宣传），**仅换配色，共用同一套版式骨架** | `ppt_engine.py:47` `BUILTIN_TEMPLATES` |
| 内置模板落库 | 启动/手动调用 `seed_builtin_templates()` upsert，按 `builtin_id` 幂等 | `service.py:526` |
| 上传 .pptx 模板 | 支持，解析出版式库 `layout_library` + 预览图 | `service.py:623` `upload_template` |
| 模板学习 | `analyze_template()` 纯 python-pptx 解析，逐页产出 `element_schema / text_regions / image_regions / detected_type` | `ppt_engine.py:2295` |
| 学习模板校验 | 至少 1 页非封面类、且 ≥2 个可替换文本框 | `ppt_engine.py:2371` |
| 克隆填充渲染 | `build_pptx_learned()`：克隆模板源页 → 换内容 → 保留装饰 | `ppt_engine.py:2758` |
| 路由判定 | `render_pptx()`：有 `base_pptx` + `layout_library` → 学习渲染；否则基础排版 | `ppt_engine.py:2837` |
| 底稿来源 | `_tpl_base_bytes(trow)` 从模板行取源文件字节 | `service.py` |
| 官方模板底稿 | **没有**：7 套内置模板无源文件、无 `layout_library`，所以永远走基础排版 | `service.py:526-544` |
| `templates/gov/` | **只有 README，无任何 .pptx** | `server/app/application/ppt/templates/gov/` |

**关键结论**：把真母版 pptx 放进仓库、在种子时补上「保存源文件 + 学习版式」，官方模板就会自动改走克隆填充，**渲染器一行不用改**。

### 1.2 图库

| 事项 | 现状 | 代码位置 |
|---|---|---|
| 数据模型 | `ppt_materials`：`user_id` 非空、`name/caption/file_path/width/height/mime_type`；无分类、无标签、无公共域 | `models/ppt.py:41` |
| 上传/列表/删除 | 有，全部按 `user_id` 隔离 | `service.py:778-830` |
| 存储 | `ppt_dir/materials/<uuid>.<ext>` | `service.py:804` |
| 生成时配图 | `_user_images()` 取本用户素材 → `resolve_slide_images()` 按标题 2-gram 重合度 ≥0.55 自动配图，或按 `material_ids` 手动指定 | `service.py:838` / `ppt_engine.py:779` |
| 前端 | PPT 工作台已有素材选择面板（`PptScreen.kt` / `PptViewModel.kt`）；模板中心已有 `TemplatesScreen.kt` | `desktop/.../features/ppt`、`features/templates` |

**关键结论**：公共图库只需新增一张表 + 合并取图来源；自动配图算法可复用，但需加类别加权与阈值，否则图库变大后误配率会上升。

### 1.3 部署与环境约束（决定方案形态）

1. **生产内网严禁出网**：图库不可能在线搜图（Unsplash/必应等全部不可用），只能**离线预置图片包**；模板包同理，必须随源码/镜像进入。
2. **镜像非目录挂载**：`COPY server/ /app/`，模板包与图库包必须随镜像重建生效；素材图片若要放宿主机，需挂载卷（`ppt_dir` 已在数据卷上）。
3. **soffice / pdftoppm**：模板预览图依赖 LibreOffice；记忆中的结论是生产镜像尚未装 libreoffice/poppler。**方案用「构建期预生成预览图」规避**，不在服务器上跑 soffice。
4. **迁移编号**：当前最新 `020_writing_scoped_memory.py`，本方案新增迁移编号为 **021**。
5. **测试约定**：新增测试模块必须在 `conftest._SEED_USERNAMES` 增加一行（键=模块名），否则退化成 `seedadmin` → 401；涉及 PPT agent 的测试需 autouse fixture 置空 `PPT_AGENT_URL`，避免真连内网。
6. **页面尺寸**：自绘渲染假定 16:9（`Inches(13.333) × Inches(7.5)`）。模板包必须统一 16:9，否则克隆页与填充坐标错位。

---

## 2. 方案 A：真母版模板包

### 2.1 目标形态

在仓库内置 6~8 套**设计完整**的政务/普法主题 pptx（每套 8~12 页，**由用户自行采购**，按 2.3 规格下单、2.3.1 验收入库），用户选模板后按「克隆填充」出稿——保留原母版背景、装饰图形、配色、字体、版式结构，只替换文字与图片。与现有 7 套「换色主题」并存：换色主题 = 快速出稿，母版模板 = 高设计感。

### 2.2 改造点（后端）

1. **模板包落位**：`server/app/application/ppt/templates/gov/<builtin_id>.pptx`（替换现有仅 README 的目录，README 补规格说明）。
2. **规格扩展**：`BUILTIN_TEMPLATES` 每条增加两个字段：
   - `source_pptx`: 相对路径（无则保持现有换色行为，向后兼容）
   - `learn_layouts`: bool（默认 False，True 时种子阶段执行 `analyze_template`）
3. **种子逻辑扩展**（`service.py:526 seed_builtin_templates`）：
   - 若 `source_pptx` 存在：读字节 → `analyze_template()` → `validate_learned_template()` → 写 `layout_library`；源字节写入 `ppt_dir/tpl_src/<template_id>.pptx`（`_tpl_base_bytes` 依赖此文件）。
   - **幂等**：以源文件 `sha256` 作为 `source_sha` 判断，只有内容变化才重新学习；避免每次启动重复解析。
   - **失败降级**：学习失败 → 记 warning，保留 `layouts=DEFAULT_LAYOUTS`，该模板退化为换色主题（不阻断启动）。
   - 预览图：读取预置 PNG（见 2.4），不调用 soffice；缺失则回退结构示意图。
4. **数据模型**：`ppt_templates` 增加 `source_sha`（String(64)，可空）+ `is_learned`（Boolean，默认 False）。迁移 021 一并带上（与图库同批）。
5. **选择与展示**：`template_dto` 输出 `is_learned / layout_count / preview_url`，前端可标注「母版模板」。

### 2.3 采购规格（模板由用户自行采购，此节可直接发给卖家）

采购前必须把以下条款写进订单/验收标准，否则买回来的模板大概率"好看但机器用不了"：

**交付物**
1. **.pptx 源文件**（不是 PDF、不是图片拼版、不是 Keynote/WPS 专属格式），全部元素可编辑；
2. 每套附**逐页 PNG 预览**（60~80 dpi 即可），用于系统内模板预览——服务器不能装设计软件渲染；
3. 附**授权说明**：可商用、可私有化内网部署、可二次修改、生成份数不限；不接受"仅个人学习使用"授权。

**页面规格**
4. **统一 16:9**，13.333×7.5 英寸（或等效 1920×1080）。4:3、16:10 一律不收——系统按 16:9 固定坐标填充，会整体错位；
5. 每套 **8~12 页**，至少覆盖：封面、目录、章节页、正文要点（**≥2 种不同结构**）、图文页、数据/图表页、结束页；
6. **同一套内不要用同一骨架复制页**——系统按形状坐标签名去重，结构重复的页会被直接丢弃，等于白买；
7. 每页形状数控制在 **80 个以内**，避免上百个碎片/艺术字/多层蒙版（克隆填充会变慢且易错位）。

**文字硬要求（最容易踩坑，必须写进合同）**
8. 正文可以放在**组合（Group）**里——学习器已递归展开组合并按 chOff/chExt 换算坐标（见 `ppt_engine._iter_shapes`），组内文字照常替换；但**不要把整页所有元素塞进一个组合**，那会失去局部调整版式的能力，正文变长时容易挤压；
9. 禁止用图片承载正文，禁止用 SmartArt 装正文（python-pptx 无法写入其内部文字，该页会退化为基础排版）；
10. 每个内容页至少 **2 个可替换文本框**（标题 + 正文），纯图片页不算有效版式；
11. 示例图**不要每页重复同一张**——系统会把 ≥60% 页面重复出现的图判为固定装饰，出稿后每页都会带着它。

**字体**
12. 用微软雅黑 / 思源黑体 / 等线等常见中文字体；不要依赖需单独安装的商业字体（若必须，需同时提供字体授权与安装包）。

### 2.3.1 到货验收流程（工具已就绪）

仓库已提供体检工具 `deploy/check_ppt_template.py`，把买到的 pptx 丢进去即可判断能否入库：

```bash
python deploy/check_ppt_template.py 模板A.pptx 模板B.pptx --preview ./preview
```

- **PASS** → 直接入库；
- **WARN** → 能用，但需逐条人工确认（字体回退、重复示例图、纯图片页等）；
- **FAIL** → 退回卖家（会明确列出：4:3、页数不足、无可替换文本框、版式过少等原因）。

判定逻辑对应真实代码：`analyze_template`（版式提取/去重/固定元素识别）、`validate_learned_template`（至少一页可替换标题+正文）、`_iter_shapes`（递归展开组合并按子坐标系换算文字位置）、`_mark_fixed`（≥60% 页面重复判为装饰）。组合内文字不再是致命项：8 页全组合模板实测判 **WARN（可用）**；4:3 + 3 页 + 重复骨架的坏模板仍判 FAIL 并列出具体原因。

验收通过后：
1. pptx 放入 `server/app/application/ppt/templates/gov/<builtin_id>.pptx`；
2. 预览 PNG 放入 `templates/gov/preview/<builtin_id>/`（命名 `L0.png`、`L1.png`…，与源页序号一致）；
3. 在 `BUILTIN_TEMPLATES` 登记 `id / name / category / source_pptx`，跑种子生效。

> **采购建议**：商用模板一次通过率通常只有五到七成，建议按目标套数多买 2~3 套备选，避免验收不过导致工期卡住。

### 2.4 预览图策略（规避生产 soffice 依赖）

- 在**开发机**（已有 LibreOffice）批量生成：pptx → pdf → png（`pdftoppm -r 60`，复用 `_gen_tpl_previews` 的流程）；
- 生成物提交到 `templates/gov/preview/<builtin_id>/`，随镜像进入；
- 种子阶段只做「复制 + 写库」，零外部进程依赖 → 生产服务器不需要装 LibreOffice。若后续要给「用户上传模板」也出预览，再单独评估镜像装 soffice（约 +500MB）。

### 2.5 前端（桌面端）

- `TemplatesScreen`：卡片增加「母版」徽标；hover/详情展示各版式预览图（已有 `layout-preview` 接口）；
- 选择模板时提示「该模板将按原版式填充内容，文字过多可能触发降级」——出稿后若某页降级，`warnings` 会带说明，需要在该页给出可见提示。

### 2.6 验收标准

- 种子后 `ppt_templates` 中目标模板 `is_learned=true`、`layout_library` 页数 ≥ 8；
- 用同一份大纲分别套「换色主题」与「母版模板」出稿，后者**克隆填充命中率 ≥ 90%**（允许个别页因内容超量降级，且必须有 warning）；
- 导出 pptx 中装饰形状与母版背景保留、文字可编辑；
- 冷启动耗时增加 ≤ 2s（学习仅首次，且可用预计算 JSON 进一步降为 0）。

---

## 3. 方案 B：图库

### 3.1 目标形态

1. **公共图库**：预置一批政务场景图片（法治宣传、党建、办公、调解、普法活动等），所有用户可浏览、搜索、勾选用于 PPT；
2. **个人素材库增强**：分类、标签、批量上传、按使用频次排序；
3. 生成时自动配图可同时从「个人素材 + 公共图库」中挑选（个人优先）。

### 3.2 数据模型（迁移 021）

新建表 `ppt_library_images`（不动现有 `ppt_materials`，避免 `user_id NOT NULL` 改造风险）：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | String(36) PK | |
| name | String(200) | 展示名 |
| caption | String(500) | 说明（参与语义匹配） |
| category | String(50) | 分类（法治宣传/党建/办公/会议/调解/其他） |
| tags | JSON | 标签数组（参与匹配） |
| file_path | String(500) | 实际文件路径 |
| thumb_path | String(500) | 缩略图路径（PIL 生成，最长边 480px） |
| width / height / file_size / mime_type | — | 同现有素材表 |
| source | String(200) | 来源登记（自有拍摄/授权素材/内部生成） |
| license_note | String(300) | 授权说明（合规留痕） |
| enabled | Boolean | 上/下线开关 |
| sort_order | Integer | 排序权重 |
| created_at / updated_at | DateTime | |

同时对 `ppt_materials` 增加 `category`（String(50)，可空）、`tags`（JSON，可空）两列，用于个人素材库增强——均为可空新增列，风险低。

### 3.3 存储与种子

- 文件落 `ppt_dir/library/<category>/<uuid>.<ext>`，缩略图 `ppt_dir/library/thumbs/<uuid>.jpg`；
- 图片包与清单 `server/app/application/ppt/templates/library/manifest.json` 随仓库/镜像分发；种子命令按清单导入（幂等：按 `name + sha256` 去重）；
- 单图建议 ≤ 800KB、长边 ≤ 2400px（PPT 场景足够，控制包体积与内存）；
- 首批建议 60~120 张，按 6 个分类均衡。

> **状态（已实现，待灌图）**：目录、README、空 manifest 已就位；种子命令
> `python deploy/seed_ppt_library_images.py [--dry-run]` 已可用。幂等按 `name` 定位：
> 文件 sha256 与元数据都没变 → `[跳过]`；图片换了 → 覆盖文件并更新；`source` /
> `license_note` 缺失、坏图、路径越界 → 该条记 `[错误]`，不阻断整批。
> 图片文件存放走 `--ppt-dir`（默认 `settings.ppt_dir`），与上传接口共用 `library/` 目录。
> 待定：图片包来源与授权（§7.2），授权明确后把图片放进 `templates/library/<分类>/`
> 并在 manifest.json 登记即可。

### 3.4 API（`interfaces/ppt.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/ppt/library/images?category=&q=&page=&size=` | 公共图库列表（登录即可） |
| GET | `/ppt/library/categories` | 分类及数量 |
| GET | `/ppt/library/images/{id}/file` | 原图（带缓存头） |
| GET | `/ppt/library/images/{id}/thumb` | 缩略图 |
| POST | `/ppt/library/images` | 上传（仅管理员），带 category/tags/source/license_note |
| PATCH | `/ppt/library/images/{id}` | 改分类/标签/上下线（管理员） |
| DELETE | `/ppt/library/images/{id}` | 删除（管理员） |

权限复用现有管理员判定（管理员代建账号首次登录须改密的既有规则不变）。

### 3.5 生成链路改造

1. `_user_images()` 改为「个人素材 + 公共图库（enabled）」合并返回，字段结构保持一致（`id/name/caption/file_path`），**个人在前**；
2. `resolve_slide_images()` 匹配逻辑加固：
   - 匹配文本 = `caption + tags + category`（现在只有 caption+name）；
   - 阈值从单一 0.55 提高到「0.55 且命中 ≥2 个 2-gram」，并对「分类与页面主题同域」加权；
   - 已有的 `used_auto_ids` 去重保留，避免一份 PPT 反复用同一张图；
   - 公共图库命中数上限（如每份 PPT ≤ 4 张），防止整份全是库图显得廉价。
3. `material_ids` 手动选择需同时支持公共图库 id（前端传 `source` 前缀或统一 id 空间校验）。

### 3.6 版权与治理（政务场景必须）

- 每张图必须登记 `source` 与 `license_note`；无法说明来源的图**不得入库**；
- 禁止使用含可识别人脸、警徽/国徽使用不规范、涉密场所的图片；
- 提供 `enabled=false` 快速下线能力；
- 建议设立「图库管理员」角色，上传需二次确认授权说明。

### 3.7 前端（桌面端）

- `PptScreen` 素材面板增加 Tab：「我的素材 / 公共图库」；公共图库支持分类筛选、关键词搜索、缩略图网格、多选；
- 生成时若自动配了公共图库图片，在页面缩略图上标注来源，便于用户替换；
- 个人素材库增加分类/标签编辑与批量上传。

### 3.8 验收标准

- 公共图库列表/搜索/缩略图接口 P95 < 300ms（本地 PG，万级以内）；
- 同一主题大纲自动配图，公共图库命中的图片语义相关（人工抽检 20 份，误配 ≤ 1 张/份）；
- 公共图库图片可被任意普通用户使用，但仅管理员可增删改；
- 关闭某图（`enabled=false`）后，新生成不再引用，历史文档不受影响（已落盘 pptx 不回溯）。

---

## 4. 分期建议

| 阶段 | 内容 | 产出 | 依赖 |
|---|---|---|---|
| P1 | 模板包链路打通：1 套真母版 pptx + 种子扩展 + 预生成预览 | 选该模板可出克隆填充稿 | 需要 1 套设计好的 pptx |
| P2 | 模板包扩至 6~8 套 + 分类/徽标/预览完善 | 模板中心可见「母版模板」专区 | P1 |
| P3 | 图库后端：表 + 迁移 021 + API + 种子 + 生成链路合并 | 接口可用，生成能配公共图 | 需要首批图片包 + 授权说明 |
| P4 | 前端图库浏览/搜索/多选 + 个人素材分类标签 | 用户可用 | P3 |

P1 与 P3 无相互依赖，可并行；但两者共用迁移 021，建议合并为一次迁移发布，减少生产升级次数。

---

## 5. 风险清单

| # | 风险 | 影响 | 应对 |
|---|---|---|---|
| 1 | 采购模板质量不达标（页型不足、4:3、整页单一组合） | 学习器拒收或出稿退化，钱白花 | `deploy/check_ppt_template.py` 到货即检；FAIL 直接退；多买 2~3 套备选（见 2.3.1） |
| 2 | 克隆填充遇到超量文字丢内容 | 用户看到缺段 | 已有降级告警；前端必须展示 warning 并提供「改用自由排版」按钮 |
| 3 | 生产镜像无 soffice | 预览图空白 | 预生成 PNG 随包分发（2.4），不依赖运行时 |
| 4 | 图片包体积膨胀 | 镜像变大、构建变慢 | 单图 ≤800KB、首批 ≤120 张；后续图片放数据卷而非镜像 |
| 5 | 公共图库自动匹配误配 | 出稿图文不符 | 提高阈值 + 分类加权 + 每份上限 + 前端标注来源 |
| 6 | 版权/合规 | 政务场景风险高 | 来源与授权必填、管理员审核、可快速下线 |
| 7 | 迁移 021 与既有 schema 漂移 | 升级失败 | 迁移仅新增表 + 可空列；上线前在副本库演练；沿用既有 alembic 流程 |
| 8 | 模板分类误判 | 版式映射错页型 | `LEARNED_FALLBACK` 已兜底；抽样验证 detected_type 准确率 |
| 9 | 内置模板种子重复学习拖慢启动 | 冷启动变慢 | 以 `source_sha` 幂等；必要时预计算 `layout_library` JSON 提交 |
| 10 | 新测试模块漏配 `_SEED_USERNAMES` | 测试 401 假失败 | 按项目约定新增模块必须加行；PPT 测试置空 `PPT_AGENT_URL` |

---

## 6. 改动文件清单（预估）

**后端**
- `server/app/application/ppt/ppt_engine.py`：`BUILTIN_TEMPLATES` 增字段；`resolve_slide_images` 匹配加固
- `server/app/application/ppt/service.py`：`seed_builtin_templates` 扩展（源文件入库/学习/幂等）；`_user_images` 合并公共图库；新增图库服务方法
- `server/app/application/ppt/library_service.py`（新增）：图库 CRUD/种子/缩略图
- `server/app/domain/ppt/`（或 repositories）：`PPTLibraryImage` 实体 + 仓储
- `server/app/infrastructure/database/models/ppt.py`：新表模型 + `ppt_templates` 两列 + `ppt_materials` 两列
- `server/app/migrations/versions/021_ppt_template_learned_and_library.py`（新增）
- `server/app/interfaces/ppt.py`：图库路由（注意具名端点必须注册在 `/{id}` 之前）
- `server/app/application/ppt/templates/gov/*.pptx` + `preview/`；`templates/library/manifest.json`（新增）
- `deploy/check_ppt_template.py`（**已完成**）：模板采购体检工具，判 PASS/WARN/FAIL 并给出具体原因

**前端**
- `desktop/.../features/templates/TemplatesScreen.kt`、`TemplatesRepository.kt`：母版徽标 + 预览
- `desktop/.../features/ppt/PptScreen.kt`、`PptViewModel.kt`：素材面板 Tab/搜索/多选
- `desktop/.../core/network/Endpoints.kt`：图库接口

**测试（新增模块须在 conftest `_SEED_USERNAMES` 加行）**
- `test_ppt_template_seed.py`：种子幂等、学习失败降级、source_sha 变化重学
- `test_ppt_learned_render.py`：母版模板克隆填充命中率与降级告警
- `test_ppt_library.py`：列表/搜索/权限/上下线/生成链路合并

---

## 7. 待拍板事项

1. ~~模板包来源~~ → **已定：用户自行采购**。采购时按 2.3 条款下单，到货用 2.3.1 工具验收；需确认预算能覆盖「多买 2~3 套备选」。
2. **图片包来源与授权**：自有拍摄 / 采购图库授权 / 内部生成，需能出具授权说明（政务场景硬要求）。**这一项未定，P3 无法启动。**
3. **首批规模**：模板 6 套还是 8 套；图片 60 张还是 120 张——直接决定 P1/P3 的启动时间。
