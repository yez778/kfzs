FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/app ./app

# 构建阶段预下载 ONNX 嵌入模型（约 87MB）到 /root/.cache，避免首次启动等待；
# 构建环境无外网时删掉此行也可，容器启动时会自动重试下载
RUN python -m app.rag.model_download || echo "ONNX 模型预下载失败，将在运行时重试"

EXPOSE 8000

CMD ["python", "-m", "app.run"]
