"""外层 LangGraph 编排：把一次客服请求编译成 14 节点、无环的状态图。

建图六步（build_graph）：
1. StateGraph(AgentState)            绑定状态契约；
2. add_node × 14                     注册节点（route_intent 用 route_intent_node）；
3. START → classify_intent → route_intent；
4. add_conditional_edges(“route_intent”, …)  条件边①：按意图分发（白名单 10 个目标）；
5. 9 个 handler → grounding_check；
6. add_conditional_edges(“grounding_check”, …) 条件边②：通过 → final_answer，失败 → escalate_human。

运行时：run_agent 注入记忆 → _initial_state 铺初值 → agent_graph.ainvoke 一次跑完。
注意图里没有环，所以 iteration / max_iterations 实际恒为 1（防御字段）。
"""
import time
from collections import deque
from typing import Any

from langgraph.graph import END, START, StateGraph

from . import nodes
from .state import AgentState


INTENT_LABELS = {
    "order": "订单查询",
    "product": "商品咨询",
    "refund": "退款售后",
    "shipment": "物流发货",
    "inventory": "库存查询",
    "complaint": "投诉处理",
    "smalltalk": "寒暄问候",
    "unknown": "意图识别",
}

_latencies: deque[float] = deque(maxlen=100)


# @tool
# def get_order(order_id: str) -> dict:
#     """按订单号查询订单状态、商品与金额。"""
#     return DB_ORDERS.get(order_id, {"error": f"订单 {order_id} 不存在"})
#
#
# @tool
# def get_inventory(sku_id: str) -> dict:
#     """查询某个 SKU 的当前库存。"""
#     return {"sku_id": sku_id, "stock": STOCK.get(sku_id, 0)}

# agent = create_react_agent(
#     model=llm,
#     tools=[get_order, get_inventory],   # 只放只读工具
#     prompt=SYSTEM_PROMPT,               # 新版参数名；旧版本用 state_modifier
# )



# import re
# from typing import TypedDict, Optional
# from langgraph.graph import StateGraph, START, END
#
# class State(TypedDict):
#     message: str
#     intent: str
#     tool_result: Optional[dict]
#     final_response: str
#     grounding_passed: Optional[bool]
#
# def classify(state):                      # 节点：返回增量
#     m = state["message"]
#     return {"intent": "order" if "订单" in m else ("product" if "灯" in m else "unknown")}
#
# def route(state):                         # 路由：纯函数返回节点名
#     return {"order": "handle_order", "product": "handle_product"}.get(state["intent"], "handle_unknown")
#
# def handle_order(state):
#     return {"tool_result": {"order_id": "1001", "amount": 350},
#             "final_response": "订单 1001 已付款，金额 350 元。"}
#
# def handle_product(state):
#     return {"tool_result": {"title": "太阳能柱头灯", "price": 350},
#             "final_response": "推荐这款，点卡片看详情。"}
#
# def handle_unknown(state):
#     return {"final_response": "抱歉没听懂，是否需要转人工？"}
#
# def grounding(state):                     # 数字必须能溯源
#     nums = re.findall(r"\d+", state["final_response"])
#     return {"grounding_passed": all(n in str(state.get("tool_result") or "") for n in nums)}
#
# def decide(state):                        # 条件边②：返回节点名
#     return "final_answer" if state["grounding_passed"] else "escalate"
#
# def escalate(state):
#     return {"final_response": "我暂时无法确认，已为您转人工核实。"}
#
# def final_answer(state):
#     return {"final_response": state["final_response"]}
#
# g = StateGraph(State)
# for n, f in [("classify", classify), ("handle_order", handle_order),
#              ("handle_product", handle_product), ("handle_unknown", handle_unknown),
#              ("grounding", grounding), ("escalate", escalate), ("final_answer", final_answer)]:
#     g.add_node(n, f)
# g.add_edge(START, "classify")
# g.add_conditional_edges("classify", route,
#     {"handle_order": "handle_order", "handle_product": "handle_product", "handle_unknown": "handle_unknown"})
# for n in ("handle_order", "handle_product", "handle_unknown"):
#     g.add_edge(n, "grounding")
# g.add_conditional_edges("grounding", decide, {"final_answer": "final_answer", "escalate": "escalate"})
# g.add_edge("escalate", "final_answer")
# g.add_edge("final_answer", END)
#
# app = g.compile()
# out = app.invoke({"message": "订单 1001 什么状态", "intent": "", "tool_result": None,
#                   "final_response": "", "grounding_passed": None})
# print(out["final_response"])   # 订单 1001 已付款，金额 350 元。

