# 协议文档（示例）

这是白名单目录里的示例文档，供 `search_docs` / `get_file` 检索与读取。

## 合约 owner

- 合约 owner 地址是 0xAAA111...；owner 权限可转移，转移需 48h 时间锁。
- 关键权限：修改费率、暂停合约、升级实现。

## withdraw

- `withdraw(amount)` 会从合约转出 token；仅 owner 可调用，需先通过 multi-sig 确认。
- 单次 withdraw 有上限，超过上限需要治理投票。

## voting

- 治理投票通过阈值是 51%；提案从提交到可执行至少 3 天。
