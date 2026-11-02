# 本地开发启动脚本：启动 server（生产请用环境变量/密钥管理）
# 用法：cd server && python run_dev.py
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
