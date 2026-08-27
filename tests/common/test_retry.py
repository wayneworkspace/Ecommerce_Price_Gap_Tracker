"""Test cho common/retry.py."""

import pytest

from price_tracker.common.retry import shopee_scrape_retry


def test_shopee_scrape_retry_rejects_being_called_with_no_exceptions():
    """Gọi không tham số phải gãy TO và SỚM.

    tenacity nhận retry_if_exception_type(()) mà không phàn nàn, nên decorator
    trông như đã gắn nhưng không bao giờ retry cái gì. Hỏng âm thầm kiểu này
    chỉ lộ ra lúc production đang cần retry nhất."""
    with pytest.raises(TypeError):
        shopee_scrape_retry()
