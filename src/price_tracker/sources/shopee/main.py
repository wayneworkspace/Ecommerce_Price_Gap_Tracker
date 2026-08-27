import json
from price_tracker.sources.shopee.extract import fetch_raw
from price_tracker.sources.shopee.transform import build_record, save_record


def main():
    raw_path = fetch_raw()
    if raw_path is None:
        print("Dừng lại — không có data để đóng gói.")
        return

    record = build_record(raw_path)
    save_record(record)

    print("=== Kết quả cuối cùng ===")
    print(json.dumps(record, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
