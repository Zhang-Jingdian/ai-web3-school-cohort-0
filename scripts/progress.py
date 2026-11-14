"""打印 AI × Web3 School 学习进度摘要（只读，不修改任何文件）。

用法：
    .venv/bin/python scripts/progress.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    plan_path = ROOT / "learning-plan.md"
    daily_dir = ROOT / "daily"

    plan = plan_path.read_text(encoding="utf-8") if plan_path.exists() else ""
    done = len(re.findall(r"^- \[x\]", plan, flags=re.M))
    todo = len(re.findall(r"^- \[ \]", plan, flags=re.M))

    m = re.search(r"^- \[ \] \[(.+?)\]\(http.*?进行中", plan, flags=re.M)
    doing = m.group(1) if m else None

    daily = sorted(daily_dir.glob("*.md")) if daily_dir.exists() else []
    dates = [p.stem for p in daily]

    print("AI × Web3 School 学习进度")
    print("-" * 40)
    print(f"已完成条目：{done}")
    print(f"未完成条目：{todo}")
    print(f"进行中：{doing or '（无）'}")
    print(f"每日笔记：{len(daily)} 篇")
    if dates:
        print(f"  范围：{dates[0]} ~ {dates[-1]}")


if __name__ == "__main__":
    main()
