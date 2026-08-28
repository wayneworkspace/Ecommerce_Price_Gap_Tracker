"""Entry point: scrape every configured listing, then build one record each."""
import json
import logging

from price_tracker.config import load_source_listings, listing_label
from price_tracker.sources.shopee.extract import (
    fetch_all_listings, BatchIncompleteError)
from price_tracker.sources.shopee.transform import build_record, save_record

logger = logging.getLogger(__name__)


def run_batch(listing_configs: list[dict] | None = None) -> tuple[list[dict], dict[str, str]]:
    """Scrape and package a batch; return records plus per-listing failures.

    Cào rồi đóng gói cả mẻ. Trả về (record lấy được, lỗi theo từng listing).

    Không ném ở đây mà trả cả hai phần về cho hàm gọi: main() còn phải in tóm
    tắt trước khi báo đỏ. Ném thẳng thì đúng lúc mẻ hỏng — lúc cần nhìn nhất —
    lại chẳng in được gì.

    Lỗi ở khâu đóng gói gom chung vào failures với lỗi ở khâu cào, và dùng
    CÙNG một nhãn listing_label(). Đứng từ góc nhìn "hôm nay listing này có dữ
    liệu không" thì hai loại đó như nhau; mà nếu hai khâu đặt tên khác nhau
    cho cùng một listing (một bên "SKU/item_id", một bên tên file raw) thì về
    sau không đối chiếu hay cảnh báo theo listing được nữa.
    """
    if listing_configs is None:
        listing_configs = load_source_listings("shopee")

    failures: dict[str, str] = {}
    try:
        fetched = fetch_all_listings(listing_configs)
    except BatchIncompleteError as exc:
        # Mẻ đã chạy hết danh sách, chỉ là thiếu vài listing. Lấy phần đã cào
        # được ra dùng tiếp thay vì bỏ cả mẻ.
        fetched = exc.succeeded
        failures.update(exc.failures)

    records: list[dict] = []
    for raw_path, listing_cfg in fetched:
        label = listing_label(listing_cfg)
        try:
            record = build_record(raw_path, listing_cfg)
            save_record(record)
            records.append(record)
        except Exception as exc:
            failures[label] = f"{type(exc).__name__}: {exc}"
            logger.warning("Không đóng gói được %s (%s): %s",
                           label, raw_path.name, exc)

    return records, failures


def main():
    """Run one batch, print a summary, exit red if any listing failed."""
    listing_configs = load_source_listings("shopee")
    records, failures = run_batch(listing_configs)

    print("=== Tóm tắt mẻ cào ===")
    print(f"Tổng listing cấu hình : {len(listing_configs)}")
    print(f"Thành công            : {len(records)}")
    print(f"Hỏng                  : {len(failures)}")

    for record in records:
        official = "chính hãng" if record.get("is_official") else "seller khác"
        print(f"  OK   {record['sku']}/{record['item_id']} ({official}) "
              f"— {record['price']} — {record['scraped_at']}")
    for label, why in failures.items():
        print(f"  FAIL {label} — {why}")

    if records:
        print("=== Record cuối cùng ===")
        print(json.dumps(records[-1], indent=2, ensure_ascii=False))

    # Đã in xong mới báo đỏ. Ném để Airflow đánh dấu task fail: một mẻ thiếu
    # listing mà báo xanh thì lỗ hổng dữ liệu chỉ lộ ra ở dashboard, hàng tuần
    # sau.
    #
    # Truyền `records` chứ không phải list rỗng: BatchIncompleteError lấy
    # len(succeeded) + len(failures) làm mẫu số, nên truyền rỗng sẽ in "1/1
    # listing hỏng" trong khi thực tế là 1/5 — đọc log tưởng sập cả mẻ.
    if failures:
        raise BatchIncompleteError(records, failures)


if __name__ == "__main__":
    main()
