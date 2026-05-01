import time
import logging
import functools
from src.config import (
    RETRY_MAX_ATTEMPTS,
    RETRY_INITIAL_DELAY_SEC,
    RETRY_MAX_DELAY_SEC,
    RETRY_BACKOFF_FACTOR,
)

logger = logging.getLogger(__name__)


def retry_with_backoff(
    max_attempts: int = RETRY_MAX_ATTEMPTS,
    initial_delay: float = RETRY_INITIAL_DELAY_SEC,
    max_delay: float = RETRY_MAX_DELAY_SEC,
    backoff_factor: float = RETRY_BACKOFF_FACTOR,
    exceptions: tuple = (Exception,),
):
    """指数バックオフ付きリトライデコレータ。負荷を与えすぎないよう待機時間を設ける。"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    result = func(*args, **kwargs)
                    if attempt > 1:
                        logger.info(f"[{func.__name__}] 試行 {attempt} で成功しました")
                    return result
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        logger.error(
                            f"[{func.__name__}] {max_attempts} 回試行しましたが失敗しました: {e}"
                        )
                        raise
                    wait = min(delay * (backoff_factor ** (attempt - 1)), max_delay)
                    logger.warning(
                        f"[{func.__name__}] 試行 {attempt}/{max_attempts} 失敗: {e}"
                        f" → {wait:.1f}秒後にリトライします"
                    )
                    time.sleep(wait)
            raise last_exception
        return wrapper
    return decorator
