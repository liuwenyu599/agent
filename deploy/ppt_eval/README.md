# 固定十页 PPT 评测

输入材料为 `fixed_10p.json`，其文字与数字取自仓库既有的 `deploy/samples/probe_outline_11p.json`。评测时两组使用相同模板、画幅、图片素材、模型参数和页面数；照片须来自已授权的公共图库，不生成或替换事实照片。保存两份 PPTX 和每页 PNG 后，由组织者随机命名为 A/B，记录映射但不交给评审。

在演示环境导入模板后，管理员调用一次 `POST /api/v1/ppt/templates/{template_id}/refresh-preview`。随后在同一环境运行 `python deploy/ppt_eval/check_previews.py <template_id> --db <数据库路径> --ppt-dir /data/justice/ppt`；只有 `ready=true` 才开始模型构图评测。此检查同时核对 `tpl_prev/<模板id>/<版式id>.png` 和数据库正文页的 `preview`/`source_preview`。若演示全程选用强制模板保底，不进行模型构图，可跳过此步骤。

两名以上评审独立观看 A/B 的逐页 PNG，先逐页评分，再看整稿。每页五项均按 1–5 分：

| 维度 | 1 分 | 5 分 |
| --- | --- | --- |
| clarity | 十秒内找不到重点 | 十秒内能说出本页结论 |
| hierarchy | 标题、数据、解释主次混乱 | 视觉权重与信息主次一致 |
| visual_fit | 图形仅作装饰或误导关系 | 图形准确表达对比、过程或证据 |
| factual_fidelity | 遗漏、改写或伪造事实 | 材料事实完整且准确 |
| rhythm | 与相邻页机械重复或突兀 | 整稿统一且有合理疏密变化 |

有照片的页另评 `image_relevance`（1=画面与文字无关，5=直接支持本页叙述）；无照片填 `null`。数据页的原生可编辑性、字号溢出和图表数值应单独记录缺陷，不用审美分数掩盖。评审不看生成器名称、构图诊断或对方分数。

运行 `python deploy/ppt_eval/score.py A.pptx --ratings A.ratings.json --out A.metrics.json`。评分文件格式为 `{"judges":[{"pages":[{"clarity":1,"hierarchy":1,"visual_fit":1,"factual_fidelity":1,"rhythm":1,"image_relevance":null}, ... 共10页]} , ... 至少两人]}`。脚本给出页均视觉元素数、字号标准差、图文占比波动和人工图片相关性；缺照片时相关性为 `null`，不会伪造零分。比较时同时报告逐页分数、评审人数、模型构图接受率和退回原因，避免只看平均值。

图文占比只统计导出器标记为 `PPTEvidencePhoto` 的证据照片，模板底图和 SVG 装饰不算照片。评测旧版 PPTX 时需先确认照片有这一标记，否则报告的 `photo_pages=0` 不能解释为实际无图。
