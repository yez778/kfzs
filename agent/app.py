# 星途 AI 智能客服服务（FastAPI 独立微服务）
# 默认 LLM_PROVIDER=mock 本地运行；配置 LLM_API_KEY 后切换 DeepSeek。
# 会话历史落盘（sessions.py）；订单/物流类问题走工具查 server 真实数据（tools.py）。
import os
import uuid

from fastapi import FastAPI
from pydantic import BaseModel

import sessions as session_store
from knowledge import search_knowledge
from llm import LLMError, chat
from tools import extract_order_id, tools_status, try_answer_with_tools

app = FastAPI(title="星途 AI 智能客服", version="1.1.0")


class ChatIn(BaseModel):
    message: str
    session_id: str = ""


class ChatOut(BaseModel):
    session_id: str
    response: str
    intent: str
    citations: list[str]
    hits: list[dict]
    llm_mode: str
    tool_used: str = ""


@app.get("/health")
async def health() -> dict:
    from knowledge import RULES, kb

    return {
        "status": "ok",
        "service": "xingtu-agent",
        "version": "1.1.0",
        "llm_mode": (os.getenv("LLM_PROVIDER") or "mock"),
        "knowledge_blocks": len(kb.sections),
        "rules": len(RULES),
        "sessions": session_store.stats(),
        "tools": tools_status(),
    }


@app.post("/api/v1/chat", response_model=ChatOut)
async def chat_api(payload: ChatIn) -> ChatOut:
    message = (payload.message or "").strip()
    mode = os.getenv("LLM_PROVIDER") or "mock"
    if not message:
        return ChatOut(
            session_id=payload.session_id,
            response="请告诉我你想咨询的问题～",
            intent="empty",
            citations=[],
            hits=[],
            llm_mode=mode,
        )

    sid = payload.session_id or str(uuid.uuid4())
    intent = classify_intent(message)

    # 1. 工具优先：消息里带订单号 → 查真实订单/物流（需要 SERVICE_TOKEN）
    tool_used = ""
    if extract_order_id(message):
        tool_answer = try_answer_with_tools(message)
        if tool_answer:
            tool_used = "order_query"
            session_store.append_turn(sid, "user", message)
            session_store.append_turn(sid, "assistant", tool_answer)
            return ChatOut(
                session_id=sid,
                response=tool_answer,
                intent=intent,
                citations=["订单系统"],
                hits=[],
                llm_mode=mode,
                tool_used=tool_used,
            )

    # 2. 知识库检索
    hits = search_knowledge(message, top_k=3)
    citations = [h["title"] for h in hits]

    # 3. LLM 生成（mock 时基于知识库规则）
    history = session_store.get_history(sid)
    history.append({"role": "user", "content": message})
    history = history[-8:]
    system = (
        "你是星途户外照明商城的 AI 客服。回答要友好、简洁、准确；"
        "优先依据知识库内容作答，并引用知识来源标题；不确定时请引导用户提供订单号或商品名。"
    )
    if hits:
        context = "\n\n".join(f"【{h['title']}】{h['body']}" for h in hits)
        system += "\n\n以下是知识库检索到的资料：\n" + context
    try:
        response = chat(history, system=system)
    except LLMError as exc:
        response = f"（客服服务暂时不可用：{exc}）"

    session_store.append_turn(sid, "user", message)
    session_store.append_turn(sid, "assistant", response)
    return ChatOut(
        session_id=sid,
        response=response,
        intent=intent,
        citations=citations,
        hits=hits,
        llm_mode=mode,
        tool_used=tool_used,
    )


def classify_intent(message: str) -> str:
    """规则意图识别：商品 / 订单 / 物流 / 售后 / 支付 / 问候 / 其他"""
    m = message.lower()
    if extract_order_id(message):
        return "order"
    if any(k in m for k in ["你好", "hi", "hello", "在吗", "请问"]):
        return "greeting"
    if any(k in m for k in ["退款", "退货", "换货", "售后", "保修", "维修"]):
        return "aftersale"
    if any(k in m for k in ["物流", "快递", "发货", "到哪", "运单"]):
        return "logistics"
    if any(k in m for k in ["订单", "下单", "我的单", "取消订单"]):
        return "order"
    if any(k in m for k in ["支付", "付款", "优惠", "折扣", "红包", "价格", "多少钱"]):
        return "payment"
    if any(k in m for k in ["灯", "柱头", "壁灯", "太阳能", "庭院", "商品", "推荐", "防水", "尺寸", "安装"]):
        return "product"
    return "other"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8100)
