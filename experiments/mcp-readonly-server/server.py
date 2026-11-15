"""只读 + 写入（带权限模型）的 MCP Server：search_docs / get_file / write_file / grant_write / revoke_write

对应 Handbook「模型上下文协议（MCP）」章节的最小实践，分两步：

第一步（只读）—— 两个只读工具 + 四条硬约束：
  - search_docs(query)  搜索白名单目录里的项目文档
  - get_file(path)      读取白名单目录里的一个文件
  约束：不能读白名单外路径 / 结果带来源路径 / 调用写日志 / 错误明确返回。

第二步（权限升级）—— 一个「写入工具」的完整权限模型：
  - write_file(path, content)   写入文件，默认拒绝，需用户逐次确认（elicitation）
  - grant_write(path)           授予某路径「本次会话免确认写入」，本身也需用户确认
  - revoke_write(grant_id)      撤销授权，无需确认（降低权限是安全动作）

权限模型三条（对应章节 Permission 节点）：
  1. 默认拒绝：没有授权时，每次写入都弹用户确认；用户拒绝/取消 → 明确返回错误，不执行。
  2. 可撤销：grant_write 授予会话级授权，revoke_write 随时吊销，吊销后回到「逐次确认」。
  3. 可审计：每次写入 / 授权 / 撤销都追加一行到 logs/audit.log（只追加、不覆盖），
     记录动作、目标路径、时间、内容 sha256、字节数。

运行（stdio transport，供 MCP client 拉起）：

  .venv/bin/python experiments/mcp-readonly-server/server.py

验证（本仓库自带的 MCP client 冒烟测试，含 elicitation 回调）：

  .venv/bin/python experiments/mcp-readonly-server/test_client.py
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
    Elicit,
    ElicitationResult,
    MCPServer,
    Resolve,
)
from pydantic import BaseModel

# 白名单：只允许访问这个目录（及其子目录）里的文件；读、写共用同一边界，但写另有权限模型
WHITELIST = (Path(__file__).resolve().parent / "docs").resolve()

# 日志：stdio 占用了 stdout，协议消息不能混进日志，所以只走 stderr + 文件
LOG_PATH = Path(__file__).resolve().parent / "logs" / "calls.log"
AUDIT_PATH = Path(__file__).resolve().parent / "logs" / "audit.log"
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
    name="docs-mcp",
    title="文档 MCP Server（只读 + 带权限的写入）",
    description=(
        "只读搜索/读取白名单目录，并提供一个需要用户确认、可撤销、可审计的写入工具。"
        "工具：search_docs / get_file / write_file / grant_write / revoke_write。"
    ),
)

# ---------------------------------------------------------------------------
# 权限状态：会话级「授权」登记表（stdlib 只演示单个 stdio 连接；生产环境应持久化并绑定账户/session）
# ---------------------------------------------------------------------------
_GRANTS: dict[str, str] = {}  # grant_id -> 允许写入的路径（相对白名单）
_grant_seq = 0


def _audit(op: str, target: str, **fields: object) -> None:
    """追加一条审计记录（只追加，不覆盖）。op 是操作类型（write/grant/revoke），action 等细节走 fields。"""
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "op": op, "target": target, **fields}
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _safe_resolve(requested: str) -> Path | None:
    """把请求路径安全解析到白名单内；越界 / 路径穿越返回 None。"""
    p = Path(requested)
    candidate = p.resolve() if p.is_absolute() else (WHITELIST / p).resolve()
    try:
        candidate.relative_to(WHITELIST)
    except ValueError:
        return None
    return candidate


def _relative(requested: str) -> str | None:
    resolved = _safe_resolve(requested)
    return str(resolved.relative_to(WHITELIST)) if resolved is not None else None


def _is_granted(path: str) -> bool:
    """是否已有覆盖该路径的授权。"""
    rel = _relative(path)
    if rel is None:
        return False
    return any(rel == g or rel.startswith(g.rstrip("/") + "/") for g in _GRANTS.values())


def _ok(payload: dict) -> str:
    return json.dumps({"ok": True, **payload}, ensure_ascii=False)


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 用户确认 schema + 解析器（Resolve）：写入/授权前，用 MCP elicitation 问用户
# ---------------------------------------------------------------------------
class WriteApproval(BaseModel):
    """一次写入/授权的用户确认结果。confirmed 为 true 才放行。"""

    confirmed: bool


def confirm_write(path: str) -> Elicit[WriteApproval] | WriteApproval:
    """写入前确认：已有授权直接放行（不打扰用户）；否则弹确认，默认拒绝。"""
    if _is_granted(path):
        logger.info("write_file path=%r 已有授权，跳过确认", path)
        return WriteApproval(confirmed=True)
    logger.info("write_file path=%r 需要用户确认", path)
    return Elicit(message=f"确认写入文件 {path!r}？此操作会修改磁盘内容。", schema=WriteApproval)


def confirm_grant(path: str) -> Elicit[WriteApproval]:
    """授权本身也是高风险动作，永远弹确认。"""
    logger.info("grant_write path=%r 需要用户确认", path)
    return Elicit(
        message=f"确认授权「本会话免确认写入 {path!r}」？授权后可用 revoke_write 撤销。",
        schema=WriteApproval,
    )


# ---------------------------------------------------------------------------
# 只读工具
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# 写入工具（有副作用，带权限模型）
# ---------------------------------------------------------------------------
@server.tool()
def write_file(
    path: str,
    content: str,
    outcome: Annotated[ElicitationResult[WriteApproval], Resolve(confirm_write)],
) -> str:
    """在白名单目录里写入一个文件（有副作用，需用户确认）。path 是相对 docs/ 的路径；content 是要写入的内容。"""
    if isinstance(outcome, DeclinedElicitation):
        msg = f"用户拒绝了写入：{path!r}"
        logger.warning(msg)
        _audit("write", path, action="declined")
        return _err(msg)
    if isinstance(outcome, CancelledElicitation):
        msg = f"用户取消了写入：{path!r}"
        logger.warning(msg)
        _audit("write", path, action="cancelled")
        return _err(msg)
    approval: WriteApproval = outcome.data
    if not approval.confirmed:
        msg = f"未确认，拒绝写入：{path!r}"
        logger.warning(msg)
        _audit("write", path, action="denied")
        return _err(msg)

    resolved = _safe_resolve(path)
    if resolved is None:
        msg = f"拒绝写入白名单外的路径：{path!r}"
        logger.warning(msg)
        _audit("write", path, action="denied-out-of-whitelist")
        return _err(msg)

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        msg = f"写入失败：{exc}"
        logger.error(msg)
        return _err(msg)

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    rel = str(resolved.relative_to(WHITELIST))
    logger.info("write_file ok：%s（%d 字符）", resolved.name, len(content))
    _audit("write", rel, action="approved", bytes=len(content), sha256=digest)
    return _ok({"source": rel, "written": len(content), "sha256": digest})


@server.tool()
def grant_write(
    path: str,
    outcome: Annotated[ElicitationResult[WriteApproval], Resolve(confirm_grant)],
) -> str:
    """授予某路径「本次会话免确认写入」（有副作用，需用户确认）。path 是相对 docs/ 的路径。"""
    if isinstance(outcome, DeclinedElicitation):
        return _err(f"用户拒绝了授权：{path!r}")
    if isinstance(outcome, CancelledElicitation):
        return _err(f"用户取消了授权：{path!r}")
    if not outcome.data.confirmed:
        return _err(f"未确认，拒绝授权：{path!r}")

    rel = _relative(path)
    if rel is None:
        return _err(f"拒绝授权白名单外的路径：{path!r}")

    global _grant_seq
    _grant_seq += 1
    grant_id = f"grant-{_grant_seq}"
    _GRANTS[grant_id] = rel
    logger.info("grant_write ok：%s -> %s", grant_id, rel)
    _audit("grant", rel, action="granted", grant_id=grant_id)
    return _ok({"grant_id": grant_id, "path": rel})


@server.tool()
def revoke_write(grant_id: str) -> str:
    """撤销一个之前授予的写入授权（降低权限，无需确认）。grant_id 是 grant_write 返回的授权 id。"""
    rel = _GRANTS.pop(grant_id, None)
    if rel is None:
        return _err(f"授权不存在或已撤销：{grant_id!r}")
    logger.info("revoke_write ok：%s（原授权 %s）", grant_id, rel)
    _audit("revoke", rel, action="revoked", grant_id=grant_id)
    return _ok({"grant_id": grant_id, "path": rel, "revoked": True})


if __name__ == "__main__":
    server.run(transport="stdio")
