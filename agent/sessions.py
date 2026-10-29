# 会话持久化：把 AI 客服会话历史落盘到 JSON 文件，重启后仍可继续。
import json
import os
import threading
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
STORE_FILE = Path(os.getenv("SESSION_STORE") or (DATA_DIR / "sessions.json"))
MAX_SESSIONS = int(os.getenv("SESSION_MAX", "200"))
MAX_TURNS = int(os.getenv("SESSION_MAX_TURNS", "20"))

_lock = threading.Lock()
_cache: dict[str, list[dict]] | None = None


def _load() -> dict[str, list[dict]]:
    global _cache
    if _cache is not None:
        return _cache
    data: dict[str, list[dict]] = {}
    try:
        if STORE_FILE.exists():
            raw = json.loads(STORE_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = {k: v for k, v in raw.items() if isinstance(v, list)}
    except Exception:
        data = {}
    _cache = data
    return _cache


def _save(data: dict[str, list[dict]]) -> None:
    try:
        STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        # 只保留最近 MAX_SESSIONS 个会话（按插入顺序裁剪）
        if len(data) > MAX_SESSIONS:
            for key in list(data.keys())[: len(data) - MAX_SESSIONS]:
                data.pop(key, None)
        STORE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except Exception:
        # 持久化失败不影响对话本身
        pass


def get_history(session_id: str) -> list[dict]:
    """读取会话历史（返回副本，避免外部修改缓存）"""
    with _lock:
        return [dict(m) for m in _load().get(session_id, [])]


def append_turn(session_id: str, role: str, content: str) -> list[dict]:
    """追加一轮消息并落盘，返回截断后的历史（最近 MAX_TURNS 条）"""
    with _lock:
        data = _load()
        history = data.setdefault(session_id, [])
        history.append({"role": role, "content": content})
        if len(history) > MAX_TURNS:
            data[session_id] = history[-MAX_TURNS:]
        _save(data)
        return [dict(m) for m in data[session_id]]


def stats() -> dict:
    with _lock:
        data = _load()
        return {"sessions": len(data), "turns": sum(len(v) for v in data.values())}
