"""Test cho config.py — phần đọc danh sách SKU và listing.

Mọi test ở đây trỏ SKUS_FILE vào file YAML tạm của riêng nó. Cố ý KHÔNG đọc
config/skus.yaml thật: file thật chỉ chứa listing có link sản phẩm có thật, còn
muốn nhiều SKU/listing để test thì bịa trong tmp_path. Bịa vào file thật là trỏ
pipeline vào sản phẩm không tồn tại và test sẽ xanh giả.
"""

import pytest
import yaml

from price_tracker import config as config_module

# Khuôn giống config/skus.yaml thật: mỗi nguồn là một DANH SÁCH listing, vì
# cùng một sản phẩm được nhiều người bán rao, mỗi người một item_id.
TWO_SKUS = [
    {"sku": "SKU-A", "name": "Sản phẩm A", "reference_price": 489000,
     "sources": {"shopee": [
         {"shop_id": "11", "item_id": "111", "is_official": True,
          "listing_title": "A chính hãng", "url": "https://shopee.vn/a1"},
         {"shop_id": "12", "item_id": "112", "is_official": False,
          "listing_title": "A shop khác", "url": "https://shopee.vn/a2"},
     ]}},
    {"sku": "SKU-B", "name": "Sản phẩm B", "reference_price": 199000,
     "sources": {"shopee": [
         {"shop_id": "22", "item_id": "222", "is_official": True,
          "listing_title": "B", "url": "https://shopee.vn/b"}],
         "tiktok": [
         {"shop_id": "99", "item_id": "999", "is_official": False,
          "listing_title": "B trên tiktok", "url": "https://tiktok.com/b"}]}},
]


