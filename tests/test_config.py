"""Tests for config.py -- reading the SKU list and its listings.

Every test here points SKUS_FILE at its own temporary YAML file. It
deliberately does NOT read the real config/skus.yaml: that file only holds
listings with real product links, and inventing extra SKUs/listings for a test
belongs in tmp_path. Inventing them in the real file would point the pipeline at
products that do not exist, and the tests would go green for the wrong reason.
"""

import pytest
import yaml

from price_tracker import config as config_module

# Same shape as the real config/skus.yaml: each source is a LIST of listings,
# because the same product is sold by several sellers, each with its own item_id.
TWO_SKUS = [
    {"sku": "SKU-A", "name": "Product A", "reference_price": 489000,
     "sources": {"shopee": [
         {"shop_id": "11", "item_id": "111", "is_official": True,
          "listing_title": "A official", "url": "https://shopee.vn/a1"},
         {"shop_id": "12", "item_id": "112", "is_official": False,
          "listing_title": "A other shop", "url": "https://shopee.vn/a2"},
     ]}},
    {"sku": "SKU-B", "name": "Product B", "reference_price": 199000,
     "sources": {"shopee": [
         {"shop_id": "22", "item_id": "222", "is_official": True,
          "listing_title": "B", "url": "https://shopee.vn/b"}],
         "tiktok": [
         {"shop_id": "99", "item_id": "999", "is_official": False,
          "listing_title": "B on tiktok", "url": "https://tiktok.com/b"}]}},
]


