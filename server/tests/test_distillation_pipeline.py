import json
from pathlib import Path

from scripts.prepare_distillation_dataset import (
    load_rows,
    select_fewshot,
    split_rows,
    validate_row,
)


def _row(i=1, doc_type="通知", output=None):
    body = output or (
        f"关于第{i}项工作的通知\n\n各有关单位：\n"
        "为进一步规范工作流程，提升协同办理质量，现将有关事项通知如下。\n\n"
        "一、提高认识。各单位要结合职责实际细化责任分工，明确办理标准、责任人员和完成时限，"
        "对重点环节实行清单化管理，确保任务要求传达到岗、落实到人。\n"
        "二、抓好落实。建立工作台账和定期调度机制，及时协调解决推进中的具体问题，"
        "对跨部门事项主动衔接、闭环办理，确保各项任务有序推进、有效衔接。\n"
        "三、强化监督。定期梳理进展情况，对发现的问题逐项分析原因、明确整改措施，"
        "并跟踪整改结果，形成发现问题、整改落实、复盘提升的工作闭环。\n\n"
        "请各单位认真组织实施，加强过程沟通，并按要求及时报送阶段性进展和有关情况。"
    )
    return {
        "instruction": f"起草第{i}项工作通知",
        "input": "",
        "output": body,
        "document_type": doc_type,
        "source_model": "external-strong-model",
        "source_id": f"src-{i}",
    }


def test_validate_rejects_placeholder_and_requires_provenance():
    ok, reason, _ = validate_row(_row(output="待补充" * 100))
    assert not ok and reason == "placeholder"
    row = _row()
    row["source_model"] = ""
    ok, reason, _ = validate_row(row)
    assert not ok and reason == "missing_source_model"


def test_exact_output_deduplication(tmp_path: Path):
    source = tmp_path / "external.jsonl"
    row = _row()
    source.write_text(
        json.dumps(row, ensure_ascii=False) + "\n" + json.dumps(row, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    accepted, rejected = load_rows(source)
    assert len(accepted) == 1
    assert rejected["duplicate_output"] == 1


def test_split_is_deterministic_and_fewshot_is_bounded_per_type():
    rows = []
    for i in range(20):
        row = _row(i=i + 1)
        row["output"] += f"\n本通知第{i + 1}项任务由相关责任单位结合实际组织落实。"
        ok, _, normalized = validate_row(row)
        assert ok
        rows.append(normalized)
    train1, val1 = split_rows(rows)
    train2, val2 = split_rows(list(reversed(rows)))
    assert {r["sample_id"] for r in train1} == {r["sample_id"] for r in train2}
    assert {r["sample_id"] for r in val1} == {r["sample_id"] for r in val2}
    fewshot = select_fewshot(rows)
    assert len([r for r in fewshot if r["document_type"] == "通知"]) <= 8
