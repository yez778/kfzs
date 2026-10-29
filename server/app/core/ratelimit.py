# 极简滑动窗口限流：按 客户端 IP + 路径分组限制请求频率。
# 单进程内存实现，够单机/演示使用；多实例生产环境应换成 Redis 计数。
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        per_minute: int = 120,
        login_per_minute: int = 10,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self.per_minute = max(1, int(per_minute))
        self.login_per_minute = max(1, int(login_per_minute))
        self.window = max(1, int(window_seconds))
        # key -> 时间戳队列
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _is_login_path(self, path: str) -> bool:
        return path.endswith("/auth/login") or path.endswith("/auth/wechat")

    def _allow(self, key: str, limit: int, now: float) -> tuple[bool, int]:
        queue = self._hits[key]
        # 清理窗口外的记录
        while queue and now - queue[0] > self.window:
            queue.popleft()
        if len(queue) >= limit:
            retry_after = int(self.window - (now - queue[0])) + 1
            return False, max(1, retry_after)
        queue.append(now)
        return True, 0

    async def dispatch(self, request, call_next):
        # 探活与静态资源不限流
        path = request.url.path
        if request.method == "OPTIONS" or path in ("/health", "/api/v1/health"):
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        limit = self.login_per_minute if self._is_login_path(path) else self.per_minute
        now = time.monotonic()
        allowed, retry_after = self._allow(f"{client}:{path}", limit, now)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试"},
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
