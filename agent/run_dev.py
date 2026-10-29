# 本地开发启动脚本：注入默认环境变量后启动 agent（AI 客服）
# 用法：cd agent && python run_dev.py
import os

import uvicorn

# 本地联调默认值：server 内部接口地址 + 服务令牌（与 server 的 SERVICE_TOKEN 保持一致）
os.environ.setdefault("SERVER_API_BASE", "http://127.0.0.1:8000/api/v1")
os.environ.setdefault("SERVICE_TOKEN", "dev-internal-token")

if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8100, reload=False)
