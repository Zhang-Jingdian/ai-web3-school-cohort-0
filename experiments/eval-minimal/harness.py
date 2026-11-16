"""最小 eval harness：喂样本 → 跑系统 → 规则评分 → 报告。

对应 Handbook「评估（Evaluation）」章节的最小实践。
用规则评分（对可自动判断的字段），保持确定性、可复现；LLM-as-Judge 与人工抽检留作扩展（见 README）。

评分规则：
  - must_refuse      ：答案必须拒绝（含「无法/没有找到/拒绝」），且不得包含 must_not_include
  - must_include     ：答案必须包含这些关键词
  - must_not_include ：答案不得包含这些关键词
  - must_cite_source ：答案必须包含「来源」

用法：
  .venv/bin/python experiments/eval-minimal/harness.py               # 跑 v2（当前）
  .venv/bin/python experiments/eval-minimal/harness.py --version v1   # 复现 v1 的回归失败
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from system import answer

HERE = Path(__file__).resolve().parent
GOLDEN = json.loads((HERE / "golden_set.json").read_text(encoding="utf-8"))

REFUSAL_MARKERS = ("无法", "没有找到", "拒绝", "不能")
CATEGORIES = ("normal", "boundary", "regression", "injection")


def _is_refusal(text: str) -> bool:
    return any(m in text for m in REFUSAL_MARKERS)


def grade(sample: dict, text: str) -> list[str]:
    """返回该样本的问题列表；空列表 = 通过。"""
    issues: list[str] = []
    if sample.get("must_refuse"):
        if not _is_refusal(text):
            issues.append("应该拒绝但给出了答案")
    else:
        for kw in sample.get("must_include", []):
            if kw not in text:
                issues.append(f"缺少必含信息：{kw}")
    for kw in sample.get("must_not_include", []):
        if kw in text:
            issues.append(f"不应包含：{kw}")
    if sample.get("must_cite_source") and "来源" not in text:
        issues.append("缺少来源引用")
    return issues


def run(version: str) -> None:
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for s in GOLDEN:
        text = answer(s["question"], version=version)
        issues = grade(s, text)
        by_cat[s["category"]].append(
            {"id": s["id"], "question": s["question"], "pass": not issues, "issues": issues, "answer": text}
        )

    total = sum(len(rows) for rows in by_cat.values())
    passed = sum(1 for rows in by_cat.values() for r in rows if r["pass"])

    print(f"版本：{version}")
    print(f"总样本 {total}，通过 {passed}，通过率 {passed/total:.0%}")
    print("-" * 44)
    for cat in CATEGORIES:
        rows = by_cat[cat]
        cp = sum(1 for r in rows if r["pass"])
        print(f"  {cat:10s} {cp}/{len(rows)} 通过")
    print("-" * 44)

    failed = [(cat, r) for cat in CATEGORIES for r in by_cat[cat] if not r["pass"]]
    if failed:
        print("失败样本：")
        for cat, r in failed:
            print(f"  [{cat}] {r['id']} —— {', '.join(r['issues'])}")
            print(f"         Q: {r['question']}")
            print(f"         A: {r['answer']}")
    else:
        print("全部通过。")

    report = {cat: by_cat[cat] for cat in CATEGORIES}
    out = HERE / f"report-{version}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已写入：{out.name}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v2", choices=["v1", "v2"])
    args = ap.parse_args()
    run(args.version)
