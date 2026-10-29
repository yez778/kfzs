# 本地开发启动脚本：注入默认环境变量后启动 server（生产请用环境变量/密钥管理）
# 用法：cd server && python run_dev.py
import os

import uvicorn

# 本地联调默认值：AI 客服转发地址 + 内部服务令牌（与 agent/.env 的 SERVICE_TOKEN 保持一致）
os.environ.setdefault("AGENT_SERVICE_URL", "http://127.0.0.1:8100")
os.environ.setdefault("SERVICE_TOKEN", "dev-internal-token")

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
