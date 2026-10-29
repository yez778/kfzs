# 星途 AI 智能客服 · 独立服务

独立部署的 AI 客服微服务，为商城（server）提供智能问答能力：
**意图识别 → 知识库检索（RAG）→ LLM 生成 → 引用来源**。

## 架构定位

```
wx（微信小程序）──▶ server（商城后端 /chat）──转发──▶ agent（AI 客服服务）
client（Vue 管理端）─────┘                          │
                                                    └─ 知识库（data/knowledge.md）
```

- **agent** 是独立 FastAPI 服务（端口 8100），只负责客服问答，不依赖商城数据库；
- **server** 配置 `AGENT_SERVICE_URL=http://127.0.0.1:8100` 后，商城 `/chat` 自动转发到 agent，
  小程序「AI客服」tab 即可获得 agent 能力；未配置时走 server 内置客服链路（默认，便于单机演示）。

## 启动

```bash
cd agent
pip install -r requirements.txt
python -m uvicorn app:app --port 8100 --reload     # 默认 LLM_PROVIDER=mock，无需 API Key
```

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查：服务状态、LLM 模式、知识库条数 |
| POST | `/api/v1/chat` | `{message, session_id?}` → `{response, citations, intent, session_id, product_hits}` |

## 配置（.env 或环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `mock` 本地模板回答 / `deepseek` 调用 DeepSeek |
| `LLM_API_KEY` | 空 | DeepSeek API Key（`LLM_PROVIDER=deepseek` 时需要） |
| `LLM_BASE_URL` | `https://api.deepseek.com` | LLM 接口地址 |
| `LLM_MODEL` | `deepseek-chat` | 模型名 |
| `KNOWLEDGE_FILE` | `data/knowledge.md` | 知识库文档路径 |

## 知识库

`data/knowledge.md` 内置商品咨询、订单物流、退换货、支付与售后 FAQ；
问答时先做关键词检索（BM25 简化实现）取 Top-K 片段，再交给 LLM 生成带引用来源的回复。
新增知识：直接编辑 `data/knowledge.md` 追加 `## 主题` 段落即可，重启生效。

## 测试

```bash
cd agent && python -m pytest tests -q
```
