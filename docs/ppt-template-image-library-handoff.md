# PPT 模板与图库：交接说明

> 需求来源：何总提出「加 PPT 模版和图库」。
> 本文是**交接用现状总结**，不是新方案：写清哪些已经能用、缺口在哪、改哪里、怎么验收。长篇方案见 `docs/ppt-template-and-image-library-plan.md`。
> 代码位置以 `server/app/application/ppt/` 为准，行号可能随改动漂移，按函数名检索。

---

## 0 一句话结论

- **模板**：真母版的「上传 → 学版式 → 克隆填充」链路**已经端到端存在且可用**，缺的只是**母版 pptx 本体**和 **seed 时补两步**（存底版字节、写 `layout_library`）。渲染器一行都不用改。
- **图库**：只有「每用户私有素材库」，**没有公共图库**。需要新表 + 迁移 + 配图来源合并，**不能**拿 `ppt_materials` 改约束凑。
- **组合形状**：本轮已支持递归解析，采购模板不再需要排除「正文在组合里」的模板。

---

## 1 现状盘点（已核对代码）

### 1.1 模板

| 能力 | 现状 | 落点 |
|---|---|---|
| 内置主题 | **7 套**，只有 `colors` + `layouts`（渲染样式名，如 `bar_title`），**共用同一套版式骨架**，仅换配色 | `ppt_engine.py` 的 `BUILTIN_TEMPLATES` |
| 官方模板入库 | `seed_builtin_templates()` 只 upsert `name/category/description/colors/layouts`，**从不写 `source_file`、从不写 `layout_library`** | `service.py::seed_builtin_templates` |
| 上传模板（真母版） | 链路完整：校验 → `analyze_template` → `validate_learned_template` → `_save_tpl_source` → `_gen_tpl_previews` → `layout_library` 落库 | `service.py::upload_template` |
| 出稿选路 | 有 `base_pptx` + `layout_library` → `build_pptx_learned`（克隆模板页、保留背景/装饰、只换文字）；否则 → `build_pptx` 自由生成 | `ppt_engine.py::render_pptx` |
| 底版存储 | **磁盘**：`ppt_dir/tpl_src/<template_id>.pptx`；DB 只存 `layout_library` 与 `source_file`（文件名） | `service.py::_tpl_source_path / _save_tpl_source / _tpl_base_bytes` |
| 母版素材 | `ppt/templates/gov/` 只有 `README.md`，**没有任何母版 pptx** | 同目录 |
| DB 列 | `ppt_templates` 已有 `source_file`、`layout_library`（JSON），**无需为新功能加列** | `infrastructure/database/models/ppt.py` |

> 关键含义：**底版字节是文件不是 DB blob**。内置模板 seed 之后必须把字节落盘到 `tpl_src/`，否则换机/清数据卷后 `_tpl_base_bytes` 读不到，出稿会静默退回自由排版。

### 1.2 图库

| 能力 | 现状 | 落点 |
|---|---|---|
| 个人素材库 | 有：上传、分析、改、删、取文件；`ppt_materials.user_id NOT NULL` | `interfaces/ppt.py` 的 `/ppt/materials*`；`service.py::list_materials / _user_images` |
| 配图来源 | 只用「当前用户的素材」，按标题语义匹配 | `service.py::_user_images` |
| 公共图库 | **不存在**：无表、无分类、无搜索、无授权登记 | — |

---

## 2 本轮已完成（勿重复做）

1. **组合形状递归解析**（`ppt_engine.py`）
   - 新增 `_iter_shapes()`：DFS 展开组合，按 `chOff/chExt` 把子坐标系换算回页面坐标；嵌套组合逐层累加缩放；缺子坐标系时 1:1 兜底。
   - `_element_of(shape, sw, sh, rect, depth)`：改收页面坐标，组内元素打 `in_group` 标记。
   - `_fill_learned_slide()`：递归收集/替换组内文字、图片、图表；替换图片与图表改用页面坐标。
   - `_delete_shape(shape, prune=True)` + `_prune_empty_group()`：组内元素被删空后移除空 `grpSp`，避免 PowerPoint 报修复。
   - 回归：`server/tests/test_ppt_group_template.py`（5 项，覆盖坐标换算、嵌套缩放、validate、出稿无残留、重复标题仍为 content）。
