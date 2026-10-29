# agent 服务测试：知识库检索 + 意图识别 + /chat 接口
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import app, classify_intent  # noqa: E402
from knowledge import search_knowledge  # noqa: E402


client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["knowledge_blocks"] >= 5


def test_knowledge_search():
    hits = search_knowledge("太阳能灯防水吗", top_k=3)
    assert hits
    assert any("防水" in h["body"] or "太阳能" in h["body"] for h in hits)


def test_chat_greeting():
    r = client.post("/api/v1/chat", json={"message": "你好"})
    assert r.status_code == 200
    data = r.json()
    assert data["intent"] == "greeting"
    assert data["response"]
    assert data["session_id"]


def test_chat_product_intent_and_citations():
    r = client.post("/api/v1/chat", json={"message": "推荐一款防水的太阳能庭院灯"})
    data = r.json()
    assert data["intent"] == "product"
    assert data["citations"]  # 命中知识库引用
    assert "太阳能" in data["response"]


def test_chat_aftersale_intent():
    r = client.post("/api/v1/chat", json={"message": "我想申请退款"})
    assert r.json()["intent"] == "aftersale"


def test_chat_logistics_intent():
    r = client.post("/api/v1/chat", json={"message": "我的快递到哪了"})
    assert r.json()["intent"] == "logistics"


def test_chat_session_keeps_history():
    sid = ""
    for msg in ["你好", "推荐太阳能庭院灯"]:
        r = client.post("/api/v1/chat", json={"message": msg, "session_id": sid})
        assert r.status_code == 200
        sid = r.json()["session_id"]
    assert sid


def test_chat_empty_message():
    r = client.post("/api/v1/chat", json={"message": "  "})
    assert r.status_code == 200
    assert r.json()["intent"] == "empty"


def test_sessions_persist_to_file(tmp_path, monkeypatch):
    """会话历史落盘：重启后仍能读到"""
    import importlib

    monkeypatch.setenv("SESSION_STORE", str(tmp_path / "sessions.json"))
    import sessions as session_store

    importlib.reload(session_store)
    session_store.append_turn("s-persist", "user", "你好")
    session_store.append_turn("s-persist", "assistant", "您好")
    # 清缓存模拟重启
    session_store._cache = None
    history = session_store.get_history("s-persist")
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert (tmp_path / "sessions.json").exists()


def test_extract_order_id():
    from tools import extract_order_id

    assert extract_order_id("我的订单 2026.10.29.16.9.48 到哪了") == "2026.10.29.16.9.48"
    assert extract_order_id("没有订单号") == ""


def test_tool_degrades_without_token(monkeypatch):
    """未配置 SERVICE_TOKEN 时工具降级，不影响问答"""
    monkeypatch.delenv("SERVICE_TOKEN", raising=False)
    from tools import try_answer_with_tools

    assert try_answer_with_tools("订单 2026.10.29.16.9.48 到哪了") == ""


def test_describe_order_shipped():
    from tools import describe_order

    text = describe_order(
        {
            "order_id": "2026.10.3.14.0.3",
            "product": "太阳能庭院灯",
            "amount": 180.0,
            "status": "shipped",
            "ship_company_name": "顺丰速运",
            "logistics_code": "SF123",
            "shipped_at": "2026-10-05T09:30:00",
        }
    )
    assert "待收货" in text
    assert "顺丰速运 SF123" in text


def test_extract_order_id_plain_number():
    """种子订单号是纯数字（1001-1005）也要能识别"""
    from tools import extract_order_id

    assert extract_order_id("订单 1003 到哪了") == "1003"
    assert extract_order_id("订单 2026.10.29.20.9.55 发货了吗") == "2026.10.29.20.9.55"
