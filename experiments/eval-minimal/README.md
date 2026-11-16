# 最小 eval（文档问答）

对应 Handbook「评估（Evaluation）」章节的最小实践：给一个「文档问答」原型做最小 eval，
用 harness + golden set + 规则评分，回答「这次改动有没有让关键任务更可靠」。

## 结构

```
eval-minimal/
├── system.py        # 被评估对象：确定性「文档问答」系统（v1 / v2 两个版本）
├── golden_set.json  # 30 条标注样本（10 正常 / 10 边界 / 5 历史 bug / 5 注入）
├── harness.py       # eval harness：喂样本 → 跑系统 → 规则评分 → 报告
├── README.md
└── .gitignore       # 忽略 report-*.json
```

## 五个知识节点怎么落地的

| 节点 | 对应实现 |
| --- | --- |
| **Harness** | `harness.py`：喂样本、调用系统、跑 grader、输出报告，可重复运行 |
| **Golden Set** | `golden_set.json`：30 条样本，覆盖正常 / 边界 / 历史 bug / 注入四类 |
| **LLM-as-Judge** | 这里用**规则评分**（对可自动判断的字段），因为系统是确定性的；LLM judge 留给开放式质量 |
| **Regression** | `regression-*` 5 条是「历史 bug」样本，`system.py` 的 v1 故意带两个 bug，v2 修掉 |
| **Observability** | 留作扩展（线上观察），这里只做发布前 eval |

## 样本与评分规则

每条样本标注：`must_include`（必含信息）、`must_not_include`（不得包含）、`must_refuse`（必须拒绝）、
`must_cite_source`（必须带来源）。`harness.py` 的 `grade()` 按这些字段做规则评分。

## 运行

```bash
cd /Users/zjd/workbench/ai-web3-school-cohort-0

.venv/bin/python experiments/eval-minimal/harness.py               # v2（当前）→ 30/30
.venv/bin/python experiments/eval-minimal/harness.py --version v1   # 复现回归 → 18/30
```

## 结果（演示「改动前后各跑一遍」）

| 版本 | 通过率 | 说明 |
| --- | --- | --- |
| v1 | 60%（18/30） | 两个 bug：withdraw 漏「仅 owner」、投票阈值 66% 写错；中文注入漏过 → 泄露答案 |
| v2 | 100%（30/30） | 修掉两个 bug + 补上中文注入识别 + 补「提案」别名 |

v1 的失败集中在 `regression`（1/5）和 `injection`（1/5），正好对应「历史 bug 别复发」和「注入要拒绝」。

## 一个真实收获

第一轮跑 v2 时，`normal-06「提案多久可以执行」` 失败——不是系统 bug，而是「提案」这个事实在知识库里、
但没进 voting 的别名表，所以检索不到。**eval 的作用正是暴露这种覆盖缺口**：补上「提案」别名后 100% 通过。

> 扩展方向：对开放式答案把规则评分换成 LLM-as-Judge；对高风险样本保留人工抽检；把线上失败样本回灌进 golden set。