2. **修正固定元素误判**（`ppt_engine.py::_mark_fixed`）
   - 原逻辑把「每页重复的短文本」判成装饰，模板里反复出现的示例标题/正文会被判 fixed → 示例文字永久残留 + `validate_learned_template` 必然失败。
   - 现在只有「非页内最大字号 且 ≤14pt」的短文本才按重复判装饰（页脚/页码/落款），标题与正文恒为内容槽。
3. **模板采购体检工具** `deploy/check_ppt_template.py`（PASS/WARN/FAIL），组合项已从「一票否决」降为分级提示（组内文字→WARN、嵌套≥3 层→提示、整页单一组合→提示）。
4. **采购规格改写**：`docs/ppt-template-and-image-library-plan.md` 第 2.3 节第 8 条，不再要求「正文必须是独立文本框」。

实测基线：8 页「全部正文在组合里」的模板判 **WARN（可用）**；原 12 个本地 PPT 测试文件 **249 passed / 6 skipped** 无回归。

---

## 3 待做

### P1 母版模板接入（代码量最小，等 pptx 到货）

**落点**

1. 放料：`server/app/application/ppt/templates/gov/<builtin_id>.pptx`；预览 `templates/gov/preview/<builtin_id>/L0.png、L1.png…`（与源页序号一致）。
2. 改 `service.py::seed_builtin_templates`：
   - 每个 `spec` 若存在 `templates/gov/<id>.pptx` → 读字节 → `ppt_engine.analyze_template(bytes)` → `validate_learned_template` → **先 `add/update` 拿到行，再 `_save_tpl_source(t.id, data)`** → `t.layout_library = learned["layouts"]` → 回写 `source_file`。
   - 解析/校验失败**只 `logger.warning`，不阻断启动**（否则一个坏模板能让服务起不来）。
   - 内置模板 `created_by` 为空、`is_official=True`，确保权限判断走「官方可见」分支。
3. 预览图：优先读随包预生成的 PNG（放 `templates/gov/preview/<builtin_id>/L0.png…`），**seed 时复制到 `ppt_dir/tpl_prev/<template_id>/`**，或改 `_layout_preview_path` 增加「包内资源」回退查找；**不要依赖运行时 soffice**（生产镜像是否装了 LibreOffice 未确认，`_gen_tpl_previews` 失败会静默回退结构示意图）。
4. 前端：模板卡片要能区分「设计母版」与「换色主题」，并显示预览图；模板编辑器沿用已有的页型→版式绑定（`preferred_layout_id`）。
5. **迁移：先确认再决定**。`ppt_templates` 现有列已够用，**大概率不需要 021**；只有确实要加字段（如 `design_tier`、`preview_asset`）才写。

**验收**

- `psql` 查 `ppt_templates` 里官方行的 `layout_library` 非空、`source_file` 非空；
- 容器内 `ppt_dir/tpl_src/<id>.pptx` 存在；
- 选该模板出稿，成品背景/装饰保留、文字被替换、无「点击输入…」残留；
- 出稿走的是 `build_pptx_learned`（可加一行 INFO 日志确认）。

### P2 公共图库后端

**落点**

1. 新表 `ppt_library_images`（**不要给 `ppt_materials` 加可空 `user_id`**，现有查询全按 `user_id` 过滤，改约束风险大）：
   `id / name / category / caption / file_path / thumb_path / width / height / mime_type / source / license / is_active / sort / created_at`
2. 迁移 **021**（当前最新是 `020_writing_scoped_memory.py`）。
3. 服务层：公共图库列表（分类+关键词+分页）、管理员上传/下线、文件与缩略图读取；`source`、`license` **必填**，缺授权不允许 `is_active=1`（政务场景硬要求）。
4. 配图来源合并：`service.py::_user_images` 末尾 append 公共图库行（带 `source="library"` 标识），匹配算法复用现有逻辑，不重写。
5. 出稿时保持「用户显式选的图优先，公共图库只做补充」，避免误配。

**验收**：同一主题出稿能命中公共图库图片；删除/下线后不再命中；未填授权的图无法上架。

### P3 前端（桌面端 Compose）

