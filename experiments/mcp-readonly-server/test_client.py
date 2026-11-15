"""MCP client 冒烟测试：拉起只读 server，list_tools 并逐个调用。

验证四条硬约束是否成立：
  1. 白名单内读取 / 搜索正常，结果带 source 路径
  2. 白名单外路径（路径穿越）被明确拒绝，而不是静默失败
  3. 空 query 明确报错
  4. 每次调用在 server 侧留下日志（stderr + logs/calls.log）

用法：
  .venv/bin/python experiments/mcp-readonly-server/test_client.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

SERVER = (Path(__file__).resolve().parent / "server.py").resolve()


def _show(label: str, raw: str) -> None:
    print(f"\n=== {label} ===")
    try:
        obj = json.loads(raw)
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(raw)


async def main() -> int:
    params = StdioServerParameters(
        command=sys.executable,  # 当前 venv 的 python
        args=[str(SERVER)],
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("已注册工具：", [t.name for t in tools.tools])

            # 1. 正常搜索
            r = await session.call_tool("search_docs", {"query": "owner"})
            _show("search_docs(owner)", r.content[0].text)

            # 2. 正常读取，结果带 source
            r = await session.call_tool("get_file", {"path": "protocol.md"})
            _show("get_file(protocol.md)", r.content[0].text)

            # 3. 路径穿越 → 应明确拒绝
            r = await session.call_tool("get_file", {"path": "../../../.env"})
            _show("get_file(../../../.env) → 应被拒绝", r.content[0].text)

            # 4. 空 query → 应明确报错
            r = await session.call_tool("search_docs", {"query": "   "})
            _show("search_docs('   ') → 应报错", r.content[0].text)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
