"""Test cho extract.py — chỉ phần bóc JSON và lưu bằng chứng debug.

Hai hàm này được tách ra khỏi fetch_raw() chính là để test được mà không cần
mở browser: chúng chỉ nhận vào object có .json() / .screenshot(), nên đưa
object giả vào là đủ. Bản thân fetch_raw() không test ở đây vì nó bắt buộc
phải mở Chrome thật bằng session thật.
"""

import json

import pytest
from patchright.sync_api import Error as PWError, TimeoutError as PWTimeout

from price_tracker.sources.shopee.extract import (
    FetchFailedError,
    extract_json_or_fail,
    dump_debug_evidence,
    validate_payload_or_fail,
    fetch_raw,
)


FAKE_URL = "https://shopee.vn/api/v4/pdp/get_pc?item_id=6765591429"


class _FakeResponse:
    """Object giả thay cho patchright Response — chỉ cần có .url và .json()."""

    def __init__(self, payload=None, raises: Exception | None = None):
        self.url = FAKE_URL
        self._payload = payload
        self._raises = raises

    def json(self):
        if self._raises is not None:
            raise self._raises
        return self._payload


def test_extract_json_returns_payload_when_body_is_valid_json():
    response = _FakeResponse(payload={"data": {"item": {"item_id": 1}}})

    assert extract_json_or_fail(response) == {"data": {"item": {"item_id": 1}}}


def test_extract_json_converts_patchright_error_to_fetch_failed():
    """Ca thật hay gặp nhất: session hết hạn -> Shopee 302 sang tường login,
    patchright ném Error('Response body is unavailable for redirect responses').

    Đây KHÔNG phải JSONDecodeError. Nếu không convert, nó thoát ra khỏi cả
    khối except lẫn bộ lọc của tenacity -> không retry, browser không đóng."""
    response = _FakeResponse(
        raises=PWError("Response body is unavailable for redirect responses"))

    with pytest.raises(FetchFailedError):
        extract_json_or_fail(response)


def test_extract_json_converts_json_decode_error_to_fetch_failed():
    response = _FakeResponse(raises=json.JSONDecodeError("Expecting value", "", 0))

    with pytest.raises(FetchFailedError):
        extract_json_or_fail(response)


def test_extract_json_converts_unicode_decode_error_to_fetch_failed():
    """Body không phải UTF-8 -> .decode() ném UnicodeDecodeError, cũng không
    phải JSONDecodeError."""
    response = _FakeResponse(
        raises=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"))

    with pytest.raises(FetchFailedError):
        extract_json_or_fail(response)


def test_extract_json_keeps_original_exception_as_cause():
    """Convert nhưng không được nuốt nguyên nhân gốc, nếu không thì lúc đọc
    log chỉ thấy 'fetch failed' mà không biết vì sao."""
    original = PWError("No resource with given identifier found")
    response = _FakeResponse(raises=original)

    with pytest.raises(FetchFailedError) as excinfo:
        extract_json_or_fail(response)

    assert excinfo.value.__cause__ is original


class _ExplodingPage:
    """Page giả mà mọi thao tác đều ném — mô phỏng lúc target đã crash/đóng,
    đúng lúc ta cần chụp bằng chứng nhất."""

    def screenshot(self, **kwargs):
        raise PWTimeout("Timeout 30000ms exceeded taking screenshot")

    def content(self):
        raise PWError("Target page, context or browser has been closed")


def test_dump_debug_evidence_never_raises(tmp_path):
    """Khối chụp bằng chứng không được phép ném ra ngoài: nếu nó ném, nó sẽ
    thay mất exception chẩn đoán gốc và làm browser.close() không chạy."""
    dump_debug_evidence(_ExplodingPage(), debug_dir=tmp_path)  # không được ném


def test_fetch_raw_retry_covers_the_exceptions_it_actually_raises():
    """Chốt lại phần đấu dây: loại exception fetch_raw ném ra phải nằm đúng
    trong danh sách tenacity chịu retry, nếu không thì retry chỉ là trang trí."""
    retry_config = fetch_raw.retry

    assert retry_config.stop.max_attempt_number == 3
    assert FetchFailedError in retry_config.retry.exception_types
    assert PWError in retry_config.retry.exception_types


def test_validate_payload_or_fail_passes_a_healthy_payload():
    payload = {"error": None, "data": {"item": {"item_id": 6765591429}}}

    assert validate_payload_or_fail(payload) == {"item_id": 6765591429}


def test_validate_payload_or_fail_rejects_shopee_error_payload():
    """Lớp 1 của C1: chặn TRƯỚC khi ghi ra data/raw/.

    Phải là FetchFailedError để tenacity retry — đây đúng là ca đáng retry
    nhất (bị chặn/throttle tạm thời), mà bản cũ lại coi là thành công."""
    payload = {"error": 1, "error_msg": "server busy", "data": None}

    with pytest.raises(FetchFailedError) as excinfo:
        validate_payload_or_fail(payload)

    msg = str(excinfo.value)
    assert "1" in msg and "server busy" in msg, \
        "Phải kèm error/error_msg thật của Shopee, đừng nuốt mất manh mối"