- 图库页：分类筛选、关键词搜索、缩略图预览、选择插入；
- 模板页：母版标记 + 预览图；
- 出稿流程：选图入口 + 来源标注。
- 参照现有 `KnowledgeScreen`/`KnowledgeViewModel` 结构，保持 Pages/Components/ViewModel 分层。

### P4 素材包

- 首批 60~120 张政务场景图（分类：法治宣传/党建/办公/会议/调解/其他），单图 ≤800KB，附 `manifest.json`（名称/分类/来源/授权）。
- 生产不能出网，**只能离线包**，随镜像或数据卷分发。

---

## 4 硬约束（违反会白干）

| 约束 | 说明 |
|---|---|
| 生产内网禁出网 | 图库不可能在线搜图；禁止设计任何运行时外网拉图逻辑 |
| 镜像 `COPY server/` | 改宿主机文件 + restart **不生效**，必须 rebuild 镜像 + `up -d` |
| 空气闸构建 | 新增 pip 依赖要在出网机 build→save→scp→load，或预缓存；不要指望构建期联网 |
| `deploy_latest.sh` | 靠 sed 匹配 `image: justice-office-server:<tag>` 字面量；改成 `${SERVER_IMAGE}` 模板会失效 |
| 迁移 | 在 `server/` 下执行 alembic；当前最新 `020`，新迁移用 `021` |
| 测试补充 | 新测试模块若走鉴权 client，须在 `tests/conftest.py::_SEED_USERNAMES` 加一行，否则退 `seedadmin` → 401 |
| 行尾/Python | `.py` 必须 LF（`.gitattributes` 要求）；用 `D:\apps\anaconda3\python.exe`（3.11） |
| 数据卷 | `ppt_dir/tpl_src`、`tpl_prev` 在数据卷；清卷后必须重跑 seed 才会重新落底版 |

测试命令：

```bash
cd server && CODEBUDDY_SAFE_DELETE_ENABLED=0 D:/apps/anaconda3/python.exe -m pytest \
  tests/test_ppt_group_template.py tests/test_ppt_layouts.py tests/test_ppt_template_tokens.py \
  tests/test_ppt_workbench.py tests/test_ppt_free_structure.py tests/test_ppt_local_job.py -q
```

---

## 5 明确不要做（已踩过）

1. **不要**把「正文必须放顶层」写回采购规格——组合已支持递归解析，这条会白白筛掉可用模板。
2. **不要**给 `ppt_materials` 加可空 `user_id` 当公共图库——`list_by_user` 等查询全部假设非空。
3. **不要**放宽 `drawio_native.validate_generated_layout` 的重叠/越界阈值——那是 PPT 图示那条线的问题，与模板/图库无关。
4. **不要**用 PDF、图片拼版、纯图片页当模板；**不要**用 SmartArt 承载正文（python-pptx 写不进内部文字）。
5. **不要**把「内置主题扩到 20 套（仅换配色）」当成满足需求——那正是当前被吐槽「还是模板化」的原因：骨架在换，视觉语言只有一套。
6. **不要**依赖运行时 `soffice` 生成预览——生产镜像未确认装了 LibreOffice/poppler/中文字体。

---

## 6 未决事项（业务侧，不定就开不了工）

1. **模板 pptx 来源**：用户已确认自行采购。到货必须先跑 `python deploy/check_ppt_template.py 模板.pptx`，**PASS/WARN 才入库，FAIL 直接退**；建议按目标 6 套买 8~9 套备选。
2. **图片授权**：政务场景要求严格（无可识别人像、无未授权商标、涉地图需审图号、可商用可内网部署）。图源不定，P2 只能建空库。
3. **首批规模**：模板 6 套 / 图片 60 张，还是 8 套 / 120 张——直接决定 P4 工作量与镜像体积。

---

## 7 快速自检清单（交付前）

- [ ] `python deploy/check_ppt_template.py <模板>.pptx` 结论为 PASS/WARN
- [ ] 官方模板行 `layout_library` 非空、`source_file` 非空、`tpl_src/<id>.pptx` 存在
- [ ] 选母版模板出稿：背景/装饰保留，文字全替换，无示例文字残留
- [ ] 清空 `tpl_src/` 后重启，seed 能自动重建底版
- [ ] 公共图库：分类/搜索可用，未授权图片无法上架，下线后不再命中
- [ ] 上述测试命令全绿
