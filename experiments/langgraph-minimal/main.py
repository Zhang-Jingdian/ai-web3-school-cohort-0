"""LangGraph 最小版：检索 → 工具调用 → 结构化输出 → 失败重试

对应 Handbook「框架（Frameworks）」章节的最小实践。
用一个真实的 LangGraph graph 跑通四个点：

  1. 检索      —— retrieve 节点：本地“协议文档”只读检索
  2. 工具调用  —— agent 节点：模型自己决定调用哪个工具
  3. 结构化输出 —— validate 节点：强制最终答案是合法 JSON，不合规打回重试
  4. 失败重试  —— get_contract 第一次必失败，模型重试后成功

运行前：
  export DEEPSEEK_API_KEY=sk-xxxx
  python main.py "0x1234 这个合约的 owner 是谁？"

概念对照（Handbook Frameworks）：
  State  = “任务走到哪一步”显式记录，不藏在聊天历史里
  Node   = 执行动作（检索 / 调用模型 / 执行工具 / 校验）
  Edge   = 控制流（普通边 + 条件边）
  retry  = 失败后从哪个节点继续，且有次数上限
"""
from __future__ import annotations

import json
import os
import sys
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages


# ---------------------------------------------------------------------------
# 1. State：把“任务走到哪一步”显式记下来（对应「长流程需要显式状态」）
# ---------------------------------------------------------------------------
class AgentState(TypedDict):
    query: str                                  # 用户原始问题
    context: str                                # 检索回来的材料
    messages: Annotated[list, add_messages]     # 对话/工具消息（累加，不覆盖）
    attempts: int                               # 结构化输出不合规时的重试次数
    max_attempts: int                           # 最多重试几次
    valid: bool                                 # 最终输出是否已是合法 JSON


# ---------------------------------------------------------------------------
# 2. 工具：只读检索 + 一个“第一次必失败”的模拟 RPC
# ---------------------------------------------------------------------------
DOCS = {
    "owner": "合约 owner 地址是 0xAAA111...；owner 权限可转移，转移需 48h 时间锁。",
    "withdraw": "withdraw(amount) 会从合约转出 token；仅 owner 可调用，需先通过 multi-sig 确认。",
    "voting": "治理投票通过阈值是 51%；提案从提交到可执行至少 3 天。",
}


@tool
def search_docs(query: str) -> str:
    """在本地“协议文档”里按关键词检索（只读）。query 是要查的关键词。"""
    hits = [v for k, v in DOCS.items() if k in query.lower()]
    return "\n".join(hits) if hits else "没有找到相关文档。"


_CALL_COUNT = 0  # 模拟“第一次必失败”的外部依赖（每次进程运行会重置）


@tool
def get_contract(address: str) -> str:
    """查询链上合约信息（模拟外部 RPC）。address 是合约地址。"""
    global _CALL_COUNT
    _CALL_COUNT += 1
    if _CALL_COUNT == 1:
        raise RuntimeError("RPC 超时（模拟第一次失败）")
    return f"{address} 部署在 mainnet，是 ERC-20 合约。"


TOOLS = [search_docs, get_contract]

SYSTEM_PROMPT = (
    "你是协议文档助手。规则：\n"
    "1. 先根据检索材料回答；若问题涉及具体合约地址（如 0x...），必须先调用 get_contract 查询。\n"
    '2. 最终答案只输出一个 JSON 对象，不要多余文字：'
    '{"answer": "...", "sources": [...], "needs_check": true/false}'
)


def _get_llm():
    # 每次调用才读 env，导入本模块时不需要 key（便于先 smoke-test 图结构）
    return ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        temperature=0,
    )


# ---------------------------------------------------------------------------
# 3. 节点
# ---------------------------------------------------------------------------
def retrieve(state: AgentState) -> dict:
    """检索节点：先本地查，把材料放进 context（这一步不调用模型）。"""
    result = search_docs.invoke({"query": state["query"]})
    return {"context": result}


def agent(state: AgentState) -> dict:
    """模型节点：基于 context 决定调用工具，或给出结构化答案。"""
    llm = _get_llm().bind_tools(TOOLS)

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        SystemMessage(
            content=f"已检索到的材料：\n{state['context']}"
            if state["context"]
            else "暂无检索材料。"
        ),
        HumanMessage(content=state["query"]),
    ]
    messages += state["messages"]  # 带上历史（含工具结果/失败记录），让模型能重试

    resp = llm.invoke(messages)
    return {"messages": [resp]}


def tools_node(state: AgentState) -> dict:
    """执行模型发起的工具调用；失败时把错误写回 ToolMessage，让模型重试。"""
    by_name = {t.name: t for t in TOOLS}
    last = state["messages"][-1]
    out = []
    for call in last.tool_calls:
        t = by_name[call["name"]]
        try:
            result = t.invoke(call["args"])
            content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        except Exception as e:
            # 失败不直接炸掉整条图，而是记下错误交给模型，模拟“失败重试”
            content = f"调用失败：{e}（请重试一次）"
        out.append(ToolMessage(content=content, tool_call_id=call["id"]))
    return {"messages": out}


def _strip_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def validate(state: AgentState) -> dict:
    """结构化输出检查：最终答案必须是合法 JSON，否则（有预算时）打回重试。"""
    text = _strip_fence(state["messages"][-1].content)
    try:
        json.loads(text)
        return {"valid": True}
    except Exception:
        return {
            "valid": False,
            "attempts": state["attempts"] + 1,
            "messages": [
                HumanMessage(
                    content='你上一轮没有输出合法 JSON。请只输出一个 JSON 对象：'
                    '{"answer": "...", "sources": [...], "needs_check": true/false}'
                )
            ],
        }


# ---------------------------------------------------------------------------
# 4. 边 / 路由
# ---------------------------------------------------------------------------
def route_after_agent(state: AgentState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"       # 模型还想调工具 → 去执行
    return "validate"        # 模型给出最终答案 → 去校验


def route_after_validate(state: AgentState) -> str:
    if state["valid"]:
        return END
    if state["attempts"] >= state["max_attempts"]:
        return END            # 重试用尽，放弃，返回原始输出
    return "agent"            # 打回模型重试


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("retrieve", retrieve)
    g.add_node("agent", agent)
    g.add_node("tools", tools_node)
    g.add_node("validate", validate)

    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "agent")
    g.add_conditional_edges("agent", route_after_agent, {"tools": "tools", "validate": "validate"})
    g.add_edge("tools", "agent")
    g.add_conditional_edges("validate", route_after_validate, {"agent": "agent", END: END})
    return g.compile()


# ---------------------------------------------------------------------------
# 5. 入口
# ---------------------------------------------------------------------------
def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "0x1234 这个合约的 owner 是谁？"
    graph = build_graph()
    result = graph.invoke(
        {
            "query": query,
            "context": "",
            "messages": [],
            "attempts": 0,
            "max_attempts": 3,
            "valid": False,
        }
    )
    print("=" * 60)
    print("最终输出：")
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
