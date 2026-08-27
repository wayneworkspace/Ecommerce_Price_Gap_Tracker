import json
import logging
from datetime import datetime
from pathlib import Path

from price_tracker.config import RAW_DIR, STAGING_DIR
from price_tracker.sources.shopee.payload import (
    find_item_in_raw,
    describe_raw_problem,
    find_scraped_at,
    scraped_at_from_filename,
    format_timestamp,
)

logger = logging.getLogger(__name__)

# Shopee trả giá dưới dạng số nguyên đã nhân sẵn 100_000 (48_900_000_000 -> 489_000 VND).
# Đặt tên hằng số thay vì rải số 100_000 trong code: sai hệ số này là hỏng toàn bộ
# mart layer mà không có gì báo động, nên phải để nó ở một chỗ duy nhất, dễ soi.
SHOPEE_PRICE_SCALE = 100_000


def find_latest_raw_file() -> Path:
    """Trả file raw mới nhất còn DÙNG ĐƯỢC — không phải file mới nhất.

    Khác biệt đó là cả vấn đề. Bản cũ lấy thẳng file mtime lớn nhất, nên chỉ cần
    một file hỏng lọt vào data/raw/ là nó vĩnh viễn là file được chọn, và mọi
    lần chạy transform sau đó đều vỡ ở cùng một chỗ. Hỏng một lần, hỏng mãi, mà
    cách sửa duy nhất là tự vào xoá file bằng tay — nếu đoán ra được nguyên nhân.

    Giờ duyệt từ mới về cũ và bỏ qua file không đọc được: chỉ cần còn một bản
    cào lành là pipeline chạy tiếp được. Mỗi file bị bỏ qua đều log warning kèm
    tên và lý do, để còn biết đường đi dọn.
    """
    files = sorted(RAW_DIR.glob("shopee_raw_*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(
            f"Không tìm thấy file raw nào trong {RAW_DIR} — chạy extract trước.")

    skipped: list[str] = []
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        # UnicodeDecodeError phải có mặt: read_text(encoding="utf-8") ném nó
        # TRƯỚC khi json.loads kịp chạy, và nó không phải OSError cũng không
        # phải JSONDecodeError. extract.py ghi ensure_ascii=False nên file đầy
        # ký tự nhiều byte — chỉ cần Ctrl-C hay đầy đĩa giữa lúc ghi là dính,
        # và thế là rơi lại đúng bẫy "hỏng một lần, hỏng mãi".
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
        else:
            if find_item_in_raw(raw) is not None:
                if skipped:
                    # Cảnh báo vẫn cần, nhưng hệ quả nay nhẹ hơn trước nhiều:
                    # resolve_scraped_at() đóng dấu đúng thời điểm CÀO, nên
                    # record sinh từ file cũ mang luôn ngày cũ. Nạp lên warehouse
                    # nó trùng khoá với bản đã có và bị merge đè, chứ không đội
                    # lốt một quan sát mới của hôm nay. Nói cách khác: hôm nay
                    # KHÔNG có điểm dữ liệu — và đó là sự thật cần thấy được,
                    # thay vì một đường giá phẳng trông như hàng không đổi giá.
                    logger.warning(
                        "Đã bỏ qua %d file raw hỏng, đang dùng bản cào CŨ HƠN: %s. "
                        "Record mang ngày cũ, nên hôm nay coi như KHÔNG cào được — "
                        "kiểm tra xem có đang bị chặn không.",
                        len(skipped), path.name)
                return path
            reason = describe_raw_problem(raw)

        skipped.append(path.name)
        logger.warning("Bỏ qua file raw hỏng %s — %s", path.name, reason)

    raise FileNotFoundError(
        f"Có {len(files)} file raw trong {RAW_DIR} nhưng không file nào dùng được. "
        f"Đã bỏ qua: {', '.join(skipped)}. Chạy lại extract để lấy bản mới."
    )


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


def resolve_scraped_at(raw, raw_path: Path) -> str:
    """Thời điểm CÀO của file raw này — không phải thời điểm chạy transform.

    Phân biệt hai mốc đó là cả vấn đề. find_latest_raw_file() có thể trả về một
    bản cào CŨ khi bản mới nhất hỏng; nếu chỗ này đóng dấu datetime.now() thì
    record sinh ra mang GIÁ CŨ với DẤU THỜI GIAN HÔM NAY. Chạy hằng ngày trong
    lúc Shopee chặn mình cả tuần, mart layer nhận về chuỗi giá phẳng lì trông y
    như thật — LAG() không thấy gì bất thường và không ai biết là dữ liệu giả.

    Kể cả ở ca bình thường thì đây mới là ngữ nghĩa đúng: scraped_at là lúc
    *cào*, không phải lúc *transform*. Hai lúc đó chỉ tình cờ gần nhau khi chạy
    main.py một mạch.

    Thứ tự ưu tiên: envelope trước (chính xác tới giây, do extract ghi), rồi
    mới tới tên file (cho file cào bằng bản code cũ). Không tìm được thì NÉM,
    tuyệt đối không lặng lẽ quay về now() — đó đúng là bug đang sửa.
    """
    embedded = find_scraped_at(raw)
    if embedded is not None:
        return embedded

    from_name = scraped_at_from_filename(raw_path.name)
    if from_name is not None:
        return from_name

    raise ValueError(
        f"File raw {raw_path.name} không suy ra được thời điểm cào: envelope "
        f"không có 'scraped_at' và tên file không chứa dấu thời gian dạng "
        f"20260827T055522Z. Không đoán bừa bằng giờ hiện tại vì như thế là đẻ "
        f"ra một dòng dữ liệu sai mà không ai phát hiện."
    )


def build_record(raw_path: Path) -> dict:
    raw = json.loads(raw_path.read_text(encoding="utf-8"))

    # Không index thẳng raw["data"]["data"]["item"] nữa: với file độc thì nó nổ
    # TypeError: 'NoneType' object is not subscriptable — đúng nhưng không nói
    # được file nào hỏng hay hỏng vì sao. Đi qua find_item() để lỗi chỉ thẳng
    # vào file cần xoá.
    item = find_item_in_raw(raw)
    if item is None:
        raise ValueError(
            f"File raw {raw_path.name} không dùng được — {describe_raw_problem(raw)}"
        )

    return {
        "sku_id": item.get("item_id"),
        "seller_id": item.get("shop_id"),
        "product_name": item.get("title"),
        "price": parse_price(item),
        "url": raw.get("url"),
        "scraped_at": resolve_scraped_at(raw, raw_path),
    }


def save_record(record: dict) -> Path:
    # Tên file lấy từ scraped_at của record, KHÔNG phải giờ chạy. Hai lý do:
    #
    # 1. Idempotent — chạy lại transform trên cùng một file raw ra cùng một tên
    #    file, ghi đè thay vì đẻ thêm bản sao. data/staging/ rồi sẽ được nạp lên
    #    warehouse; mỗi lần chạy lại đẻ một file mới là tự tạo dòng trùng ở tầng
    #    dưới, đúng thứ dbt incremental unique_key sinh ra để dẹp.
    # 2. Truy vết — record_<ts>.json khớp thẳng với raw_<ts>.json sinh ra nó,
    #    khỏi phải dò mtime để biết bản ghi này từ bản cào nào.
    ts = format_timestamp(datetime.fromisoformat(record["scraped_at"]))
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
