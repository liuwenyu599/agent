#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把审核通过的样本导出成可直接训练的 JSONL。

产出形态是「去掉风格卡」的完整对话：

    system     = 当时那份 system（含检索资料），**不含** 1100 字风格卡
    user       = 当时的起草指令
    assistant  = 用户认可的那版正文

这就是把推理期的 few-shot 蒸馏进权重（context distillation）的标准做法：
训练时给「撤了卡」的输入，配「有卡时才写得出」的输出，让权重自己去补这张卡。
等 LoRA 学会了，线上那张卡就可以摘掉。

用法：
  python training/scripts/export_accepted_samples.py \
      --database-url sqlite:///server/data/judicial_app.db \
      --snapshot-dir training/data/snapshots \
      --status approved

  # 导出后直接切分进 training/data/processed
  python training/scripts/export_accepted_samples.py ... --prepare
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "server"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出审核通过的 SFT 样本")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--snapshot-dir", default=os.getenv("SFT_SNAPSHOT_DIR", ""))
    parser.add_argument("--status", default="approved",
                        choices=["approved", "candidate", "all"],
                        help="默认只导出 approved：自动抓取的样本必须过人工复核")
    parser.add_argument("--data-dir", default=str(_REPO_ROOT / "training" / "data"))
    parser.add_argument("--prepare", action="store_true",
                        help="导出后随即调用 prepare_dataset 切分出 processed/train|val")
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def load_samples(database_url: str, statuses: List[str]) -> List[Dict[str, Any]]:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app.infrastructure.database.models.training import TrainingSampleModel

    engine = create_engine(database_url, future=True)
    rows: List[Dict[str, Any]] = []
    with Session(engine) as db:
        stmt = select(TrainingSampleModel)
        if statuses:
            stmt = stmt.where(TrainingSampleModel.status.in_(statuses))
        for row in db.scalars(stmt).all():
            rows.append({
                "id": row.id,
                "instruction": row.instruction or "",
                "input": row.input or "",
                "output": row.output or "",
                "draft": row.draft or "",
                "biz_type": row.biz_type or "",
                "session_id": row.session_id or "",
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else "",
            })
    return rows


def index_snapshots(snapshot_dir: str) -> Dict[str, List[Dict[str, Any]]]:
    """按 session_id 汇总所有快照，每条保留时间戳以备按时间配对。

    一个会话里可能起草多次、改写多次，快照文件里就有多行。样本配哪个，
    取决于它是什么时候产生的——见 pick_snapshot。
    """
    root = Path(snapshot_dir) / "ctx"
    if not root.exists():
        return {}
    index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for path in root.glob("*.jsonl"):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                snap = json.loads(line)
                key = snap.get("session_id") or snap.get("task_id") or ""
                if key:
                    index[key].append(snap)
        except Exception:
            continue
    for snaps in index.values():
        snaps.sort(key=lambda s: s.get("ts") or "")
    return index


def pick_snapshot(snaps: List[Dict[str, Any]], created_at: str) -> Optional[Dict[str, Any]]:
    """取样本产生那一刻之前、离它最近的一次模型调用上下文。

    一次会话可能先起草、再改写两轮，用户最后认可的是第二轮之后的版本。
    随便取首版或末版都会错配：时间序列上市忖的那次才是真正产出它的那次。
    """
    if not snaps:
        return None
    if created_at:
        earlier = [s for s in snaps if (s.get("ts") or "") <= created_at]
        if earlier:
            return earlier[-1]
        return None
    return snaps[-1]


def ensure_intermediate_dir(data_dir: Path) -> Path:
    """挑一个能写的中间目录。

    ``training/data/raw`` 在仓库里是一个断链符号链接（指向训练机上才有的数据目录），
    Windows 上 os.path.isdir 为 False，mkdir 即便 exist_ok=True 也会抛
    FileExistsError——pathlib 会把已存在但不是目录的路径重新抛出。所以这里
    逐个候选往下退，总能找到一个真正可写的。
    """
    candidates = [data_dir / "raw", data_dir / "collected"]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    fallback = data_dir / "collected"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def main() -> int:
    args = parse_args()
    if not args.database_url:
        print("[export] 缺少 --database-url 或 DATABASE_URL", file=sys.stderr)
        return 2
    if not args.snapshot_dir:
        print("[export] 未配置 --snapshot-dir：样本将拿不到输入侧，\n"
              "        这类样本训练等于教模型凭空编事实，脚本会全部丢弃。",
              file=sys.stderr)

    statuses = [] if args.status == "all" else [args.status]
    samples = load_samples(args.database_url, statuses)
    print(f"[export] 读到样本: {len(samples)} (status={args.status})")

    from app.application.shared.writing_assistant import WritingAssistant
    from app.application.writing import prompt_snapshot

    if args.snapshot_dir:
        os.environ["SFT_SNAPSHOT_DIR"] = args.snapshot_dir
    # 只借用它的字符串拼装逻辑，发请求的能力一个都没用
    assistant = WritingAssistant(None)
    index = index_snapshots(args.snapshot_dir) if args.snapshot_dir else {}

    records: List[Dict[str, Any]] = []
    missing = 0
    for sample in samples:
        snap = pick_snapshot(index.get(sample["session_id"]) or [],
                             sample["created_at"])
        if not snap:
            snap = prompt_snapshot.latest(sample["session_id"])
        inputs = prompt_snapshot.build_inputs(snap, assistant, keep_style_card=False) if snap else {}
        if not inputs or not inputs.get("user"):
            missing += 1
            # 宁可丢，也不造：没有输入侧的样本就是「给个标题写出一篇」的样板
            continue
        records.append({
            "messages": [
                {"role": "system", "content": inputs["system"]},
                {"role": "user", "content": inputs["user"]},
                {"role": "assistant", "content": sample["output"]},
            ],
            "_sample_id": sample["id"],
            "_biz_type": sample["biz_type"],
            "_had_style_card": bool(snap.get("style_card")),
        })

    print(f"[export] 可训练样本: {len(records)}，缺输入侧丢弃: {missing}")

    data_dir = Path(args.data_dir)
    raw_dir = ensure_intermediate_dir(data_dir)
    out_path = raw_dir / "accepted.jsonl"
    with out_path.open("w", encoding="utf-8") as fh:
        for item in records:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"[export] 已写出: {out_path}")

    if args.prepare:
        return run_prepare(out_path, data_dir, args.val_ratio, args.seed)
    return 0


def run_prepare(out_path: Path, data_dir: Path, val_ratio: float, seed: int) -> int:
    sys.path.insert(0, str(_REPO_ROOT / "training" / "scripts"))
    import prepare_dataset

    argv = ["prepare_dataset", "--input", str(out_path),
            "--output-dir", str(data_dir / "processed"),
            "--val-ratio", str(val_ratio), "--seed", str(seed)]
    old_argv = sys.argv
    sys.argv = argv
    try:
        return prepare_dataset.main()
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    sys.exit(main())