def _use_skus(monkeypatch, tmp_path, entries):
    f = tmp_path / "skus.yaml"
    f.write_text(yaml.safe_dump(entries, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(config_module, "SKUS_FILE", f)
    return f


def test_load_source_listings_returns_one_entry_per_listing(monkeypatch, tmp_path):
    """Lặp theo LISTING chứ không theo SKU: SKU-A có 2 người bán nên phải ra 2
    dòng, vì mỗi listing là một request thật tới sàn."""
    _use_skus(monkeypatch, tmp_path, TWO_SKUS)

    got = config_module.load_source_listings("shopee")

    assert [g["item_id"] for g in got] == ["111", "112", "222"]


def test_load_source_listings_carries_the_sku_down_to_every_listing(monkeypatch, tmp_path):
    """`sku` phải đi kèm từng listing — nó là khoá join tới reference_price.

    Hai listing của SKU-A có item_id khác nhau nhưng cùng một SKU logic; thiếu
    cột này thì mart layer không nối được về giá niêm yết và price_gap_pct
    không tồn tại."""
    _use_skus(monkeypatch, tmp_path, TWO_SKUS)

    got = config_module.load_source_listings("shopee")

    assert [g["sku"] for g in got] == ["SKU-A", "SKU-A", "SKU-B"]
    assert got[0]["reference_price"] == 489000
    assert got[1]["reference_price"] == 489000, "Hai listing chung một giá niêm yết"
    assert got[0]["is_official"] is True
    assert got[1]["is_official"] is False


def test_load_source_listings_picks_the_right_source(monkeypatch, tmp_path):
    _use_skus(monkeypatch, tmp_path, TWO_SKUS)

    got = config_module.load_source_listings("tiktok")

    assert [g["sku"] for g in got] == ["SKU-B"]
    assert got[0]["item_id"] == "999"


def test_load_source_listings_skips_a_sku_without_that_source(monkeypatch, tmp_path, caplog):
    """Thêm TikTok cho 1 SKU không có nghĩa các SKU còn lại phải dừng cào Shopee."""
    _use_skus(monkeypatch, tmp_path, TWO_SKUS)

    got = config_module.load_source_listings("tiktok")

    assert len(got) == 1
    assert "SKU-A" in caplog.text, "Bỏ qua thì phải nói, không thì im lặng mất SKU"


def test_load_source_listings_raises_when_nothing_declares_that_source(monkeypatch, tmp_path):
    """Không SKU nào khai báo nguồn = lỗi cấu hình, phải vỡ ngay chứ không trả
    list rỗng rồi để crawler chạy một mẻ trống và báo thành công."""
    _use_skus(monkeypatch, tmp_path, TWO_SKUS)

    with pytest.raises(ValueError) as excinfo:
        config_module.load_source_listings("lazada")

    assert "lazada" in str(excinfo.value)


def test_get_listings_returns_every_seller_of_one_sku(monkeypatch, tmp_path):
    _use_skus(monkeypatch, tmp_path, TWO_SKUS)

    got = config_module.get_listings("SKU-A", "shopee")

    assert [g["item_id"] for g in got] == ["111", "112"]


def test_get_listings_raises_for_an_unknown_sku(monkeypatch, tmp_path):
    _use_skus(monkeypatch, tmp_path, TWO_SKUS)

    with pytest.raises(KeyError):
        config_module.get_listings("KHONG-CO", "shopee")


# ---------------------------------------------------------------------------
# Chặn lỗi gõ nhầm YAML — cấu hình sai phải chỉ đúng chỗ sai.
# ---------------------------------------------------------------------------

def test_load_skus_rejects_a_mapping_instead_of_a_list(monkeypatch, tmp_path):
    """Viết YAML thành mapping thay vì list là lỗi rất dễ mắc. Không chặn thì
    vòng lặp đi qua các key kiểu chuỗi rồi nổ AttributeError: 'str' object has
    no attribute 'get' — chẳng nói được file cấu hình sai ở đâu."""
    f = tmp_path / "skus.yaml"
    f.write_text("sku: SKU-A\nname: nham roi\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "SKUS_FILE", f)

    with pytest.raises(ValueError) as excinfo:
        config_module.load_skus()

    assert "DANH SÁCH" in str(excinfo.value)


def test_load_source_listings_rejects_a_single_listing_written_as_a_dict(monkeypatch, tmp_path):
    """Khuôn cũ (mỗi nguồn một dict) giờ là sai — phải báo rõ chứ không im lặng."""
    _use_skus(monkeypatch, tmp_path, [
        {"sku": "SKU-A", "sources": {"shopee": {"item_id": "111",
                                                "url": "https://shopee.vn/a"}}}])

    with pytest.raises(ValueError) as excinfo:
        config_module.load_source_listings("shopee")

    assert "danh sách listing" in str(excinfo.value)


def test_load_source_listings_does_not_kill_the_batch_over_one_bad_listing(monkeypatch, tmp_path):
    """Thiếu item_id/url KHÔNG được ném ở tầng đọc cấu hình.

    load_source_listings() chạy trước khi browser kịp mở, nên ném ở đây là quên
    một dòng `url:` làm chết cả mẻ — kể cả những listing đã chạy tốt hàng tuần.
    Việc kiểm field chuyển xuống fetch_one_listing() để lỗi chỉ giết đúng
    listing của nó (xem test bên test_extract.py)."""
    _use_skus(monkeypatch, tmp_path, [
        {"sku": "SKU-A", "sources": {"shopee": [
            {"shop_id": "11"},
            {"shop_id": "12", "item_id": "112", "is_official": False,
             "url": "https://shopee.vn/a2"}]}}])

    got = config_module.load_source_listings("shopee")

    assert len(got) == 2, "Listing hỏng vẫn đi qua, để tầng dưới báo lỗi riêng nó"


def test_load_source_listings_defaults_is_official_to_false_and_says_so(monkeypatch, tmp_path):
    """Quên `is_official: true` cho cửa hàng chính hãng sẽ đảo ngược câu hỏi
    kinh doanh — mọi filter `WHERE is_official` coi NULL là không chính hãng.
    Mặc định False được, nhưng phải kêu lên."""
    _use_skus(monkeypatch, tmp_path, [
        {"sku": "SKU-A", "sources": {"shopee": [
            {"shop_id": "11", "item_id": "111", "url": "https://shopee.vn/a"}]}}])

    got = config_module.load_source_listings("shopee")

    assert got[0]["is_official"] is False


def test_load_source_listings_warns_about_duplicate_listings(monkeypatch, tmp_path, caplog):
    """Thêm người bán bằng cách copy-paste rồi quên sửa item_id là lỗi dễ mắc
    với khuôn YAML này: cào lặp một trang, và failures (dict khoá theo nhãn)
    gộp hai listing thành một dòng nên đếm sai kích thước mẻ."""
    _use_skus(monkeypatch, tmp_path, [
        {"sku": "SKU-A", "sources": {"shopee": [
            {"shop_id": "11", "item_id": "111", "is_official": True,
             "url": "https://shopee.vn/a"},
            {"shop_id": "11", "item_id": "111", "is_official": True,
             "url": "https://shopee.vn/a"}]}}])

    config_module.load_source_listings("shopee")

    assert "nhiều lần" in caplog.text


def test_listing_label_names_both_the_sku_and_the_listing():
    """Chỉ ghi sku thì hai listing cùng SKU không phân biệt được cái nào hỏng;
    chỉ ghi item_id thì đọc log không biết là sản phẩm gì."""
    label = config_module.listing_label({"sku": "SKU-A", "item_id": "111"})

    assert "SKU-A" in label and "111" in label


# ---------------------------------------------------------------------------
# Chốt chặn cho file THẬT.
# ---------------------------------------------------------------------------

def test_the_real_skus_file_is_readable_and_declares_shopee():
    """Chỉ kiểm file thật parse được và mọi listing có đủ field code cần.

    Không assert số lượng hay item_id cụ thể — người dùng sẽ tự thêm listing,
    và một test đếm số listing sẽ đỏ mỗi lần họ thêm link mới, dạy người ta
    thói quen bỏ qua test đỏ."""
    got = config_module.load_source_listings("shopee")

    assert len(got) >= 1
    for entry in got:
        assert entry["item_id"] and entry["url"]
        assert entry["sku"], "Thiếu sku là mất khoá join tới reference_price"


def test_the_real_skus_file_urls_match_their_shop_and_item_id():
    """URL Shopee kết thúc bằng .<shop_id>.<item_id> — lệch là cấu hình đã gõ
    nhầm, và crawler sẽ lặng lẽ cào nhầm trang."""
    for entry in config_module.load_source_listings("shopee"):
        shop_id = entry.get("shop_id")
        assert shop_id, f"Listing {entry['item_id']} thiếu shop_id trong skus.yaml"
        assert entry["url"].endswith(f".{shop_id}.{entry['item_id']}"), \
            f"URL không khớp shop_id/item_id: {entry['url']}"
