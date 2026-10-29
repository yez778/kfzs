# 支付定时任务：周期性关闭超时未支付订单并归还预占库存
import asyncio
import logging

from ..core.payment import sweep_expired_payments
from .celery_app import celery_app

logger = logging.getLogger(__name__)


async def _sweep() -> int:
    return await sweep_expired_payments()


@celery_app.task(name="tasks.sweep_expired_payments")
def sweep_expired_payments_task() -> int:
    # beat 每 2 分钟触发：把超过 expires_at 仍未支付的订单置 cancelled 并回补库存
    try:
        closed = asyncio.run(_sweep())
    except Exception:
        logger.exception("sweep expired payments failed")
        return 0
    if closed:
        logger.info("closed %d expired unpaid orders", closed)
    return closed
