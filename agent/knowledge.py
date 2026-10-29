# 知识库：加载 markdown 文档并做轻量关键词检索（简化 BM25），返回命中片段与引用
import math
import os
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
KNOWLEDGE_FILE = os.getenv("KNOWLEDGE_FILE") or str(DATA_DIR / "knowledge.md")

# (关键词, 回答) 规则表：供 mock 模式直接匹配
RULES: list[tuple[str, str]] = []


def _split_sections(text: str) -> list[dict]:
    """按 ## 二级标题切分为知识块"""
    sections: list[dict] = []
    current_title = "通用"
    current_body: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_body:
                sections.append({"title": current_title, "body": "\n".join(current_body).strip()})
            current_title = line[3:].strip()
            current_body = []
        elif line.strip():
            current_body.append(line.strip())
    if current_body:
        sections.append({"title": current_title, "body": "\n".join(current_body).strip()})
    return [s for s in sections if s["body"]]


def _load_knowledge() -> list[dict]:
    path = Path(KNOWLEDGE_FILE)
    if not path.exists():
        return []
    return _split_sections(path.read_text(encoding="utf-8"))


def _tokenize(text: str) -> list[str]:
    # 简单分词：中文按二元组，英文按单词
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    cjk = re.findall(r"[\u4e00-\u9fa5]", text)
    tokens = words
    for i in range(len(cjk) - 1):
        tokens.append(cjk[i] + cjk[i + 1])
    return tokens


def _build_index(sections: list[dict]) -> dict:
    idx: dict[str, list[tuple[int, int]]] = {}  # token -> [(doc_idx, tf)]
    for i, sec in enumerate(sections):
        tokens = _tokenize(sec["title"] + " " + sec["body"])
        freq: dict[str, int] = {}
        for t in tokens:
            freq[t] = freq.get(t, 0) + 1
        for t, f in freq.items():
            idx.setdefault(t, []).append((i, f))
    return idx


class KnowledgeBase:
    def __init__(self) -> None:
        self.sections = _load_knowledge()
        self.index = _build_index(self.sections)
        self.doc_len = [len(_tokenize(s["title"] + " " + s["body"])) for s in self.sections]
        self.build_rules()

    def build_rules(self) -> None:
        global RULES
        rules: list[tuple[str, str]] = []
        for sec in self.sections:
            body = sec["body"]
            # 每段以「关键词：回答」形式提取若干条（用换行与冒号粗切）
            for line in body.split("\n"):
                line = line.strip()
                if not line or "：" not in line and ":" not in line:
                    continue
                m = re.match(r"^([^：:]{2,12})[：:](.+)$", line)
                if m:
                    rules.append((m.group(1), f"【{sec['title']}】{m.group(2)}"))
        RULES = rules

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []
        # 简化 BM25：idf * tf，按文档累加
        scores: list[float] = [0.0] * len(self.sections)
        for t in set(q_tokens):
            postings = self.index.get(t, [])
            idf = math.log((len(self.sections) + 1) / (len(postings) + 0.5) + 1.0)
            for doc_i, tf in postings:
                dl = self.doc_len[doc_i] or 1
                scores[doc_i] += idf * (tf / (tf + 0.5 + 1.5 * dl / 100.0))
        ranked = sorted(
            range(len(self.sections)),
            key=lambda i: scores[i],
            reverse=True,
        )[:top_k]
        out = []
        for i in ranked:
            if scores[i] > 0:
                out.append({"title": self.sections[i]["title"], "body": self.sections[i]["body"]})
        return out


kb = KnowledgeBase()


def search_knowledge(query: str, top_k: int = 3) -> list[dict]:
    """检索知识库，返回 [{title, body}]，body 截断到 400 字"""
    hits = kb.search(query, top_k)
    for h in hits:
        if len(h["body"]) > 400:
            h["body"] = h["body"][:400] + "…"
    return hits