def build_graph():
    graph = StateGraph(AgentState)

    node_names = [
        "classify_intent",
        "route_intent",
        "collect_slots",
        "handle_order",
        "handle_product",
        "handle_refund",
        "handle_shipment",
        "handle_inventory",
        "handle_complaint",
        "handle_smalltalk",
        "handle_unknown",
        "grounding_check",
        "escalate_human",
        "final_answer",
    ]
    for name in node_names:
        func = nodes.route_intent_node if name == "route_intent" else getattr(nodes, name)
        graph.add_node(name, func)

    graph.add_edge(START, "classify_intent")
    graph.add_edge("classify_intent", "route_intent")

    handler_names = [
        "collect_slots",
        "handle_order",
        "handle_product",
        "handle_refund",
        "handle_shipment",
        "handle_inventory",
        "handle_complaint",
        "handle_smalltalk",
        "handle_unknown",
    ]
    route_map = {name: name for name in handler_names + ["escalate_human"]}
    graph.add_conditional_edges("route_intent", nodes.route_intent, route_map)

    for name in handler_names:
        graph.add_edge(name, "grounding_check")

    graph.add_conditional_edges(
        "grounding_check",
        lambda state: "final_answer" if state.get("grounding_passed") else "escalate_human",
        {"final_answer": "final_answer", "escalate_human": "escalate_human"},
    )
    graph.add_edge("escalate_human", "final_answer")
    graph.add_edge("final_answer", END)

    return graph.compile()


agent_graph = build_graph()


def _initial_state(messages: list[dict], user_id: str, session_id: str | None = None) -> dict[str, Any]:
    return {
        "messages": messages,
        "user_id": user_id,
        "session_id": session_id,
        "intent": "unknown",
        "order_id": None,
        "product_query": None,
        "tool_results": [],
        "retrieved_chunks": [],
        "citations": [],
        "needs_human": False,
        "human_task_id": None,
        "final_response": "",
        "iteration": 0,
        "max_iterations": 3,
        "grounding_passed": None,
        "slots": {},
        "missing_slots": [],
        "action": "",
        "next_step": "",
        "reason_code": "",
        "memory_context": {},
        "resolved_query": "",
        "after_sales_preview_id": None,
       "citations_detail": [],
       "safety_blocked": False,
        "relevance_score": 0.0,
        "product_cards": [],
   }


async def run_agent(messages: list[dict], user_id: str, session_id: str | None = None, stream_final: bool = False) -> dict[str, Any]:
    """图执行入口：组装初始状态 → ainvoke 一次 → 返回最终 state。

    - 有 session_id：先 build_context 取三层记忆 + WorkflowState，并把最近消息并入 messages；
    - 无 session_id（eval / 单测）：裸跑，图内所有记忆副作用都会被 if 守卫跳过；
    - stream_final=True：final_answer 跳过同步润色，由 WS 处理器逐 token 推送。
    """
    started_at = time.perf_counter()
    try:
        # Load memory context for the session
        if session_id:
            from ..core.memory import memory_service
            ctx = await memory_service.build_context(
                session_id, user_id, messages[-1].get("content", "") if messages else ""
            )
            history = list(ctx.get("recent_messages") or [])
            last = messages[-1] if messages else None
            # 入口层已把用户消息写库，recent_messages 通常已包含本轮；
            # 这里只在“库里的最后一条不是本轮消息”时补上，避免重复追加。
            if last and (not history or history[-1].get("content") != last.get("content")):
                history = history + [last]
            initial = _initial_state(history or messages, user_id, session_id)
            initial["memory_context"] = ctx
        else:
            initial = _initial_state(messages, user_id, session_id)

        initial["stream_final"] = stream_final
        result = await agent_graph.ainvoke(initial)
        return result
    finally:
        _latencies.append(time.perf_counter() - started_at)


def get_avg_latency() -> float:
    if not _latencies:
        return 0.0
    return sum(_latencies) / len(_latencies)


def steps_from_state(state: dict[str, Any]) -> list[dict]:
    intent = state.get("intent") or "unknown"
    steps: list[dict] = [
        {
            "type": "intent",
            "label": INTENT_LABELS.get(intent, "意图识别"),
            "detail": state.get("reason_code") or "",
        }
    ]

    # Show slot extraction info
    slots = state.get("slots") or {}
    if slots:
        detail = ", ".join(f"{k}={v}" for k, v in slots.items())
        steps.append({"type": "slots", "label": "槽位抽取", "detail": detail})

    for result in state.get("tool_results") or []:
        arguments = result.get("arguments") or {}
        detail = ", ".join(f"{key}={value}" for key, value in arguments.items())
        steps.append(
            {
                "type": "tool",
                "label": result.get("name") or "tool",
                "detail": detail,
            }
        )
    if state.get("needs_human"):
        steps.append(
            {
                "type": "status",
                "label": "转人工",
                "detail": state.get("human_task_id"),
            }
        )
    return steps
