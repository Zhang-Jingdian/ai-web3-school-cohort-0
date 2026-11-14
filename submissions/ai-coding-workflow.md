# 我的 AI Coding 工作流

> 学员：Zhang-Jingdian · 2026-11-14 · 对应 Handbook「氛围编程（Vibe Coding）」挑战路径
> 工具：Claude Code（本仓库的 Learning Agent / AI Coding Agent）

## 一句话原则

**AI 帮你写更多代码，但不替你承担工程判断。** 所以边界由我定，验收由我做。

## 能改（放心让 Agent 动）

- `daily/` —— 每日学习笔记（新增 / 编辑当天文件）
- `experiments/` —— 实验代码（新增文件）
- `submissions/` —— 作业 / 文档产出
- `scripts/` —— 工具脚本（新增）
- `learning-plan.md` —— 勾选进度、更新「进行中」标记
- `README.md` —— 更新说明

## 能跑（Agent 可自动执行）

- 只读 git：`git status` / `git diff` / `git log` / `git branch`
- 读文件、搜索代码
- `.venv/bin/python` 跑本地脚本 / 测试
- `curl` 拉取公开网页（如 Handbook 章节）

## 需停下来确认（先问我，不许自动做）

- `git commit` / `git push` / 改历史（rebase / reset）
- 删除文件、覆盖已有文件
- 装依赖 / 改 `.env` / 涉及任何 API key
- 改 `profile.md` 的画像字段
- 任何链上动作（合约、签名、支付、交易）——本仓库暂不涉及，但原则保留

## 验收（每次改动后我至少做）

1. `git diff` 看改动清单和内容
2. 跑一遍测试 / 脚本确认不报错
3. 检查有没有把密钥、日志、构建产物提交进去
4. 高风险动作必须我明确点头后才执行

## 版本 / 工具记录

- Claude Code CLI（本机）
- Python 3.12.16（Homebrew）· `.venv` · langgraph 1.2.21 / langchain-openai 1.7.4
- DeepSeek API（`DEEPSEEK_API_KEY`，仅存环境变量，不进仓库）
- Git remote：https://github.com/Zhang-Jingdian/ai-web3-school-cohort-0
