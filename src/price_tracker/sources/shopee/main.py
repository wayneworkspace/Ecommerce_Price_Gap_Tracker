import json
import logging

from price_tracker.config import load_source_listings, listing_label
from price_tracker.sources.shopee.extract import (
    fetch_all_listings, BatchIncompleteError)
from price_tracker.sources.shopee.transform import build_record, save_record


logger = logging.getLogger(__name__)


def run_batch(listing_configs: list[dict] | None = None) -> tuple[list[dict], dict[str, str]]:

    # EXTRACT
    if listing_configs is None:
        listing_configs = load_source_listings("shopee")

    failures: dict[str, str] = {}
    try:
        fetched = fetch_all_listings(listing_configs)
    except BatchIncompleteError as exc:

        fetched = exc.succeeded
        failures.update(exc.failures)

    records: list[dict] = []
    for raw_path, listing_cfg in fetched:
        label = listing_label(listing_cfg)
        try:
            # TRANSFORM
            record = build_record(raw_path, listing_cfg)
# LOAD
            save_record(record)
            records.append(record)
        except Exception as exc:
            failures[label] = f"{type(exc).__name__}: {exc}"
            logger.warning("Không đóng gói được %s (%s): %s",
                           label, raw_path.name, exc)

    return records, failures


def main():
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

    if failures:
        raise BatchIncompleteError(records, failures)


if __name__ == "__main__":
    main()
