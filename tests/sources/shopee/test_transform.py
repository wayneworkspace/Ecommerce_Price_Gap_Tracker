"""Test cho transform.py — hàm thuần: đọc 1 file JSON có sẵn rồi map field.

Không cần browser, không chạm mạng, chạy trong vài mili-giây.
"""

import json
from datetime import datetime, timezone
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

    # Tên phải theo quy ước thật: build_record() suy thời điểm cào từ đây
    # khi envelope chưa có scraped_at (file cào bằng bản code cũ).
    raw_path = tmp_path / "shopee_raw_6765591429_20260820T035111Z.json"
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
# find_latest_raw_file — lớp phòng thủ thứ 2 của C1.
#
# Lớp 1 (validate trong extract.py) chặn không cho file độc ra đĩa. Lớp này lo
# ca file độc ĐÃ nằm sẵn ở đó — từ bản code cũ, hoặc do sửa tay. Không có nó
# thì một file hỏng làm transform vỡ vĩnh viễn, vì nó luôn là file mới nhất.
# ---------------------------------------------------------------------------

import os

import pytest

from price_tracker.sources.shopee import transform as transform_module

HEALTHY_ITEM = {"item_id": 6765591429, "shop_id": 52679373,
                "title": "Logitech G102", "price": RAW_PRICE_489K}


def _write_raw_file(dir_path, name: str, payload, mtime: float) -> Path:
    """Ghi 1 file raw đúng khuôn envelope extract.py tạo ra, với mtime chỉ định.

    Đặt mtime tay thay vì dựa vào thứ tự ghi, để test không phụ thuộc vào độ
    phân giải mtime của filesystem."""
    p = dir_path / name
    if isinstance(payload, str):
        p.write_text(payload, encoding="utf-8")          # rác, không phải JSON
    else:
        p.write_text(json.dumps({"data": payload, "url": "https://shopee.vn/x"},
                                ensure_ascii=False), encoding="utf-8")
    os.utime(p, (mtime, mtime))
    return p


def test_find_latest_raw_file_skips_a_poisoned_newest_file(tmp_path, monkeypatch, caplog):
    """File độc MỚI NHẤT không được phép chặn cả pipeline.

    Đây đúng là ca 'hỏng một lần, hỏng mãi': file độc luôn là file mtime lớn
    nhất nên bản cũ nhặt đúng nó cho mọi lần chạy về sau."""
    monkeypatch.setattr(transform_module, "RAW_DIR", tmp_path)

    _write_raw_file(tmp_path, "shopee_raw_1_old.json",
                    {"error": None, "data": {"item": HEALTHY_ITEM}}, mtime=1000)
    _write_raw_file(tmp_path, "shopee_raw_1_new.json",
                    {"error": 1, "error_msg": "server busy", "data": None}, mtime=2000)

    chosen = transform_module.find_latest_raw_file()

    assert chosen.name == "shopee_raw_1_old.json"
    # caplog.text la log da format san — kiem tren do thay vi tu ghep %-format
    assert "shopee_raw_1_new.json" in caplog.text  # phai log TEN file bi bo qua
    assert "server busy" in caplog.text  # va ca LY DO, khong thi biet hong ma khong biet vi sao


def test_find_latest_raw_file_skips_unparseable_json(tmp_path, monkeypatch):
    monkeypatch.setattr(transform_module, "RAW_DIR", tmp_path)

    _write_raw_file(tmp_path, "shopee_raw_1_old.json",
                    {"error": None, "data": {"item": HEALTHY_ITEM}}, mtime=1000)
    _write_raw_file(tmp_path, "shopee_raw_1_broken.json",
                    "{ day khong phai JSON", mtime=2000)

    assert transform_module.find_latest_raw_file().name == "shopee_raw_1_old.json"


def test_find_latest_raw_file_reports_how_many_it_skipped(tmp_path, monkeypatch):
    """Không còn file nào lành thì phải nói rõ đã bỏ qua bao nhiêu và vì sao —
    khác hẳn thông báo 'không tìm thấy file raw nào'."""
    monkeypatch.setattr(transform_module, "RAW_DIR", tmp_path)

    _write_raw_file(tmp_path, "shopee_raw_1_a.json",
                    {"error": 1, "error_msg": "blocked", "data": None}, mtime=1000)
    _write_raw_file(tmp_path, "shopee_raw_1_b.json", "rac", mtime=2000)

    with pytest.raises(FileNotFoundError) as excinfo:
        transform_module.find_latest_raw_file()

    msg = str(excinfo.value)
    assert "2" in msg
    assert "shopee_raw_1_a.json" in msg and "shopee_raw_1_b.json" in msg


