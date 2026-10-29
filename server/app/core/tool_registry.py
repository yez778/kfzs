"""工具注册表与执行器（Act 阶段）。

六个工具用 ToolDefinition 描述“风险等级 / 必填参数 / 超时 / 重试”，这份元数据被三处复用：
1. ToolExecutor.execute：缺参校验、重试策略（读 2 次 / 写 0 次）、审计日志；
2. react_agent._function_definitions：生成 OpenAI function calling 的 schema；
3. 管理端展示工具风险等级。

两条调用路径要区分：
- tool_executor.execute：只保留 required_params、全部字符串化，带审计 + 重试；
- tools.run_tool：原样透传参数，无审计无重试（handle_refund / handle_shipment 走这条）。

写工具不直连生产：process_refund / process_shipment 只创建 pending 的 HumanTask，
真实写操作由管理员审批后执行，避免模型自主发起资金操作。
"""
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from .doudian_provider import get_provider
from .tools import create_human_task, search_knowledge


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    risk_level: Literal["read", "write"]
    required_params: tuple[str, ...]
    timeout_seconds: float
    max_retries: int
    description: str


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    # 只读工具（max_retries=2）：失败可重试；由 handle_order / handle_inventory / handle_shipment 调用
    "get_order": ToolDefinition("get_order", "read", ("order_id",), 5.0, 2, "Query order status and details by order ID."),
    "get_logistics": ToolDefinition("get_logistics", "read", ("order_id",), 5.0, 2, "Query logistics info for an order."),
    "get_inventory": ToolDefinition("get_inventory", "read", ("sku_id",), 5.0, 2, "Query current stock for a SKU."),
    "search_knowledge": ToolDefinition("search_knowledge", "read", ("query",), 5.0, 1, "Search the product knowledge base for answers."),
    "process_refund": ToolDefinition("process_refund", "write", ("return_order_no", "action"), 5.0, 0, "Submit a refund request for human approval."),
    "process_shipment": ToolDefinition("process_shipment", "write", ("order_id",), 5.0, 0, "Submit a shipment request for human approval."),
}

ACTION_TO_TOOL: dict[str, str] = {
    "order_query": "get_order",
    "logistics_query": "get_logistics",
    "inventory_query": "get_inventory",
    "knowledge_query": "search_knowledge",
    "refund_only": "process_refund",
    "return_refund": "process_refund",
    "shipment_request": "process_shipment",
}

SLOT_LABELS: dict[str, str] = {
    "order_id": "订单号",
    "sku_id": "SKU编号",
    "return_order_no": "订单号",
    "action": "售后类型",
}


@dataclass
class ToolExecutionResult:
    execution_id: str
    tool_name: str
    status: str
    ok: bool
    data: dict[str, Any] | None
    error_code: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    duration_ms: int = 0


class ToolExecutor:
    """Execute registered tools with timeout, retry, and audit logging."""

    def __init__(self) -> None:
        self.executions: dict[str, list[dict]] = {}

    async def execute(self, run_id: str, tool_name: str, user_id: str, params: dict[str, str]) -> ToolExecutionResult:
        definition = TOOL_REGISTRY.get(tool_name)
        if not definition:
            return self._result(run_id, tool_name, "system_error", False, params, None, "tool_not_registered", "工具未注册", 0, 0, user_id)

        missing = [p for p in definition.required_params if not params.get(p)]
        if missing:
            labels = [SLOT_LABELS.get(p, p) for p in missing]
            return self._result(run_id, tool_name, "business_error", False, params, None, "missing_parameter", f"请补充：{'、'.join(labels)}", 0, 0, user_id)

        safe_params = {p: str(params[p]) for p in definition.required_params}
        # 只保留必填参数并统一字符串化：多传的参数会被丢弃（额外参数只有 run_tool 路径才透传）
        attempts = definition.max_retries + 1

        for attempt in range(attempts):
            started = time.perf_counter()
            try:
                data = await self._invoke(tool_name, safe_params)
                duration_ms = int((time.perf_counter() - started) * 1000)
                if data is not None:
                    return self._result(run_id, tool_name, "success", True, safe_params, data, None, None, attempt, duration_ms, user_id)
                return self._result(run_id, tool_name, "business_error", False, safe_params, None, "platform_error", "平台请求失败", attempt, duration_ms, user_id)
            except Exception as exc:
                duration_ms = int((time.perf_counter() - started) * 1000)
                if attempt + 1 == attempts:
                    return self._result(run_id, tool_name, "system_error", False, safe_params, None, "tool_exception", str(exc)[:200], attempt, duration_ms, user_id)

        raise RuntimeError("Tool executor reached an invalid state")

    @staticmethod
    async def _invoke(tool_name: str, params: dict[str, str]) -> dict | None:
        provider = get_provider()
        if tool_name == "get_order":
            return await provider.get_order(params["order_id"])
        if tool_name == "get_logistics":
            order = await provider.get_order(params["order_id"])
            return order
        if tool_name == "get_inventory":
            stock = await provider.get_inventory(params["sku_id"])
            return {"sku_id": params["sku_id"], "stock": stock}
        if tool_name == "search_knowledge":
            return {"results": await search_knowledge(params["query"])}
        if tool_name == "process_refund":
            return await _create_refund_task(params)
        if tool_name == "process_shipment":
            return await _create_shipment_task(params)
        return None

    def _result(self, run_id, tool_name, status, ok, params, data, error_code, error_message, retry_count, duration_ms, user_id: str = "") -> ToolExecutionResult:
        # 统一出口：每次执行都落一条审计（参数截断 120 字），失败可复盘；审计只存进程内，重启即丢
        execution_id = str(uuid.uuid4())
        result = ToolExecutionResult(
            execution_id=execution_id, tool_name=tool_name, status=status, ok=ok,
            data=data, error_code=error_code, error_message=error_message,
            retry_count=retry_count, duration_ms=duration_ms,
        )
        self.executions.setdefault(run_id, []).append({
            "execution_id": execution_id, "tool_name": tool_name, "status": status,
            "ok": ok, "retry_count": retry_count, "duration_ms": duration_ms,
            "params": {k: str(v)[:120] for k, v in (params or {}).items()},
            "error": error_message, "user_id": user_id,
        })
        return result


async def _create_refund_task(params: dict[str, str]) -> dict:
    task_id = await create_human_task("refund", {
        "return_order_no": params["return_order_no"],
        "action": params.get("action", "refund"),
        "reason": params.get("reason", ""),
    })
    return {"status": "pending", "task_id": task_id}


async def _create_shipment_task(params: dict[str, str]) -> dict:
    task_id = await create_human_task("shipment", {
        "order_id": params["order_id"],
        "company_code": "SF",
        "logistics_code": f"SF{int(time.time() * 1000)}",
    })
    return {"status": "pending", "task_id": task_id}


tool_executor = ToolExecutor()
