import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from price_tracker.config import RAW_DIR, STAGING_DIR

logger = logging.getLogger(__name__)

# Shopee trả giá dưới dạng số nguyên đã nhân sẵn 100_000 (48_900_000_000 -> 489_000 VND).
# Đặt tên hằng số thay vì rải số 100_000 trong code: sai hệ số này là hỏng toàn bộ
# mart layer mà không có gì báo động, nên phải để nó ở một chỗ duy nhất, dễ soi.
SHOPEE_PRICE_SCALE = 100_000


def find_latest_raw_file() -> Path:
    files = sorted(RAW_DIR.glob("shopee_raw_*.json"),
                   key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(
            "Không tìm thấy file raw nào — chạy fetch_raw.py trước.")
    return files[-1]


def parse_price(item: dict) -> float | None:
    """Lấy giá từ item, trả None nếu Shopee không trả giá nào.

    Dùng `is None` chứ KHÔNG dùng `or`: `item.get("price") or ...` coi giá 0
    là falsy nên nó tụt xuống nhánh fallback, làm ta mất khả năng phân biệt
    "hàng giá 0đ thật" với "Shopee không trả giá". Hai ca này phải xử lý
    khác nhau ở lớp dưới.

    Trả None thay vì 0.0 khi thiếu giá, vì 0.0 là bug thầm lặng: xuống mart
    layer nó trông y như một mức giá hợp lệ và đẻ ra price_change_pct = -100%.
    Cũng không raise, vì một SKU hỏng không đáng để giết cả run — theo đúng
    hướng "malformed price -> quarantine" đã ghi trong README.
    """
    raw_price = item.get("price")
    if raw_price is None:
        raw_price = item.get("price_min")

    # Chặn theo KIỂU chứ không chỉ chặn None: Shopee có field trả giá dạng chuỗi,
    # mà `"48900000000" / 100_000` ném TypeError thoát thẳng ra ngoài — đúng cái
    # "giết cả run vì một SKU" mà hàm này tự nhận là tránh. bool bị loại riêng vì
    # trong Python nó là subclass của int (True / 100_000 = 1e-05, im như thật).
    if isinstance(raw_price, bool) or not isinstance(raw_price, (int, float)):
        logger.warning(
            "SKU %s có giá không dùng được (price=%r, price_min=%r) — trả price=None để lớp dưới tách ra quarantine",
            item.get("item_id"), item.get("price"), item.get("price_min"),
        )
        return None

    return raw_price / SHOPEE_PRICE_SCALE


def build_record(raw_path: Path) -> dict:
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    item = raw["data"]["data"]["item"]

    return {
        "sku_id": item.get("item_id"),
        "seller_id": item.get("shop_id"),
        "product_name": item.get("title"),
        "price": parse_price(item),
        "url": raw.get("url"),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def save_record(record: dict) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = STAGING_DIR / f"shopee_record_{record['sku_id']}_{ts}.json"
    out_path.write_text(json.dumps(
        record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Đã lưu record: {out_path}")
    return out_path


if __name__ == "__main__":
    raw_path = find_latest_raw_file()
    record = build_record(raw_path)
    save_record(record)
    print(json.dumps(record, indent=2, ensure_ascii=False))
