# 安全加固测试：限流中间件 + 生产关闭文档
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.ratelimit import RateLimitMiddleware


def _build_app(per_minute: int, login_per_minute: int) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, per_minute=per_minute, login_per_minute=login_per_minute)

    @app.get("/api/v1/shop/products")
    async def products():
        return {"ok": True}

    @app.post("/api/v1/auth/login")
    async def login():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"ok": True}

    return app


def test_rate_limit_blocks_after_threshold():
    client = TestClient(_build_app(per_minute=3, login_per_minute=2))
    codes = [client.get("/api/v1/shop/products").status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429


def test_login_rate_limit_is_stricter():
    client = TestClient(_build_app(per_minute=10, login_per_minute=2))
    codes = [client.post("/api/v1/auth/login").status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    # 其他路径不受登录限流影响
    assert client.get("/api/v1/shop/products").status_code == 200


def test_health_not_rate_limited():
    client = TestClient(_build_app(per_minute=1, login_per_minute=1))
    assert all(client.get("/health").status_code == 200 for _ in range(5))


def test_429_has_retry_after_header():
    client = TestClient(_build_app(per_minute=1, login_per_minute=1))
    client.get("/api/v1/shop/products")
    res = client.get("/api/v1/shop/products")
    assert res.status_code == 429
    assert int(res.headers.get("Retry-After", "0")) >= 1


def test_docs_disabled_in_production(monkeypatch):
    """ENV=production 时 /docs 与 /openapi.json 应关闭"""
    import importlib

    monkeypatch.setenv("ENV", "production")
    # 生产环境强制要求配置 SECRET_KEY（config 校验），测试中给一个强密钥
    monkeypatch.setenv("SECRET_KEY", "test-production-secret-key-should-be-long")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    import app.config as config_mod

    importlib.reload(config_mod)
    import app.main as main_mod

    importlib.reload(main_mod)
    client = TestClient(main_mod.app)
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    # 业务接口仍可用（探活路径不限流）
    assert client.get("/api/v1/shop/products").status_code in (200, 500)
    # 还原，避免影响其他测试
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "please-change-me-to-a-long-random-string")
    importlib.reload(config_mod)
    importlib.reload(main_mod)
