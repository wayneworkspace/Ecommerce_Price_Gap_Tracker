import json
import logging
from datetime import datetime
from pathlib import Path

from price_tracker.config import (
    RAW_DIR, STAGING_DIR, load_source_listings, listing_label)
from price_tracker.sources.shopee.settings import RAW_FILE_PREFIX
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


def find_latest_raw_file(item_id: str) -> Path:
    """Trả file raw mới nhất còn DÙNG ĐƯỢC **của đúng SKU này**.

    item_id là tham số BẮT BUỘC, cố ý không cho mặc định. Bản trước glob
    "shopee_raw_*.json" tức vơ hết mọi SKU rồi trả về đúng một file mới nhất —
    với 1 SKU thì vô hại, nhưng từ SKU thứ 2 là N-1 SKU bị bỏ rơi IM LẶNG:
    transform chạy xong, không lỗi, chỉ là thiếu gần hết dữ liệu. Để item_id
    có giá trị mặc định là mời cái bug đó quay lại.

    Khác biệt đó là cả vấn đề. Bản cũ lấy thẳng file mtime lớn nhất, nên chỉ cần
    một file hỏng lọt vào data/raw/ là nó vĩnh viễn là file được chọn, và mọi
    lần chạy transform sau đó đều vỡ ở cùng một chỗ. Hỏng một lần, hỏng mãi, mà
    cách sửa duy nhất là tự vào xoá file bằng tay — nếu đoán ra được nguyên nhân.

    Giờ duyệt từ mới về cũ và bỏ qua file không đọc được: chỉ cần còn một bản
    cào lành là pipeline chạy tiếp được. Mỗi file bị bỏ qua đều log warning kèm
    tên và lý do, để còn biết đường đi dọn.
    """
    files = sorted(RAW_DIR.glob(f"{RAW_FILE_PREFIX}_{item_id}_*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(
            f"Không có file raw nào của item_id={item_id} trong {RAW_DIR} — "
            f"chạy extract trước.")

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
        f"Có {len(files)} file raw của item_id={item_id} trong {RAW_DIR} nhưng "
        f"không file nào dùng được. Đã bỏ qua: {', '.join(skipped)}. "
        f"Chạy lại extract để lấy bản mới."
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


def build_record(raw_path: Path, listing_cfg: dict) -> dict:
    """Ép file raw về schema chung, trộn thêm phần danh tính đến từ cấu hình.

    listing_cfg là tham số BẮT BUỘC, cố ý không cho mặc định. Record phải mang
    HAI TẦNG danh tính, và tầng trên chỉ có trong cấu hình:

      - `sku`      — SKU logic ("G102-LIGHTSYNC"). Đây là KHOÁ JOIN tới
                     reference_price ở mart layer. Nhiều người bán rao cùng một
                     sản phẩm, mỗi listing một item_id khác nhau; không có cột
                     này thì mart không có đường nào nối về giá niêm yết, tức
                     không tính được price_gap_pct — mất toàn bộ mục đích dự án.
      - `item_id`  — mã LISTING trên sàn. Tên cũ là `sku_id`, sai bản chất:
                     nó chưa bao giờ là SKU, chỉ là id của một tin đăng.
      - `source`   — tên sàn. item_id chỉ duy nhất TRONG một sàn, nên khoá tự
                     nhiên (sku, source, item_id, scraped_at) mà thiếu source
                     là mời đụng độ ngay khi TikTok đổ vào cùng staging dir.
      - `is_official` — cũng đến từ cấu hình, không có trong payload Shopee.
                     Thiếu nó thì mart không phân biệt nổi giá chính hãng với
                     giá của người bán khác, mà đó chính là câu hỏi cần trả lời.

    Cho listing_cfg một giá trị mặc định sẽ khiến chỗ gọi quên truyền mà vẫn
    chạy, đẻ ra record thiếu khoá join — hỏng im lặng tới tận mart layer.
    """
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
        # Tầng 1 — danh tính logic, đến từ config/skus.yaml
        "sku": listing_cfg.get("sku"),
        "is_official": listing_cfg.get("is_official"),
        "source": "shopee",
        # Tầng 2 — danh tính trên sàn.
        # item_id lấy từ CẤU HÌNH chứ không từ payload, dù payload cũng có.
        # Hai lý do: (1) payload thiếu field này thì record mang item_id=None
        # và save_record đặt tên file shopee_record_None_<ts>.json — hai listing
        # cào trong cùng một giây ghi đè nhau; (2) payload trả int còn skus.yaml
        # và find_latest_raw_file() dùng str, để lệch kiểu thì mọi phép join
        # sau này với bảng seed cấu hình phải cast mà không ai ghi lại là vì sao.
        # extract.fetch_one_listing() đã đối chiếu payload khớp cấu hình trước
        # khi ghi file, nên lấy từ cấu hình là an toàn.
        "item_id": listing_cfg.get("item_id"),
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
    out_path = STAGING_DIR / f"shopee_record_{record['item_id']}_{ts}.json"
    out_path.write_text(json.dumps(
        record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Đã lưu record: {out_path}")
    return out_path


if __name__ == "__main__":
    # Chạy transform độc lập trên bản cào mới nhất của TỪNG LISTING, không phải
    # trên đúng một file — nếu không thì chạy tay lại tái hiện đúng cái bug
    # "N-1 listing bị bỏ rơi" mà find_latest_raw_file(item_id) vừa dẹp.
    #
    # Mỗi listing một khối try riêng, cùng lý do như trong fetch_all_listings():
    # một listing chưa có file raw (hôm nay bị chặn) sẽ ném FileNotFoundError,
    # và nếu không cô lập thì nó giết luôn các listing phía sau vốn có file
    # hoàn toàn lành — đúng cái kiểu mất dữ liệu mà cả file này đang chống.
    _failures = {}
    for _listing in load_source_listings("shopee"):
        _label = listing_label(_listing)
        try:
            _record = build_record(
                find_latest_raw_file(str(_listing["item_id"])), _listing)
            save_record(_record)
            print(json.dumps(_record, indent=2, ensure_ascii=False))
        except Exception as _exc:
            _failures[_label] = f"{type(_exc).__name__}: {_exc}"
            logger.warning("Không đóng gói được %s: %s", _label, _exc)

    if _failures:
        raise SystemExit(
            "Có listing không đóng gói được: "
            + "; ".join(f"{k}: {v}" for k, v in _failures.items()))
