import json
from price_tracker.sources.shopee.extract import fetch_raw
from price_tracker.sources.shopee.transform import build_record, save_record


def main():
    # fetch_raw() chỉ có đúng 1 lệnh return: hoặc trả Path, hoặc ném
    # FetchFailedError sau khi tenacity đã thử hết. Không bao giờ trả None,
    # nên nhánh kiểm tra None trước đây là code chết.
    raw_path = fetch_raw()

    record = build_record(raw_path)
    save_record(record)

    print("=== Kết quả cuối cùng ===")
    print(json.dumps(record, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
