# LLM 调用层：DeepSeek 兼容 OpenAI 协议；LLM_PROVIDER=mock 时不发网络请求（本地可演示）
import os

MOCK_REPLY = (
    "我是星途 AI 智能客服。根据知识库，我可以帮你解答商品咨询（柱头灯/壁灯/太阳能庭院灯）、"
    "订单物流、退换货与售后问题。请具体告诉我你想了解什么～"
)

CUSTOM_RULES: list[tuple[str, str]] = []


class LLMError(Exception):
    pass


def _load_custom_rules() -> None:
    """从知识库文件加载的命中规则（由 knowledge 模块注入）"""
    global CUSTOM_RULES
    try:
        from knowledge import RULES  # 顶层导入，与 app.py 一致（本服务以顶层模块运行）
        CUSTOM_RULES = list(RULES or [])
    except Exception:
        CUSTOM_RULES = []


def chat(messages: list[dict], system: str = "") -> str:
    """调用 LLM 生成回复；mock 模式返回基于规则的模板回答，不消耗网络。"""
    provider = (os.getenv("LLM_PROVIDER") or "mock").strip().lower()
    if provider == "mock":
        _load_custom_rules()
        # 只取最后一条用户消息做规则匹配，避免历史消息关键词误命中
        user_text = ""
        for m in messages:
            if m.get("role") == "user":
                user_text = m.get("content", "")
        for kw, answer in CUSTOM_RULES:
            if kw and kw.lower() in user_text.lower():
                return answer
        return MOCK_REPLY

    # DeepSeek（OpenAI 兼容协议）
    api_key = os.getenv("LLM_API_KEY") or ""
    if not api_key:
        raise LLMError("未配置 LLM_API_KEY")
    import httpx

    base = (os.getenv("LLM_BASE_URL") or "https://api.deepseek.com").rstrip("/")
    model = os.getenv("LLM_MODEL") or "deepseek-chat"
    body = {
        "model": model,
        "messages": ([{"role": "system", "content": system}] if system else []) + messages,
        "temperature": 0.2,
        "stream": False,
    }
    try:
        resp = httpx.post(
            f"{base}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        raise LLMError(f"LLM 调用失败: {exc}") from exc
