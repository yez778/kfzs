"""按需下载 Chroma ONNX 嵌入模型（all-MiniLM-L6-v2）。

背景
----
该模型原本以 87MB 二进制直接提交在 `server/vendor/chroma-onnx/` 里，
把仓库撑到 93MB，克隆极慢，且触发 GitHub 大文件告警。现改为**运行时按需下载**：

- 默认启用；缓存目录与 chromadb 内核一致：
  `~/.cache/chroma/onnx_models/all-MiniLM-L6-v2/onnx`
- `CHROMA_DOWNLOAD_ONNX=0` 可彻底关闭下载（关闭后由哈希嵌入兜底）
- `CHROMA_ONNX_MODEL_URL=https://...` 可换镜像/内网地址
- 任何失败都不抛给调用方致命错误：上层捕获后回退哈希嵌入，服务保持可用

本模块只依赖标准库，便于在 Docker 构建阶段单独调用做预热。
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"
ARCHIVE_FILENAME = "onnx.tar.gz"
EXTRACTED_FOLDER_NAME = "onnx"
DEFAULT_MODEL_URL = (
    "https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz"
)
# 官方压缩包 SHA256（仅在使用默认源时校验；自定义镜像源跳过对比）
DEFAULT_MODEL_SHA256 = (
    "913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3"
)

# 解压后必须齐全的文件，少一个就视为模型不完整
REQUIRED_FILES = (
    "config.json",
    "model.onnx",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "tokenizer.json",
    "vocab.txt",
)


def model_root() -> Path:
    """模型缓存根目录（与 chromadb 默认 DOWNLOAD_PATH 保持一致）。"""
    return Path.home() / ".cache" / "chroma" / "onnx_models" / MODEL_NAME


def model_dir() -> Path:
    """解压后的模型目录（内含 model.onnx 等）。"""
    return model_root() / EXTRACTED_FOLDER_NAME


def is_model_ready() -> bool:
    """缓存里是否已有完整模型。"""
    target = model_dir()
    return all((target / name).is_file() for name in REQUIRED_FILES)


def download_enabled() -> bool:
    """是否允许自动下载：CHROMA_DOWNLOAD_ONNX 未显式关闭即视为启用。"""
    return os.getenv("CHROMA_DOWNLOAD_ONNX", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def model_url() -> str:
    """下载地址：优先环境变量（便于换镜像），否则用 chromadb 官方源。"""
    return (os.getenv("CHROMA_ONNX_MODEL_URL") or "").strip() or DEFAULT_MODEL_URL


def _safe_extract(archive_path: Path, target_dir: Path) -> None:
    """解压 tar.gz 到目标目录，并拒绝绝对路径与 ../ 穿越条目。

    官方压缩包内部自带 `onnx/` 目录，因此目标目录应为 model_root()，
    解压后自然得到 model_root()/onnx/。
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    base = target_dir.resolve()
    with tarfile.open(archive_path, mode="r:gz") as tar:
        for member in tar.getmembers():
            member_path = (target_dir / member.name).resolve()
            if not str(member_path).startswith(str(base)):
                raise RuntimeError(f"压缩包含非法路径，已拒绝解压：{member.name}")
        tar.extractall(target_dir)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fetch(url: str, dest: Path, *, timeout: int, retries: int = 3) -> None:
    """带进度日志与重试的下载。"""
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            logger.info(
                "正在下载 ONNX 嵌入模型（第 %s/%s 次）：%s", attempt, retries, url
            )
            request = urllib.request.Request(
                url, headers={"User-Agent": "xingtu-server/model-downloader"}
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                total = int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                next_report = 10 * 1024 * 1024  # 每 10MB 打一条进度
                with open(dest, "wb") as handle:
                    while True:
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if downloaded >= next_report:
                            if total:
                                logger.info(
                                    "模型下载进度 %.1f%%（%s / %s）",
                                    downloaded * 100 / total,
                                    _human(downloaded),
                                    _human(total),
                                )
                            else:
                                logger.info("模型下载进度 %s", _human(downloaded))
                            next_report += 10 * 1024 * 1024
                if total and downloaded != total:
                    raise IOError(f"下载不完整：期望 {total} 字节，实际 {downloaded}")
            logger.info("模型下载完成：%s", _human(dest.stat().st_size))
            return
        except Exception as exc:  # 网络抖动、超时、连接重置都走重试
            last_error = exc
            logger.warning("模型下载失败（第 %s 次）：%s", attempt, exc)
            if attempt < retries:
                time.sleep(min(2 * attempt, 6))
    raise RuntimeError(f"模型下载失败（已重试 {retries} 次）：{last_error}")


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}GB"


def ensure_model(*, timeout: int = 60, force: bool = False) -> bool:
    """确保模型就位。

    返回值：True 表示模型可用（原本就有或刚下载成功）；False 表示不可用
    （下载被禁用或失败）。**不抛异常**，便于启动阶段安全调用。
    """
    if not force and is_model_ready():
        return True
    if not download_enabled():
        logger.info(
            "ONNX 模型未缓存且已禁用下载（CHROMA_DOWNLOAD_ONNX=0），将使用哈希嵌入兜底"
        )
        return False

    target = model_dir()
    tmp_dir = Path(tempfile.mkdtemp(prefix="onnx-model-"))
    archive = tmp_dir / ARCHIVE_FILENAME
    try:
        url = model_url()
        _fetch(url, archive, timeout=timeout)
        if url == DEFAULT_MODEL_URL:
            actual = _sha256(archive)
            if actual != DEFAULT_MODEL_SHA256:
                raise RuntimeError(
                    f"压缩包校验失败：期望 {DEFAULT_MODEL_SHA256[:12]}…，实际 {actual[:12]}…"
                )
        root = model_root()
        logger.info("正在解压模型到 %s", target)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        _safe_extract(archive, root)
        if not is_model_ready():
            missing = [n for n in REQUIRED_FILES if not (target / n).is_file()]
            raise RuntimeError(f"解压后模型不完整，缺少：{missing}")
        logger.info("ONNX 嵌入模型已就绪：%s", target)
        return True
    except Exception as exc:
        logger.warning("ONNX 模型准备失败，回退哈希嵌入：%s", exc)
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":  # 支持：python -m app.rag.model_download 手动预热
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(0 if ensure_model() else 1)
