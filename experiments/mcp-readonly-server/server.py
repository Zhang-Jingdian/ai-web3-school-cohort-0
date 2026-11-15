"""只读 MCP Server：search_docs + get_file

对应 Handbook「模型上下文协议（MCP）」章节的最小实践。
一个只读 MCP server，只暴露两个工具：

  - search_docs(query)  搜索白名单目录里的项目文档（只读）
  - get_file(path)      读取白名单目录里的一个文件（只读）

四条硬约束（对应章节「第一性原理」的三条硬规则 + 最小实践要求）：

  1. 不能读取白名单外路径      —— 越界 / 路径穿越直接拒绝，明确报错
  2. 返回结果必须带来源路径    —— 每个结果都带 source 字段
  3. 工具调用要写日志          —— 每次调用写 stderr + logs/calls.log
  4. 错误要明确返回            —— 错误返回 {"ok": false, "error": ...}，不静默吞掉

运行（stdio transport，供 MCP client 拉起）：

  .venv/bin/python experiments/mcp-readonly-server/server.py

验证（本仓库自带的 MCP client 冒烟测试）：

  .venv/bin/python experiments/mcp-readonly-server/test_client.py
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer

# 白名单：只允许访问这个目录（及其子目录）里的文件
WHITELIST = (Path(__file__).resolve().parent / "docs").resolve()

# 日志：stdio 占用了 stdout，协议消息不能混进日志，所以只走 stderr + 文件
LOG_PATH = Path(__file__).resolve().parent / "logs" / "calls.log"
LOG_PATH.parent.mkdir(exist_ok=True)

logger = logging.getLogger("mcp-readonly")
logger.setLevel(logging.INFO)
_formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
for _handler in (
    logging.StreamHandler(sys.stderr),
    logging.FileHandler(LOG_PATH, encoding="utf-8"),
):
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)

server = MCPServer(
    name="readonly-docs",
    title="只读文档 MCP Server",
    description="只读地搜索、读取白名单目录里的项目文档（search_docs / get_file），不提供任何写入能力。",
)


def _safe_resolve(requested: str) -> Path | None:
    """把请求路径安全解析到白名单内；越界 / 路径穿越返回 None。

    只放行「相对白名单」的路径；绝对路径仅当确实落在白名单内才放行。
    """
    p = Path(requested)
    candidate = p.resolve() if p.is_absolute() else (WHITELIST / p).resolve()
    try:
        candidate.relative_to(WHITELIST)
    except ValueError:
        return None
    return candidate


def _ok(payload: dict) -> str:
    return json.dumps({"ok": True, **payload}, ensure_ascii=False)


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


@server.tool()
def get_file(path: str) -> str:
    """读取白名单目录里的一个文件（只读）。path 是相对于白名单 docs/ 的文件路径，例如 "example.md"。"""
    logger.info("get_file(path=%r)", path)
    resolved = _safe_resolve(path)
    if resolved is None:
        msg = f"拒绝访问白名单外的路径：{path!r}"
        logger.warning("get_file 拒绝：%s", msg)
        return _err(msg)
    if not resolved.is_file():
        msg = f"文件不存在或不是普通文件：{path!r}"
        logger.warning("get_file 失败：%s", msg)
        return _err(msg)
    try:
        content = resolved.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 —— 明确返回错误，不让模型猜
        msg = f"读取失败：{exc}"
        logger.error("get_file 异常：%s", msg)
        return _err(msg)
    logger.info("get_file ok：%s（%d 字符）", resolved.name, len(content))
    return _ok({"source": str(resolved.relative_to(WHITELIST)), "content": content})


@server.tool()
def search_docs(query: str) -> str:
    """在白名单文档里按关键词搜索（只读）。query 是要搜索的关键词或短语。"""
    logger.info("search_docs(query=%r)", query)
    q = (query or "").strip().lower()
    if not q:
        return _err("query 不能为空")

    matches: list[dict] = []
    for f in sorted(WHITELIST.rglob("*")):
        if f.is_dir() or f.suffix not in (".md", ".txt"):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.error("search_docs 读取 %s 失败：%s", f, exc)
            continue
        if q not in text.lower():
            continue
        hits = [ln.strip() for ln in text.splitlines() if q in ln.lower()]
        matches.append(
            {
                "source": str(f.relative_to(WHITELIST)),
                "hits": len(hits),
                "snippet": (hits[0] if hits else text.strip())[:200],
            }
        )
    logger.info("search_docs ok：%d 个命中", len(matches))
    return _ok({"query": query, "matches": matches})


if __name__ == "__main__":
    server.run(transport="stdio")
