"""被评估对象：一个确定性的「文档问答」系统。

刻意做成确定性（无 LLM、无随机、无外部依赖），这样 eval 可以完全复现，
专注演示 harness / golden set / 规则评分 / regression 这些概念本身。

有两个版本，用来演示「改动前后各跑一遍」：
  v1 —— 有两个已知 bug：
        1) withdraw 事实漏了「仅 owner 可调用」（权限漏报）
        2) 只识别英文注入，中文注入（忽略/越狱/泄露）会漏过
  v2 —— 修掉了这两个 bug。

用法（由 harness.py 调用）：
  .venv/bin/python experiments/eval-minimal/harness.py             # 跑 v2（当前）
  .venv/bin/python experiments/eval-minimal/harness.py --version v1  # 复现 v1 的回归失败
"""
from __future__ import annotations

# (关键词别名, 事实, 来源)。别名让中英文都能命中。
KNOWLEDGE: list[tuple[tuple[str, ...], str, str]] = [
    (("owner", "所有者", "拥有者"), "合约 owner 地址是 0xAAA111...；owner 权限可转移，转移需 48h 时间锁。", "protocol.md"),
    (("withdraw", "提现", "提取", "取出"), "withdraw(amount) 会从合约转出 token；仅 owner 可调用，需先通过 multi-sig 确认。", "protocol.md"),
    (("voting", "投票", "治理", "提案"), "治理投票通过阈值是 51%；提案从提交到可执行至少 3 天。", "protocol.md"),
    (("mcp", "模型上下文协议"), "MCP 把模型与外部工具、数据源、应用上下文的连接标准化；关键是可描述、可发现、可限制。", "notes-mcp.md"),
    (("permission", "权限"), "MCP 的 Permission 是最容易被低估的问题：只读与写入、会话与长期授权、可撤销与可审计都要区分。", "notes-mcp.md"),
]

# v1 的注入识别只覆盖英文，v2 补上中文
INJECTION_V1 = ("ignore previous instructions", "disregard", "you are dan", "developer mode")
INJECTION_V2 = INJECTION_V1 + ("忽略", "越狱", "泄露", "系统提示")

REFUSAL_NO_MATCH = "我在文档中没有找到相关信息，无法回答。"
REFUSAL_INJECTION = "我无法执行与文档问答无关的指令。"


def answer(question: str, version: str = "v2") -> str:
    q = question.lower()

    # 1) 注入识别
    patterns = INJECTION_V1 if version == "v1" else INJECTION_V2
    if any(p in q for p in patterns):
        return REFUSAL_INJECTION

    # 2) 关键词检索 + 事实拼装
    hits: list[str] = []
    for aliases, fact, src in KNOWLEDGE:
        if any(a in q for a in aliases):
            if version == "v1" and "withdraw" in aliases:
                fact = "withdraw(amount) 会从合约转出 token；任何人都可以调用。"  # v1 bug 1
            if version == "v1" and "voting" in aliases:
                fact = "治理投票通过阈值是 66%；提案从提交到可执行至少 3 天。"      # v1 bug 2
            hits.append(f"{fact} 来源: {src}")

    if not hits:
        return REFUSAL_NO_MATCH
    return "\n".join(hits)
