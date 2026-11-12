# 清单项②：工作流数据同步 —— 核验结论与修复记录

> 对应 `AI_REVIEW_BRIEF.md` §2.2 / §6-2。核验方式：直接读 `server/app/application/workflow/service.py`
> 当前 HEAD（`28a429a` 之后又改了兜底块，见下），逐条对照审查 AI 的结论并独立确认。
> 与 `LAYOUT_SELECTOR_VERIFICATION.md` 同一交付标准：**已读码 + 可复现**。

## 一、背景
双存储：`WorkflowInstance.basic_info`（权威数据源）+ `NodeInstance.content`（节点正文）。
桌面端 `WorkflowRepository.kt` 的 `createInstance` 传空 `workflow_context`，`updateNode` 只写
`ni.content`、不写 `basic_info` → 服务端 `generate_node` 拿不到「基础信息」，下游节点生成缺上下文。
`9e56971` 在服务端加了 `_get_basic_info_node_content` 兜底。

## 二、已确认的事实（逐条读码）
| # | 审查结论 | 代码位置（当前） | 是否属实 |
|---|---|---|---|
| 1 | `update_node` 现已在「基础信息」节点同步写 `basic_info`（根治项，见 §三-4）；此前确为仅写 `ni.content` | `service.py:412-430` | ✅ 历史属实，已根治 |
| 2 | 兜底触发仅 `basic_info` 全空（`ctx_text == "（未填写）"`） | `generate_node` 内 `443-449` | ✅ 属实 |
| 3 | 原 `not ctx_text` 是死条件（`_build_context_text` 至少返回非空串） | `_build_context_text:554` | ✅ 属实（已删除死分支） |
| 4 | `_get_basic_info_node_content` 按 `"基础信息" in nd.name` 子串匹配、取首个有正文节点 | `566-579` | ✅ 属实 |
| 5 | `_get_upstream_contents` 显式跳过「基础信息」节点（同一套子串匹配） | `582-617`，跳过点 `588/600` | ✅ 属实 |
| 6 | 上游正文截 2000/1500，但兜底基础信息**原样注入**（不对称） | 上游 `592/602` vs 兜底 `448` | ✅ 属实（已修） |
| 7 | `_instance_to_dict` 回读 `workflow_context/basic_info = inst.basic_info` → 长期为空时桌面端回显丢失 | `632` 起 | ✅ 属实（须桌面端根治） |

## 三、本轮已修复（低风险，回归测试通过）
1. **边界①（中）**：兜底基础信息截断到 `fallback[:2000]`，与上游对齐，避免长粘贴撑爆
   `max_tokens=3000` 的输出预算（`service.py:448`）。
2. **边界④（低）**：兜底段在 prompt 内加注
   `（回退自「基础信息」节点原文，自由文本，请提炼规范公文表述）`，修正
   「唯一权威数据源」措辞与自由文本实际形态不符（`service.py:467-471` + 注入点）。
3. **附带清理**：删除 `not ctx_text` 死分支（`_build_context_text` 永返回非空串）。
4. **桌面端根治（方案 B，后端 `update_node` 同步写，改一处更省）**：
   编辑「基础信息」类型节点时，`update_node` 现在把自由文本解析为结构化 `basic_info` 写回实例
   （`service.py:425-430` + 新增 `_parse_basic_info_text:438-457`），修复实例列表/详情回显丢失
   （`_instance_to_dict` 读 `inst.basic_info`），并让 `generate_node` 不再依赖节点正文回退。
   解析仅支持「标签：值 / 标签: 值」行；解析不出任何字段时不覆盖（回退仍生效）。
   取数用 `self._get_instance_checked(...)` + `self.instances.update(inst)`，与 `confirm_context` 同模式
   （曾误用 `self.instances.get()` 导致会话外对象不落库，已修正）。

回归测试：
- `cd server && CODEBUDDY_SAFE_DELETE_ENABLED=0 D:/apps/anaconda3/python.exe -m pytest -q "tests/test_workflow_contract.py::test_generate_node_falls_back_to_basic_info_node_content"` → **1 passed**（兜底仍有效）。
- `tests/test_workflow_contract.py::test_update_node_on_basic_info_node_syncs_basic_info` → **1 passed**（根治：编辑基础信息节点后实例 `workflow_context/basic_info` 被填充；反例验证非基础信息节点不触发同步）。
- 全文 `tests/test_workflow_contract.py` → **28 passed**（含上述两条）。

## 四、仍待决策 / 待根治（未改，明确标注为产品决策）
- **边界②（中）部分填写不回退**：本根治采用「基础信息节点即权威源、整段覆盖」语义，已规避「半空 basic_info 压制更全正文」
  的问题（因为节点正文现在直接成为 basic_info，不再有「basic_info 半空」的中间态）。但若未来桌面端改为**结构化字段**
  直传 `workflow_context`、与节点正文并存，则需重新评估叠加策略 —— 届时再定。
- **边界③（低）子串匹配脆弱**：`update_node` 与 `_get_basic_info_node_content` / `_get_upstream_contents` 仍共用
  `"基础信息" in nd.name` 子串匹配。根治项未改此匹配（保持一致即可工作）；建议后续用节点 `stage` 或显式类型标识替代。

## 五、给下一个 AI 的提示
- 不要依赖审查稿里的旧行号（`553/569/588/623`），本文件 §二 给的是当前真实行号。
- 桌面端根治已通过后端 `update_node` 完成，**桌面端 `WorkflowRepository.kt` 无需改动**即可获得回显修复
  （basic_info 由后端在 saveNode 时同步）。若仍要桌面端直传结构化 `workflow_context`，属增强而非必修。
