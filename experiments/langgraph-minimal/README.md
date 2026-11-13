# LangGraph 最小版

对应 Handbook「框架（Frameworks）」章节的最小实践：用真实 LangGraph 跑通
**检索 → 工具调用 → 结构化输出 → 失败重试** 四件事。

## 图结构

```
START → retrieve(检索) → agent(模型) ──有工具调用──> tools(执行工具) ──> agent
                                  └──无工具调用──> validate(校验 JSON)
                                                      │ 合法 → END
                                                      │ 不合法且未超次数 → 打回 agent
                                                      └ 超次数 → END（放弃）
```

- **State**：`query / context / messages / attempts / max_attempts / valid`，任务进度显式记在 state 里，不藏在聊天历史。
- **retrieve**：本地“协议文档”只读检索（不调用模型）。
- **agent**：DeepSeek 模型决定调用工具，或给出最终 JSON 答案。
- **tools**：执行工具；`get_contract` 第一次必失败，失败写成 ToolMessage 交回模型重试。
- **validate**：强制最终答案是合法 JSON，不合规打回重试，重试有次数上限。

## 环境（一次性）

```bash
# 1. 装 Python 3.12（当前系统只有 3.9，LangGraph 需要 ≥3.10）
brew install python@3.12

# 2. 在仓库根目录建 venv 并装依赖
cd /Users/zjd/workbench/ai-web3-school-cohort-0
python3.12 -m venv .venv
.venv/bin/pip install -r experiments/langgraph-minimal/requirements.txt
```

## 运行

```bash
cd /Users/zjd/workbench/ai-web3-school-cohort-0
export DEEPSEEK_API_KEY=sk-xxxx

.venv/bin/python experiments/langgraph-minimal/main.py "0x1234 这个合约的 owner 是谁？"
```

不带参数会走默认问题（会触发 `get_contract` 失败→重试）。

## 观察点

- 运行日志里会看到 `get_contract` 第一次报 `RPC 超时`，之后模型重试成功。
- 最终答案是一个 JSON：`{"answer": ..., "sources": [...], "needs_check": ...}`。
- 试着把问题改成纯知识问题（如“withdraw 谁能调”），看它跳过工具、直接检索回答。

> 注意：`.env` 与 `.venv` 都已加入 `.gitignore`，不要把 key 提交到 GitHub。
