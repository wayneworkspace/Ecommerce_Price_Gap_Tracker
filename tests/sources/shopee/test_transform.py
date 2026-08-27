"""Test cho transform.py — hàm thuần: đọc 1 file JSON có sẵn rồi map field.

Không cần browser, không chạm mạng, chạy trong vài mili-giây.
"""

import json
from pathlib import Path

from price_tracker.sources.shopee.transform import build_record


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
