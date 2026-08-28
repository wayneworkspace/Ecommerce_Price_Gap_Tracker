"""Shared retry policy: three attempts, exponential backoff."""
import logging

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)


def shopee_scrape_retry(*retryable_exceptions):
    """Build a retry decorator for the exception types a caller cares about.

    Decorator factory: mỗi hàm gọi hàm này và truyền vào những loại
    exception nào của RIÊNG nó cần retry (vì mỗi hàm có thể fail vì lý
    do khác nhau), còn cấu hình chung (thử mấy lần, chờ bao lâu) thì
    dùng lại y hệt — không phải chép code tenacity nhiều lần.

    Cách dùng:
        @shopee_scrape_retry(PWError, FetchFailedError)
        def fetch_one_listing(browser, listing_cfg):
            ...
    """
    if not retryable_exceptions:
        # tenacity nhận retry_if_exception_type(()) mà không phàn nàn: decorator
        # trông như đã gắn nhưng không bao giờ retry cái gì. Gãy to và sớm ở đây
        # còn hơn để lộ ra lúc production đang cần retry nhất.
        raise TypeError(
            "shopee_scrape_retry() cần ít nhất 1 loại exception để retry, "
            "ví dụ @shopee_scrape_retry(PWError, FetchFailedError)."
        )

    return retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=3, max=30),
        retry=retry_if_exception_type(retryable_exceptions),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