def _use_skus(monkeypatch, tmp_path, entries):
    f = tmp_path / "skus.yaml"
    f.write_text(yaml.safe_dump(entries, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(config_module, "SKUS_FILE", f)
    return f


def test_load_source_listings_returns_one_entry_per_listing(monkeypatch, tmp_path):
    """Iterates over LISTINGS, not SKUs: SKU-A has two sellers so it must yield
    two rows, because each listing is a real request to the marketplace."""
    _use_skus(monkeypatch, tmp_path, TWO_SKUS)

    got = config_module.load_source_listings("shopee")

    assert [g["item_id"] for g in got] == ["111", "112", "222"]


def test_load_source_listings_carries_the_sku_down_to_every_listing(monkeypatch, tmp_path):
    """`sku` must travel with every listing -- it is the join key to reference_price.

    The two listings of SKU-A have different item_ids but share one logical SKU;
    without this column the mart layer cannot reach back to the list price and
    price_gap_pct does not exist."""
    _use_skus(monkeypatch, tmp_path, TWO_SKUS)

    got = config_module.load_source_listings("shopee")

    assert [g["sku"] for g in got] == ["SKU-A", "SKU-A", "SKU-B"]
    assert got[0]["reference_price"] == 489000
    assert got[1]["reference_price"] == 489000, "Both listings share one list price"
    assert got[0]["is_official"] is True
    assert got[1]["is_official"] is False


def test_load_source_listings_picks_the_right_source(monkeypatch, tmp_path):
    _use_skus(monkeypatch, tmp_path, TWO_SKUS)

    got = config_module.load_source_listings("tiktok")

    assert [g["sku"] for g in got] == ["SKU-B"]
    assert got[0]["item_id"] == "999"


def test_load_source_listings_skips_a_sku_without_that_source(monkeypatch, tmp_path, caplog):
    """Adding TikTok for one SKU must not stop the others being scraped on Shopee."""
    _use_skus(monkeypatch, tmp_path, TWO_SKUS)

    got = config_module.load_source_listings("tiktok")

    assert len(got) == 1
    assert "SKU-A" in caplog.text, "Skipping silently means losing a SKU unnoticed"


def test_load_source_listings_raises_when_nothing_declares_that_source(monkeypatch, tmp_path):
    """No SKU declaring the source is a config error and must fail immediately,
    rather than returning an empty list and letting the crawler run an empty
    batch it then reports as a success."""
    _use_skus(monkeypatch, tmp_path, TWO_SKUS)

    with pytest.raises(ValueError) as excinfo:
        config_module.load_source_listings("lazada")

    assert "lazada" in str(excinfo.value)


def test_get_listings_for_sku_returns_every_seller_of_one_sku(monkeypatch, tmp_path):
    _use_skus(monkeypatch, tmp_path, TWO_SKUS)

    got = config_module.get_listings_for_sku("SKU-A", "shopee")

    assert [g["item_id"] for g in got] == ["111", "112"]


def test_get_listings_for_sku_raises_for_an_unknown_sku(monkeypatch, tmp_path):
    _use_skus(monkeypatch, tmp_path, TWO_SKUS)

    with pytest.raises(KeyError):
        config_module.get_listings_for_sku("NO-SUCH-SKU", "shopee")


# ---------------------------------------------------------------------------
# Catching YAML typos -- a wrong config must point at what is wrong.
# ---------------------------------------------------------------------------

def test_load_skus_rejects_a_mapping_instead_of_a_list(monkeypatch, tmp_path):
    """Writing the YAML as a mapping instead of a list is an easy mistake.
    Unchecked, the loop walks over string keys and blows up with
    AttributeError: 'str' object has no attribute 'get' -- which says nothing
    about where the config file is wrong."""
    f = tmp_path / "skus.yaml"
    f.write_text("sku: SKU-A\nname: wrong shape\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "SKUS_FILE", f)

    with pytest.raises(ValueError) as excinfo:
        config_module.load_skus()

    assert "LIST" in str(excinfo.value)


def test_load_source_listings_rejects_a_single_listing_written_as_a_dict(monkeypatch, tmp_path):
    """The old shape (one dict per source) is now wrong -- say so, do not accept
    it silently."""
    _use_skus(monkeypatch, tmp_path, [
        {"sku": "SKU-A", "sources": {"shopee": {"item_id": "111",
                                                "url": "https://shopee.vn/a"}}}])

    with pytest.raises(ValueError) as excinfo:
        config_module.load_source_listings("shopee")

    assert "listing list" in str(excinfo.value)


def test_load_source_listings_does_not_kill_the_batch_over_one_bad_listing(monkeypatch, tmp_path):
    """A missing item_id/url must NOT raise in the config layer.

    load_source_listings() runs before the browser even opens, so raising here
    means one forgotten `url:` line kills the whole batch -- including listings
    that have been working for weeks. Field checking moved down into
    fetch_one_listing() so the error kills only its own listing (see the test in
    test_extract.py)."""
    _use_skus(monkeypatch, tmp_path, [
        {"sku": "SKU-A", "sources": {"shopee": [
            {"shop_id": "11"},
            {"shop_id": "12", "item_id": "112", "is_official": False,
             "url": "https://shopee.vn/a2"}]}}])

    got = config_module.load_source_listings("shopee")

    assert len(got) == 2, "The bad listing passes through; the layer below reports it alone"


def test_load_source_listings_defaults_is_official_to_false_and_says_so(monkeypatch, tmp_path):
    """Forgetting `is_official: true` for the official store inverts the business
    question -- every `WHERE is_official` filter reads NULL as not official.
    Defaulting to False is fine, but it has to speak up."""
    _use_skus(monkeypatch, tmp_path, [
        {"sku": "SKU-A", "sources": {"shopee": [
            {"shop_id": "11", "item_id": "111", "url": "https://shopee.vn/a"}]}}])

    got = config_module.load_source_listings("shopee")

    assert got[0]["is_official"] is False


def test_load_source_listings_warns_about_duplicate_listings(monkeypatch, tmp_path, caplog):
    """Copy-pasting a seller and forgetting to change item_id is an easy mistake
    with this YAML shape: the same page gets scraped twice, and `failures` (keyed
    by label) collapses both listings into one row, so the batch size is counted
    wrong."""
    _use_skus(monkeypatch, tmp_path, [
        {"sku": "SKU-A", "sources": {"shopee": [
            {"shop_id": "11", "item_id": "111", "is_official": True,
             "url": "https://shopee.vn/a"},
            {"shop_id": "11", "item_id": "111", "is_official": True,
             "url": "https://shopee.vn/a"}]}}])

    config_module.load_source_listings("shopee")

    assert "more than once" in caplog.text


def test_listing_label_names_both_the_sku_and_the_listing():
    """The sku alone cannot tell two listings of one SKU apart; the item_id alone
    leaves you reading a log with no idea which product it is."""
    label = config_module.listing_label({"sku": "SKU-A", "item_id": "111"})

    assert "SKU-A" in label and "111" in label


# ---------------------------------------------------------------------------
# raw_dir_for -- per-day partitioning of data/raw/.
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone


def test_raw_dir_for_names_the_folder_after_the_scrape_day(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "RAW_DIR", tmp_path)

    got = config_module.raw_dir_for(datetime(2026, 8, 28, 5, 55, tzinfo=timezone.utc))

    assert got == tmp_path / "2026-08-28"
    assert got.is_dir(), "Created on demand -- extract.py writes straight into it"


def test_raw_dir_for_uses_utc_not_the_local_clock(tmp_path, monkeypatch):
    """A scrape at 23:30 UTC must not land in tomorrow's folder just because the
    machine running it is seven hours ahead. The filename, the envelope and the
    folder all have to name the same UTC day."""
    monkeypatch.setattr(config_module, "RAW_DIR", tmp_path)
    seven_hours_ahead = timezone(timedelta(hours=7))

    got = config_module.raw_dir_for(
        datetime(2026, 8, 29, 6, 30, tzinfo=seven_hours_ahead))  # = 23:30Z on the 28th

    assert got.name == "2026-08-28"


# ---------------------------------------------------------------------------
# Guard rails for the REAL file.
# ---------------------------------------------------------------------------

def test_the_real_skus_file_is_readable_and_declares_shopee():
    """Only checks that the real file parses and that every listing has the
    fields the code needs.

    No assertion on counts or specific item_ids: the user will add listings, and
    a test that counts them would go red every time they add a link -- teaching
    people to ignore red tests."""
    got = config_module.load_source_listings("shopee")

    assert len(got) >= 1
    for entry in got:
        assert entry["item_id"] and entry["url"]
        assert entry["sku"], "Without sku there is no join key to reference_price"


def test_the_real_skus_file_urls_match_their_shop_and_item_id():
    """Shopee URLs end in .<shop_id>.<item_id> -- a mismatch means the config has
    a typo, and the crawler would silently scrape the wrong page."""
    for entry in config_module.load_source_listings("shopee"):
        shop_id = entry.get("shop_id")
        assert shop_id, f"Listing {entry['item_id']} has no shop_id in skus.yaml"
        assert entry["url"].endswith(f".{shop_id}.{entry['item_id']}"), \
            f"URL does not match shop_id/item_id: {entry['url']}"
