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
