"""FastAPI 应用入口：lifespan 初始化、CORS、路由挂载、健康检查。

启动时做两件事：
1. init_db：建表 + 幂等种子（账号 / 订单 1001-1005 / 库存 / 橱窗商品）；
2. _warm_rag：后台线程重建 Chroma 集合，把启动开销挪出首个请求（探活可先通过）。

所有业务路由统一挂在 /api/v1 下；根路径与 /api/v1/healthz 都供云托管探活。
"""
import logging
import threading
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import (admin, aftersales, auth, chat, doudian_sim, evaluation, fulfillment, internal,
                  knowledge, memory_api, orders, payments, sandbox_gateway, sessions, shop)
from .api import human_chat, product_admin
from .config import settings
from .seed import init_db

logger = logging.getLogger(__name__)


def _warm_rag() -> None:
    # 后台线程预热知识库，不占用事件循环，探活可以先通过
    try:
        import os

        from .rag.store import get_collection

        # 默认复用已持久化的集合：uvicorn --reload 会不断创建新 worker，
        # 如果每次启动都 rebuild，就会删掉别的 worker 正在用的 collection。
        # 改了 data/knowledge/*.md 想强制生效时，设 RAG_REBUILD_ON_START=1。
        rebuild = os.getenv("RAG_REBUILD_ON_START", "0") == "1"
        get_collection(rebuild=rebuild)
    except Exception:
        logger.exception("RAG warmup failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 建表 + 幂等种子（重复启动不会重复插入）
    await init_db()
    # RAG 预热放在 daemon 线程：重建集合可能耗时，不阻塞启动与探活
    threading.Thread(target=_warm_rag, name="rag-warmup", daemon=True).start()
    yield


_is_production = settings.env.strip().lower() in ("production", "prod")

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    # 生产环境关闭交互式文档，减少信息暴露
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if settings.rate_limit_enabled:
    from .core.ratelimit import RateLimitMiddleware

    app.add_middleware(
        RateLimitMiddleware,
        per_minute=settings.rate_limit_per_minute,
        login_per_minute=settings.login_rate_limit_per_minute,
    )

if settings.allowed_hosts and "*" not in settings.allowed_hosts:
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)


app.include_router(auth.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(orders.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(human_chat.router, prefix="/api/v1")
app.include_router(product_admin.router, prefix="/api/v1")
app.include_router(shop.router, prefix="/api/v1")
app.include_router(doudian_sim.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(evaluation.router, prefix="/api/v1")
app.include_router(memory_api.router, prefix="/api/v1")
app.include_router(aftersales.router, prefix="/api/v1")
app.include_router(payments.router, prefix="/api/v1")
app.include_router(fulfillment.router, prefix="/api/v1")
app.include_router(internal.router, prefix="/api/v1")
app.include_router(sandbox_gateway.router, prefix="/api/v1")

_UPLOAD_ROOT = Path(__file__).resolve().parents[1] / "uploads"
_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
(_UPLOAD_ROOT / "avatars").mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_UPLOAD_ROOT), name="uploads")


@app.get("/")
@app.get("/api/v1/healthz")
async def healthz() -> dict:
    # 云托管默认探测根路径；/api/v1/healthz 供业务侧检查
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    # 浏览器会自动请求站点图标；直接回 204，避免访问日志里刷 404
    return Response(status_code=204)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    detail = errors[0].get("msg", "请求参数错误") if errors else "请求参数错误"
    return JSONResponse(status_code=422, content={"detail": detail})
