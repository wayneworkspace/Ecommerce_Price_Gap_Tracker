import json
from datetime import datetime, timezone
from pathlib import Path

from config import RAW_DIR, STAGING_DIR


def find_latest_raw_file() -> Path:
    files = sorted(RAW_DIR.glob("shopee_raw_*.json"),
                   key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(
            "Không tìm thấy file raw nào — chạy fetch_raw.py trước.")
    return files[-1]


def build_record(raw_path: Path) -> dict:
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    item = raw["data"]["data"]["item"]

    return {
        "sku_id": item.get("item_id"),
        "seller_id": item.get("shop_id"),
        "product_name": item.get("title"),
        "price": (item.get("price") or item.get("price_min") or 0) / 100_000,
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