def test_find_latest_raw_file_still_reports_an_empty_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(transform_module, "RAW_DIR", tmp_path)

    with pytest.raises(FileNotFoundError):
        transform_module.find_latest_raw_file()


def test_build_record_gives_a_clear_error_on_a_poisoned_file(tmp_path):
    """Trước đây chỗ này nổ TypeError: 'NoneType' object is not subscriptable —
    đúng nhưng chẳng nói được là file nào hỏng hay hỏng vì sao."""
    p = tmp_path / "poisoned.json"
    p.write_text(json.dumps({"data": {"error": 1, "error_msg": "blocked",
                                      "data": None}, "url": "x"}), encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        build_record(p)

    assert "poisoned.json" in str(excinfo.value)


def test_find_latest_raw_file_skips_a_file_with_broken_utf8(tmp_path, monkeypatch):
    """File bị cắt giữa chừng một ký tự tiếng Việt nhiều byte.

    read_text(encoding="utf-8") ném UnicodeDecodeError TRƯỚC khi json.loads
    kịp chạy, mà UnicodeDecodeError không phải OSError cũng không phải
    JSONDecodeError. Không bắt là rơi lại đúng bẫy "hỏng một lần, hỏng mãi"
    mà hàm này sinh ra để dẹp. Có thật: extract.py ghi ensure_ascii=False nên
    file đầy ký tự nhiều byte, chỉ cần Ctrl-C giữa lúc ghi là dính."""
    monkeypatch.setattr(transform_module, "RAW_DIR", tmp_path)

    _write_raw_file(tmp_path, "shopee_raw_1_old.json",
                    {"error": None, "data": {"item": HEALTHY_ITEM}}, mtime=1000)
    truncated = tmp_path / "shopee_raw_1_cut.json"
    body = json.dumps({"data": {"error": None, "data": {"item": {"title": "Chuột"}}}},
                      ensure_ascii=False).encode("utf-8")
    truncated.write_bytes(body[:-3] + b"\xe1\xba")   # cắt giữa ký tự nhiều byte
    os.utime(truncated, (2000, 2000))

    assert transform_module.find_latest_raw_file().name == "shopee_raw_1_old.json"


def test_find_latest_raw_file_accepts_an_old_bare_payload_file(tmp_path, monkeypatch):
    """File payload trần (bản code trước envelope) vẫn dùng được, đừng bỏ qua."""
    monkeypatch.setattr(transform_module, "RAW_DIR", tmp_path)

    bare = tmp_path / "shopee_raw_1_bare.json"
    bare.write_text(json.dumps({"bff_meta": {}, "error": None, "error_msg": None,
                                "data": {"item": HEALTHY_ITEM}}), encoding="utf-8")
    os.utime(bare, (2000, 2000))

    assert transform_module.find_latest_raw_file().name == "shopee_raw_1_bare.json"


def test_build_record_reads_an_old_bare_payload_file(tmp_path):
    p = tmp_path / "shopee_raw_6765591429_20260820T035111Z.json"
    p.write_text(json.dumps({"bff_meta": {}, "error": None, "error_msg": None,
                             "data": {"item": HEALTHY_ITEM}}), encoding="utf-8")

    record = build_record(p)

    assert record["sku_id"] == 6765591429
    assert record["price"] == VND_489K


# ---------------------------------------------------------------------------
# scraped_at phải là thời điểm CÀO, không phải thời điểm CHẠY transform.
#
# Vì sao quan trọng: find_latest_raw_file() có thể trả về một bản cào CŨ khi
# bản mới nhất hỏng. Nếu build_record() đóng dấu datetime.now(), record sinh ra
# mang GIÁ CŨ với DẤU THỜI GIAN HÔM NAY. Chạy hằng ngày trong lúc Shopee chặn
# mình cả tuần thì mart layer nhận về một chuỗi giá phẳng lì trông y như thật —
# LAG() không thấy gì bất thường, không ai biết là dữ liệu giả.
# ---------------------------------------------------------------------------

SCRAPED_AT_IN_FILE = "2026-08-20T03:51:11+00:00"


def _write_raw_named(tmp_path, name: str, *, scraped_at: str | None) -> Path:
    """File raw đúng khuôn envelope, tên đặt được, scraped_at bật/tắt được."""
    raw = {
        "data": {"data": {"item": {
            "item_id": 6765591429,
            "shop_id": 52679373,
            "title": "Chuột gaming Logitech G102",
            "price": RAW_PRICE_489K,
        }}},
        "url": "https://shopee.vn/product/52679373/6765591429",
    }
    if scraped_at is not None:
        raw["scraped_at"] = scraped_at

    path = tmp_path / name
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return path


def test_build_record_takes_scraped_at_from_the_envelope(tmp_path):
    raw_path = _write_raw_named(
        tmp_path, "shopee_raw_6765591429_20260820T035111Z.json",
        scraped_at=SCRAPED_AT_IN_FILE)

    record = build_record(raw_path)

    assert record["scraped_at"] == SCRAPED_AT_IN_FILE


def test_build_record_falls_back_to_the_filename_timestamp(tmp_path):
    """File cào bằng bản code cũ chưa có scraped_at trong envelope.

    data/raw/ đang có file thật thuộc loại này — coi chúng là hỏng thì tự vứt
    đi dữ liệu còn tốt, nên phải đọc được dấu thời gian từ tên file.
    """
    raw_path = _write_raw_named(
        tmp_path, "shopee_raw_6765591429_20260820T035111Z.json",
        scraped_at=None)

    record = build_record(raw_path)

    assert record["scraped_at"] == SCRAPED_AT_IN_FILE


def test_build_record_does_not_stamp_an_old_file_with_today(tmp_path):
    """Đây là bug gốc, phát biểu thẳng thành test."""
    raw_path = _write_raw_named(
        tmp_path, "shopee_raw_6765591429_20260820T035111Z.json",
        scraped_at=None)

    record = build_record(raw_path)
    today = datetime.now(timezone.utc).date().isoformat()

    assert not record["scraped_at"].startswith(today)
    assert record["scraped_at"].startswith("2026-08-20")


def test_build_record_refuses_a_file_with_no_derivable_scrape_time(tmp_path):
    """Không đoán được thời điểm cào thì KHÔNG được lặng lẽ dùng now().

    Lặng lẽ dùng now() chính là bug đang sửa. Thà vỡ to và sớm còn hơn đẻ ra
    một dòng dữ liệu sai mà không ai phát hiện.
    """
    raw_path = _write_raw_named(tmp_path, "khong_dung_quy_uoc.json",
                                scraped_at=None)

    with pytest.raises(ValueError, match="thời điểm cào"):
        build_record(raw_path)


def test_build_record_ignores_a_garbage_envelope_timestamp(tmp_path):
    """Rác trong envelope phải tụt xuống tên file, không đi thẳng vào record.

    Chỉ kiểm tra "là chuỗi khác rỗng" thì một giá trị rác vẫn lọt, và nó chảy
    tiếp xuống warehouse. Tên file thường vẫn nguyên khi envelope hỏng.
    """
    raw_path = _write_raw_named(
        tmp_path, "shopee_raw_6765591429_20260820T035111Z.json",
        scraped_at="hôm qua lúc nào đó")

    record = build_record(raw_path)

    assert record["scraped_at"] == SCRAPED_AT_IN_FILE


def test_build_record_normalises_a_z_suffix_timestamp(tmp_path):
    """Ghi kiểu 'Z' hay '+00:00' thì record vẫn ra một định dạng duy nhất."""
    raw_path = _write_raw_named(
        tmp_path, "shopee_raw_6765591429_20260820T035111Z.json",
        scraped_at="2026-08-20T03:51:11Z")

    record = build_record(raw_path)

    assert record["scraped_at"] == SCRAPED_AT_IN_FILE


def test_save_record_is_idempotent_for_the_same_scrape(tmp_path, monkeypatch):
    """Chạy lại transform trên cùng một bản cào không được đẻ thêm file.

    data/staging/ rồi sẽ được nạp lên warehouse. Mỗi lần chạy lại sinh một file
    mới là tự tạo dòng trùng ở tầng dưới — đúng thứ dbt incremental unique_key
    sinh ra để dẹp, nên đừng tạo ra nó ngay từ đầu.
    """
    monkeypatch.setattr(transform_module, "STAGING_DIR", tmp_path)
    raw_path = _write_raw_named(
        tmp_path, "shopee_raw_6765591429_20260820T035111Z.json",
        scraped_at=SCRAPED_AT_IN_FILE)

    record = build_record(raw_path)
    first = transform_module.save_record(record)
    second = transform_module.save_record(build_record(raw_path))

    assert first == second
    assert len(list(tmp_path.glob("shopee_record_*.json"))) == 1
    assert "20260820T035111Z" in first.name
