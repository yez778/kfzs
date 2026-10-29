# 星途 AI 智能客服服务（FastAPI 独立微服务）
# 默认 LLM_PROVIDER=mock 本地运行；配置 LLM_API_KEY 后切换 DeepSeek。
import os
import uuid

from fastapi import FastAPI
from pydantic import BaseModel

from knowledge import search_knowledge
from llm import LLMError, chat

app = FastAPI(title="星途 AI 智能客服", version="1.0.0")

# 简单会话内存：session_id -> 最近消息（进程内，重启清空）
SESSIONS: dict[str, list[dict]] = {}


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


@app.get("/health")
async def health() -> dict:
    from knowledge import RULES, kb
    return {
        "status": "ok",
        "service": "xingtu-agent",
        "llm_mode": (os.getenv("LLM_PROVIDER") or "mock"),
        "knowledge_blocks": len(kb.sections),
        "rules": len(RULES),
    }


@app.post("/api/v1/chat", response_model=ChatOut)
async def chat_api(payload: ChatIn) -> ChatOut:
    message = (payload.message or "").strip()
    if not message:
        return ChatOut(
            session_id=payload.session_id,
            response="请告诉我你想咨询的问题～",
            intent="empty",
            citations=[],
            hits=[],
            llm_mode=(os.getenv("LLM_PROVIDER") or "mock"),
        )

    sid = payload.session_id or str(uuid.uuid4())
    history = SESSIONS.get(sid, [])
    history.append({"role": "user", "content": message})
    history = history[-8:]  # 只保留最近 8 条

    # 1. 意图识别（规则）
    intent = classify_intent(message)

    # 2. 知识库检索
    hits = search_knowledge(message, top_k=3)
    citations = [h["title"] for h in hits]

    # 3. LLM 生成（mock 时基于检索命中与规则）
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

    history.append({"role": "assistant", "content": response})
    SESSIONS[sid] = history
    return ChatOut(
        session_id=sid,
        response=response,
        intent=intent,
        citations=citations,
        hits=hits,
        llm_mode=(os.getenv("LLM_PROVIDER") or "mock"),
    )


def classify_intent(message: str) -> str:
    """规则意图识别：商品 / 订单 / 物流 / 售后 / 支付 / 问候 / 其他"""
    m = message.lower()
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
