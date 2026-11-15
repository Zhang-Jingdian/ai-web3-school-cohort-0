# 只读 + 写入（带权限模型）的 MCP Server

对应 Handbook「模型上下文协议（MCP）」章节的最小实践，分两步做完：

1. **只读 server** —— `search_docs` / `get_file`，验证四条硬约束。
2. **写入工具的权限升级** —— `write_file` / `grant_write` / `revoke_write`，把「默认拒绝、
   逐次确认、可撤销、可审计」真正实现成代码（不是只写设计文档）。

## 结构

```
mcp-readonly-server/
├── server.py          # MCP server：2 个只读工具 + 3 个带权限的写入工具
├── test_client.py     # MCP client 冒烟测试：拉起 server，逐条调用（含 elicitation 回调）
├── docs/              # 白名单目录（读、写共用同一边界）
│   ├── protocol.md    # 示例文档
│   └── notes-mcp.md   # 示例文档
├── logs/              # 运行时生成：calls.log（每次调用）、audit.log（写/授权/撤销审计）
├── .gitignore         # 忽略 logs/、测试生成的 docs/hello.md
└── requirements.txt
```

## 五个工具

| 工具 | 作用 | 是否有副作用 | 约束 |
| --- | --- | --- | --- |
| `search_docs(query)` | 在白名单文档里按关键词搜索 | 只读 | 结果带 `source` |
| `get_file(path)` | 读取白名单目录里的一个文件 | 只读 | 越界/穿越直接拒绝 |
| `write_file(path, content)` | 写入文件 | **有副作用** | 默认拒绝，需用户逐次确认 |
| `grant_write(path)` | 授权「本会话免确认写入某路径」 | 有副作用 | 授权本身也需用户确认 |
| `revoke_write(grant_id)` | 撤销一条写入授权 | 降低权限 | 无需确认 |

## 四条硬约束（只读侧）

对应章节「第一性原理」的三条硬规则 + 最小实践要求：

1. **工具要有 schema** —— 类型注解 + docstring 由 `MCPServer` 自动转成 MCP input schema。
2. **不能读取白名单外路径** —— `_safe_resolve()` 用 `Path.resolve()` + `relative_to()` 校验，
   `get_file("../../../.env")` 这类路径穿越会被拒绝。
3. **错误要可传递** —— 所有失败返回 `{"ok": false, "error": ...}`，不抛异常、不静默吞掉。
4. **权限要在协议外也成立** —— 协议只描述「能读什么」，真正的授权/审计由 server 自己的代码实现。

## 写入权限模型（写入侧，已实现）

对应章节 Permission 节点。三条，每条都在 `server.py` 里有对应实现：

1. **默认拒绝（逐次确认）**：没有授权时，`write_file` 通过 MCP **elicitation**（`Resolve` + `Elicit`）
   弹用户确认；用户拒绝 / 取消 → 明确返回错误、不执行，并写审计日志。
2. **可撤销的授权**：`grant_write` 授予「本会话免确认写入某路径」（返回 `grant_id`），
   `revoke_write` 随时吊销；吊销后回到「逐次确认」。
3. **可审计**：每次写入 / 授权 / 撤销都追加一行到 `logs/audit.log`（只追加、不覆盖），
   记录操作类型、目标路径、时间、内容 `sha256`、字节数。

> 说明：授权登记表 `_GRANTS` 是进程内存态（单个 stdio 连接足够演示）；生产环境应持久化并绑定账户 / session。

## 运行

```bash
cd /Users/zjd/workbench/ai-web3-school-cohort-0

# 跑 client 冒烟测试（会拉起 server，覆盖只读 + 写入 + 权限全流程）
.venv/bin/python experiments/mcp-readonly-server/test_client.py
```

观察点（对应 `test_client.py` 里的 10 个断言）：

- 只读侧：`search_docs("owner")` 带 `source`；`get_file("../../../.env")` 被拒绝；空 query 报错。
- 写入侧（关键）：
  - 第一次 `write_file` 弹确认 → **用户拒绝** → 返回 `ok: false`，文件没写。
  - 第二次 `write_file` → **用户同意** → 写入成功，返回 `sha256`。
  - `grant_write` → 返回 `grant-1`。
  - 授权后再 `write_file` → **不再弹确认**（直接写入）。
  - `revoke_write` → 撤销 `grant-1`。
  - 撤销后再 `write_file` → **又弹确认**。

跑完看 `logs/audit.log`，能看到完整的权限生命周期：`declined → approved → granted → approved → revoked → approved`。
