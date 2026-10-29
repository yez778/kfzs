from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine.url import make_url


class Settings(BaseSettings):
    # 全局应用与安全配置
    app_name: str = "doudian-agent"
    env: str = "development"
    secret_key: str = "please-change-me-to-a-long-random-string"
    jwt_expire_minutes: int = 480
    agent_service_url: str = ""
    # 内部服务令牌：供 agent 等内部服务调用 /internal/* 接口
    service_token: str = ""
    # 限流与信任主机（生产建议显式配置 ALLOWED_HOSTS）
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 180
    login_rate_limit_per_minute: int = 10
    allowed_hosts_raw: str = Field(default="*", alias="ALLOWED_HOSTS")
    cors_origins_raw: str = Field(
        default="http://localhost:3000,http://localhost:5173",
        alias="CORS_ORIGINS",
    )

    database_url: str = "sqlite+aiosqlite:///./doudian.db"
    # 云托管 MySQL：配了 MYSQL_ADDRESS 后优先走 MySQL，本机不配则继续用 SQLite
    mysql_address: str = ""
    mysql_username: str = ""
    mysql_password: str = ""
    mysql_database: str = "doudian"
    redis_url: str = "redis://localhost:6379/0"
    chroma_persist_dir: str = "./chroma_data"
    chroma_url: str = ""

    llm_provider: str = "mock"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.4

    embedding_provider: str = "onnx"
    embedding_model: str = "text-embedding-3-small"
    embedding_api_key: str = ""
    embedding_base_url: str = ""

    doudian_provider: str = "mock"
    doudian_app_key: str = ""
    doudian_app_secret: str = ""
    doudian_access_token: str = ""
    doudian_refresh_token: str = ""
    doudian_base_url: str = "https://openapi-fxg.jinritemai.com"

    # 低相关性回复审核阈值：RAG 检索相关性低于该值时草稿转人工审核
    relevance_threshold: float = 0.1

    admin_username: str = "admin"
    admin_password: str = "Admin@123456"
    staff_username: str = "staff"
    staff_password: str = "Staff@123456"
    customer_username: str = "customer"
    customer_password: str = "Customer@123"

    wechat_appid: str = "wx2aa5f2c85393e806"
    wechat_secret: str = ""
    initial_wallet: float = 2000.0

    # 微信支付：三种模式
    #   sandbox   本地自建沙箱（HMAC 模拟，默认，不触达微信，可一键“支付成功”）
    #   v2sandbox 官方 V2 仿真测试系统（真实请求 sandboxnew 接口，XML+MD5，仅后端联调）
    #   wechat    真实微信支付（V3，预留）
    payment_enabled: bool = True
    payment_mode: str = "sandbox"  # sandbox | v2sandbox | wechat
    payment_appid: str = ""  # 留空时回退使用 WECHAT_APPID
    payment_mch_id: str = "1900000000"  # 本地沙箱占位商户号；v2sandbox/wechat 必须填真实商户号
    payment_mch_key: str = "sandbox-mch-key-change-me"  # 本地沙箱 HMAC 密钥；生产必须通过环境变量覆盖
    payment_notify_url: str = ""  # 异步回调地址，例如 https://your-domain/api/v1/payments/notify/wechat
    payment_order_expire_minutes: int = 15
    # 官方 V2 仿真专用：真实 APIv2 密钥（用它调 getsignkey 换取沙箱密钥）与一个真实测试 openid
    payment_api_v2_key: str = ""
    # V2 沙箱网关基址：官方 sandboxnew 已下线（404），可指向本地/自建 V2 协议网关
    payment_sandbox_base: str = "https://api.mch.weixin.qq.com/sandboxnew"
    payment_sandbox_openid: str = ""

    @property
    def payment_is_v2_sandbox(self) -> bool:
        return (self.payment_mode or "").strip().lower() == "v2sandbox"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def allowed_hosts(self) -> list[str]:
        # TrustedHost 白名单：逗号分隔，* 表示不限制
        return [h.strip() for h in (self.allowed_hosts_raw or "*").split(",") if h.strip()]

    @property
    def cors_origins(self) -> list[str]:
        # 兼容逗号分隔的环境变量，返回允许跨域的源列表
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def jwt_secret(self) -> str:
        return self.secret_key

    @model_validator(mode="after")
    def _validate_production_secret_key(self) -> "Settings":
        # 生产环境必须通过环境变量设置强密钥，防止使用默认值签发 JWT
        if self.env == "production" and (
            not self.secret_key or self.secret_key == "please-change-me-to-a-long-random-string"
        ):
            raise ValueError(
                "SECRET_KEY 未设置或仍为默认值，生产环境必须配置强随机密钥，"
                "例如：python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return self

    @property
    def resolved_database_url(self) -> str:
        # 云托管控制台填 MYSQL_* 即可，密码里的特殊字符会自动编码进连接串
        if self.mysql_address.strip() and self.mysql_username.strip():
            user = quote_plus(self.mysql_username)
            password = quote_plus(self.mysql_password)
            host = self.mysql_address.strip()
            db = (self.mysql_database or "doudian").strip() or "doudian"
            return f"mysql+aiomysql://{user}:{password}@{host}/{db}?charset=utf8mb4"
        return self.database_url

    @property
    def is_sqlite(self) -> bool:
        return self.resolved_database_url.startswith("sqlite")

    @property
    def mysql_database_name(self) -> str:
        url = self.resolved_database_url
        if url.startswith("mysql"):
            return make_url(url).database or (self.mysql_database or "doudian")
        return self.mysql_database or "doudian"

    @property
    def chroma_is_remote(self) -> bool:
        # 配置 CHROMA_URL 时使用独立 Chroma 服务，否则使用本地持久化目录
        return bool(self.chroma_url)


@lru_cache
def get_settings() -> Settings:
    # 进程内缓存配置，避免每次读取环境变量
    return Settings()


settings = get_settings()
