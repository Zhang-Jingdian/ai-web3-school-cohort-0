# 只读 MCP Server（最小实践）

对应 Handbook「模型上下文协议（MCP）」章节的最小实践：**做一个只读 MCP server**，
只暴露两个工具，并验证四条硬约束。

## 结构

```
mcp-readonly-server/
├── server.py          # 只读 MCP server（search_docs + get_file）
├── test_client.py     # MCP client 冒烟测试：拉起 server 并逐条调用
├── docs/              # 白名单目录（只允许读取这里）
│   ├── protocol.md    # 示例文档
│   └── notes-mcp.md   # 示例文档
├── logs/calls.log     # 运行时生成，每次工具调用都会写一行（已 gitignore）
└── requirements.txt
```

## 两个工具

| 工具 | 作用 | 约束 |
| --- | --- | --- |
| `search_docs(query)` | 在白名单文档里按关键词搜索 | 结果带 `source` 路径 + `hits` + `snippet` |
| `get_file(path)` | 读取白名单目录里的一个文件 | 结果带 `source` 路径；越界 / 穿越直接拒绝 |

## 四条硬约束（怎么落地）

对应章节「第一性原理」的三条硬规则 + 最小实践要求，每条都能在代码里指认：

1. **工具要有 schema** —— `get_file(path: str)` / `search_docs(query: str)` 的类型注解与
   docstring 由 `MCPServer` 自动转成 MCP 的 input schema，client 侧 `list_tools` 能读到。
2. **不能读取白名单外路径** —— `_safe_resolve()` 用 `Path.resolve()` + `relative_to()` 校验，
   `get_file("../../../.env")` 这类路径穿越会被拒绝。
3. **错误要可传递** —— 所有失败都返回 `{"ok": false, "error": ...}`，不抛异常、不静默吞掉。
4. **权限要在协议外也成立** —— 协议只描述「能读什么」，真正的授权/审计/隔离由 server
   自己的代码实现（白名单、日志），而不是靠模型自觉。

## 运行

```bash
cd /Users/zjd/workbench/ai-web3-school-cohort-0

# 跑 client 冒烟测试（会拉起 server，逐条调用工具）
.venv/bin/python experiments/mcp-readonly-server/test_client.py
```

观察点：

- `search_docs("owner")` 返回命中项，带 `source: "protocol.md"`。
- `get_file("protocol.md")` 返回文件内容，带 `source`。
- `get_file("../../../.env")` 被明确拒绝，返回 `ok: false`。
- `search_docs("   ")` 明确报错，而不是返回空结果。
- 每次调用在 `logs/calls.log` 留下一条记录（INFO / WARNING）。

## 下一步：写入工具的权限升级方案（章节最小实践的后半段）

当前 server 只有只读工具。要加一个「写入工具」（例如 `write_file` / `create_pr`），权限模型
必须先行，否则「方便」会变成「危险」。设计如下：

| 维度 | 只读工具（现状） | 写入工具（需新增） |
| --- | --- | --- |
| 动作类型 | 只读 | 有副作用（改文件 / 发请求 / 转账） |
| 授权 | 无需逐次确认 | **默认拒绝，逐次要求用户确认** |
| 会话 | 本次会话 | 区分「单次授权」vs「长期授权」，长期授权要能撤销 |
| 敏感信息 | 不接触 | 是否可写敏感路径需单独授权 |
| 审计 | 日志记录调用 | 日志记录「谁、何时、写了什么、是否撤销」 |

具体到实现，写入工具至少要满足：

1. **白名单写**：写入路径同样受白名单约束，且与读取白名单分开（可写范围更小）。
2. **用户确认**：调用前必须返回一个需要用户确认的结果，而不是直接执行
   （对应 MCP 的 elicitation / 权限提示机制）。
3. **可撤销**：长期授权要有 session key 或 token，可随时吊销。
4. **审计日志**：每次写入记录操作者、目标路径、diff、时间，且日志只追加、不可改。

> 结论：**MCP 负责「工具发现 + 调用格式」，账户 / 权限 / 审计由系统实现**——协议能描述能力，
> 但不能替你承担安全责任。
