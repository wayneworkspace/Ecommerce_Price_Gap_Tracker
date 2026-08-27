"""
test_fetch_raw.py
------------------
Unit test bằng pytest cho build_record.py — hàm thuần (chỉ đọc 1 file
JSON có sẵn rồi map field), không cần mở browser/mạng thật, chạy trong
vài mili-giây.

Chạy (đứng trong thư mục shopee/):
    pytest test_case/test_fetch_raw.py -v
"""

import json
from pathlib import Path

from build_record import build_record

# Độ lớn thật Shopee trả về, lấy từ bằng chứng trong docs/Issue_Logs.md:
# 48_900_000_000 / 100_000 = 489_000 VND (đúng giá niêm yết con chuột G102).
# Dùng đúng thang này thay vì số nhỏ tự bịa, để test bắt được lỗi lệch hệ số.
RAW_PRICE_489K = 48_900_000_000
VND_489K = 489_000.0


def _write_fake_raw(tmp_path, item: dict, url: str | None = None) -> Path:
    """Tạo 1 file JSON giả, đúng cấu trúc raw thật Shopee trả về
    (raw['data']['data']['item']), để test build_record() mà không
    cần chạy fetch_raw.py cào thật."""
    fake_raw = {"data": {"data": {"item": item}}}
    if url is not None:
        fake_raw["url"] = url

    raw_path = tmp_path / "fake_raw.json"
    raw_path.write_text(json.dumps(
        fake_raw, ensure_ascii=False), encoding="utf-8")
    return raw_path


def test_build_record_maps_fields_correctly(tmp_path):
    raw_path = _write_fake_raw(
        tmp_path,
        item={
            "item_id": 6765591429,
            "shop_id": 52679373,
            "title": "Chuột gaming Logitech G102",
            "price": RAW_PRICE_489K,
            "price_min": RAW_PRICE_489K,
        },
        url="https://shopee.vn/product/52679373/6765591429",
    )

    record = build_record(raw_path)

    assert record["sku_id"] == 6765591429
    assert record["seller_id"] == 52679373
    assert record["product_name"] == "Chuột gaming Logitech G102"
    assert record["price"] == VND_489K
    assert record["url"] == "https://shopee.vn/product/52679373/6765591429"
    assert "scraped_at" in record  # có timestamp, không kiểm tra giá trị chính xác


def test_build_record_falls_back_to_price_min_when_price_is_none(tmp_path):
    raw_path = _write_fake_raw(
        tmp_path,
        item={
            "item_id": 1,
            "shop_id": 2,
            "title": "Sản phẩm test",
            "price": None,
            "price_min": RAW_PRICE_489K,
        },
    )

    record = build_record(raw_path)

    assert record["price"] == VND_489K


def test_build_record_returns_none_when_price_and_price_min_missing(tmp_path, caplog):
    """Thiếu giá thì phải trả None + log warning, KHÔNG được trả 0.0.

    0.0 là bug thầm lặng: xuống mart layer nó thành 'giá 0 đồng' và đẻ ra
    price_change_pct = -100% mà không ai biết là do thiếu data. None thì
    lớp quarantine (xem README) còn tách nó ra được."""
    raw_path = _write_fake_raw(
        tmp_path,
        item={
            "item_id": 1,
            "shop_id": 2,
            "title": "Sản phẩm hết cả price lẫn price_min",
            "price": None,
            "price_min": None,
        },
    )

    record = build_record(raw_path)

    assert record["price"] is None
    assert any(r.levelname == "WARNING" for r in caplog.records), \
        "Thiếu giá mà im lặng thì không ai biết để đi kiểm tra"


def test_build_record_returns_none_when_price_is_not_a_number(tmp_path, caplog):
    """Giá về dưới dạng chuỗi (Shopee có field trả string) không được giết cả run.

    parse_price tự nhận là "một SKU hỏng không đáng để giết cả run", nên nó
    phải giữ đúng lời hứa đó với mọi kiểu rác, chứ không chỉ với None —
    raw_price / 100_000 trên một str sẽ ném TypeError thoát thẳng ra ngoài."""
    raw_path = _write_fake_raw(
        tmp_path,
        item={
            "item_id": 1,
            "shop_id": 2,
            "title": "Sản phẩm giá trả về dạng chuỗi",
            "price": "48900000000",
            "price_min": None,
        },
    )

    record = build_record(raw_path)

    assert record["price"] is None
    assert any(r.levelname == "WARNING" for r in caplog.records)


def test_build_record_keeps_a_genuine_zero_price(tmp_path):
    """Giá 0 THẬT phải khác với giá THIẾU.

    Đây là lý do phải dùng `is None` chứ không dùng `or`: với `or` thì
    price=0 bị coi là falsy và tụt xuống nhánh fallback, làm mất luôn
    khả năng phân biệt hai ca hoàn toàn khác nhau này."""
    raw_path = _write_fake_raw(
        tmp_path,
        item={
            "item_id": 1,
            "shop_id": 2,
            "title": "Sản phẩm giá 0 thật (hàng tặng kèm)",
            "price": 0,
            "price_min": RAW_PRICE_489K,
        },
    )

    record = build_record(raw_path)

    assert record["price"] == 0.0
    assert record["price"] is not None


# ---------------------------------------------------------------------------
# fetch_raw.py — chỉ test phần bóc JSON và lưu bằng chứng debug.
# Hai hàm này được tách ra khỏi fetch_raw() chính là để test được mà không
# cần mở browser: chúng chỉ nhận vào object có .json() / .screenshot(), nên
# ta đưa object giả vào là đủ. Bản thân fetch_raw() thì không test ở đây vì
# nó bắt buộc phải mở Chrome thật bằng session thật.
# ---------------------------------------------------------------------------

import pytest
from patchright.sync_api import Error as PWError, TimeoutError as PWTimeout

from fetch_raw import (
    FetchFailedError,
    extract_json_or_fail,
    dump_debug_evidence,
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
