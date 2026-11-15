"""MCP client 冒烟测试：拉起 server，验证「只读」+「写入权限模型」。

只读侧（四条硬约束）：
  1. 白名单内读取/搜索正常，结果带 source 路径
  2. 白名单外路径（路径穿越）被明确拒绝
  3. 空 query 明确报错
  4. 每次调用在 server 侧留下日志

写入侧（权限升级三条）：
  5. 默认拒绝：无授权时写入弹用户确认，用户拒绝 → 明确返回错误、不执行
  6. 用户同意 → 写入成功，返回 source + sha256，审计日志追加一条
  7. grant_write 授予「本会话免确认写入」，返回 grant_id（授权本身也需确认）
  8. 授权后再次写入 → 不再弹确认（跳过 elicitation）
  9. revoke_write 撤销授权
  10. 撤销后再次写入 → 又回到「逐次确认」

用法：
  .venv/bin/python experiments/mcp-readonly-server/test_client.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import deque
from pathlib import Path

import mcp.types as types
from mcp.client.client import Client
from mcp.client.stdio import StdioServerParameters

SERVER = (Path(__file__).resolve().parent / "server.py").resolve()

# 预先排好的用户回答队列（按时间顺序被 elicitation 回调消费）
PLANNED: deque[str] = deque(["decline", "accept", "accept", "accept"])


async def on_elicitation(context, params) -> types.ElicitResult:
    """模拟「人类用户」对每次确认弹窗的回答。"""
    message = getattr(params, "message", "")
    print(f"  [用户确认] {message}")
    if not PLANNED:
        return types.ElicitResult(action="decline")
    choice = PLANNED.popleft()
    if choice == "decline":
        print("      -> 用户选择：拒绝")
        return types.ElicitResult(action="decline")
    print("      -> 用户选择：同意")
    return types.ElicitResult(action="accept", content={"confirmed": True})


def _show(label: str, raw: str) -> None:
    print(f"\n=== {label} ===")
    try:
        print(json.dumps(json.loads(raw), ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(raw)


async def main() -> int:
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])

    async with Client(params, elicitation_callback=on_elicitation) as client:
        tools = await client.list_tools()
        print("已注册工具：", [t.name for t in tools.tools])

        # --- 只读侧 ---
        r = await client.call_tool("search_docs", {"query": "owner"})
        _show("search_docs(owner)", r.content[0].text)

        r = await client.call_tool("get_file", {"path": "protocol.md"})
        _show("get_file(protocol.md)", r.content[0].text)

        r = await client.call_tool("get_file", {"path": "../../../.env"})
        _show("get_file(../../../.env) → 应被拒绝", r.content[0].text)

        r = await client.call_tool("search_docs", {"query": "   "})
        _show("search_docs('   ') → 应报错", r.content[0].text)

        # --- 写入侧：默认拒绝 / 同意 / 授权 / 撤销 ---
        r = await client.call_tool("write_file", {"path": "hello.md", "content": "第一版内容\n"})
        _show("write_file(hello.md) 用户拒绝 → 应不执行", r.content[0].text)

        r = await client.call_tool("write_file", {"path": "hello.md", "content": "第一版内容\n"})
        _show("write_file(hello.md) 用户同意 → 应写入", r.content[0].text)

        r = await client.call_tool("grant_write", {"path": "hello.md"})
        _show("grant_write(hello.md) → 应返回 grant_id", r.content[0].text)
        grant_id = json.loads(r.content[0].text)["grant_id"]

        r = await client.call_tool("write_file", {"path": "hello.md", "content": "第二版内容（授权后免确认）\n"})
        _show("write_file(hello.md) 已授权 → 应免确认直接写入", r.content[0].text)

        r = await client.call_tool("revoke_write", {"grant_id": grant_id})
        _show("revoke_write(grant_id) → 应撤销", r.content[0].text)

        r = await client.call_tool("write_file", {"path": "hello.md", "content": "第三版内容（撤销后又需确认）\n"})
        _show("write_file(hello.md) 撤销后 → 应再次弹确认", r.content[0].text)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
