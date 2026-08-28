"""Tests for transform.py -- pure functions: read one JSON file, map its fields.

No browser, no network, runs in milliseconds.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from price_tracker.sources.shopee.transform import build_record


# The real magnitude Shopee returns, taken from the evidence in
# docs/Issue_Logs.md: 48_900_000_000 / 100_000 = 489_000 VND (the actual list
# price of the G102 mouse). Using the real scale instead of a made-up small
# number is what lets these tests catch a wrong scaling factor.
RAW_PRICE_489K = 48_900_000_000
VND_489K = 489_000.0

# A fake listing config, shaped exactly as config/skus.yaml produces.
# build_record() needs it because `sku` and `is_official` are NOT in the Shopee
# payload -- they come from config, and `sku` is the join key to
# reference_price in the mart layer.
LISTING_CFG = {
    "sku": "G102-LIGHTSYNC",
    "name": "Logitech G102 Lightsync",
    "reference_price": 489_000,
    "shop_id": "52679373",
    "item_id": "6765591429",
    "is_official": True,
}


def _write_fake_raw(tmp_path, item: dict, url: str | None = None,
                    name: str = "shopee_raw_6765591429_20260820T035111Z.json") -> Path:
    """Write one fake JSON file matching the real raw structure Shopee returns
    (raw['data']['data']['item']), so build_record() can be tested without
    running a real scrape through extract.py."""
    fake_raw = {"data": {"data": {"item": item}}}
    if url is not None:
        fake_raw["url"] = url

    # The name must follow the real convention: build_record() derives the
    # scrape time from it when the envelope has no scraped_at (files written by
    # older code).
    raw_path = tmp_path / name
    raw_path.write_text(json.dumps(
        fake_raw, ensure_ascii=False), encoding="utf-8")
    return raw_path


def test_build_record_maps_fields_correctly(tmp_path):
    raw_path = _write_fake_raw(
        tmp_path,
        item={
            "item_id": 6765591429,
            "shop_id": 52679373,
            "title": "Logitech G102 gaming mouse",
            "price": RAW_PRICE_489K,
            "price_min": RAW_PRICE_489K,
        },
        url="https://shopee.vn/product/52679373/6765591429",
    )

    record = build_record(raw_path, LISTING_CFG)

    # item_id comes from the CONFIG (a string), not from the payload (a number)
    # -- see the comment in build_record: without the field the staging file
    # would be named shopee_record_None_<ts>.json and two listings would
    # overwrite each other.
    assert record["item_id"] == "6765591429"
    assert record["source"] == "shopee"
    assert record["seller_id"] == 52679373
    assert record["product_name"] == "Logitech G102 gaming mouse"
    assert record["price"] == VND_489K
    assert record["url"] == "https://shopee.vn/product/52679373/6765591429"
    assert "scraped_at" in record  # a timestamp exists; the exact value is checked elsewhere


def test_build_record_falls_back_to_price_min_when_price_is_none(tmp_path):
    raw_path = _write_fake_raw(
        tmp_path,
        item={
            "item_id": 1,
            "shop_id": 2,
            "title": "Test product",
            "price": None,
            "price_min": RAW_PRICE_489K,
        },
    )

    record = build_record(raw_path, LISTING_CFG)

    assert record["price"] == VND_489K


def test_build_record_returns_none_when_price_and_price_min_missing(tmp_path, caplog):
    """A missing price must return None + log a warning, and must NOT return 0.0.

    0.0 is a silent bug: down in the mart layer it reads as 'price of zero' and
    produces price_change_pct = -100% with nobody realising it came from missing
    data. With None, the quarantine layer (see README) can still separate it
    out."""
    raw_path = _write_fake_raw(
        tmp_path,
        item={
            "item_id": 1,
            "shop_id": 2,
            "title": "Product with neither price nor price_min",
            "price": None,
            "price_min": None,
        },
    )

    record = build_record(raw_path, LISTING_CFG)

    assert record["price"] is None
    assert any(r.levelname == "WARNING" for r in caplog.records), \
        "A missing price passed over in silence is a missing price nobody investigates"


def test_build_record_returns_none_when_price_is_not_a_number(tmp_path, caplog):
    """A price returned as a string (Shopee has such fields) must not kill the run.

    parse_price claims that "one broken SKU is not worth killing the whole run",
    so it has to keep that promise for every kind of garbage, not only None --
    raw_price / 100_000 on a str raises a TypeError that escapes straight out."""
    raw_path = _write_fake_raw(
        tmp_path,
        item={
            "item_id": 1,
            "shop_id": 2,
            "title": "Product whose price comes back as a string",
            "price": "48900000000",
            "price_min": None,
        },
    )

    record = build_record(raw_path, LISTING_CFG)

    assert record["price"] is None
    assert any(r.levelname == "WARNING" for r in caplog.records)


def test_build_record_keeps_a_genuine_zero_price(tmp_path):
    """A REAL price of 0 must differ from a MISSING price.

    This is why the code uses `is None` and not `or`: with `or`, price=0 is
    falsy and falls through to the fallback branch, destroying the ability to
    tell two completely different cases apart."""
    raw_path = _write_fake_raw(
        tmp_path,
        item={
            "item_id": 1,
            "shop_id": 2,
            "title": "Genuinely free product (bundled gift)",
            "price": 0,
            "price_min": RAW_PRICE_489K,
        },
    )

    record = build_record(raw_path, LISTING_CFG)

    assert record["price"] == 0.0
    assert record["price"] is not None


# ---------------------------------------------------------------------------
# find_latest_raw_file -- the second line of defence for C1.
#
# Layer 1 (validation in extract.py) stops a poisoned file from reaching disk.
# This layer handles a poisoned file that is ALREADY there -- from older code,
# or from a hand edit. Without it, one broken file breaks transform forever,
# because it is always the newest one.
# ---------------------------------------------------------------------------

import os

import pytest

from price_tracker.sources.shopee import transform as transform_module

HEALTHY_ITEM = {"item_id": 6765591429, "shop_id": 52679373,
                "title": "Logitech G102", "price": RAW_PRICE_489K}


def _write_raw_file(dir_path, name: str, payload, mtime: float) -> Path:
    """Write one raw file in the envelope shape extract.py produces, with a
    chosen mtime.

    The mtime is set explicitly rather than relying on write order, so the test
    does not depend on the filesystem's mtime resolution."""
    p = dir_path / name
    if isinstance(payload, str):
        p.write_text(payload, encoding="utf-8")          # garbage, not JSON
    else:
        p.write_text(json.dumps({"data": payload, "url": "https://shopee.vn/x"},
                                ensure_ascii=False), encoding="utf-8")
    os.utime(p, (mtime, mtime))
    return p


def test_find_latest_raw_file_skips_a_poisoned_newest_file(tmp_path, monkeypatch, caplog):
    """The NEWEST poisoned file must not be allowed to block the whole pipeline.

    This is the "broken once, broken always" case: the poisoned file always has
    the highest mtime, so the old version picked exactly it on every later run."""
    monkeypatch.setattr(transform_module, "RAW_DIR", tmp_path)

    _write_raw_file(tmp_path, "shopee_raw_1_old.json",
                    {"error": None, "data": {"item": HEALTHY_ITEM}}, mtime=1000)
    _write_raw_file(tmp_path, "shopee_raw_1_new.json",
                    {"error": 1, "error_msg": "server busy", "data": None}, mtime=2000)

    chosen = transform_module.find_latest_raw_file("1")

    assert chosen.name == "shopee_raw_1_old.json"
    # caplog.text is the already-formatted log -- assert on that rather than
    # re-doing the %-formatting by hand
    assert "shopee_raw_1_new.json" in caplog.text  # must log the NAME of the skipped file
    assert "server busy" in caplog.text  # and the REASON, or you know it broke but not why


def test_find_latest_raw_file_skips_unparseable_json(tmp_path, monkeypatch):
    monkeypatch.setattr(transform_module, "RAW_DIR", tmp_path)

    _write_raw_file(tmp_path, "shopee_raw_1_old.json",
                    {"error": None, "data": {"item": HEALTHY_ITEM}}, mtime=1000)
    _write_raw_file(tmp_path, "shopee_raw_1_broken.json",
                    "{ this is not JSON", mtime=2000)

    assert transform_module.find_latest_raw_file("1").name == "shopee_raw_1_old.json"


def test_find_latest_raw_file_reports_how_many_it_skipped(tmp_path, monkeypatch):
    """With no healthy file left, it must say how many were skipped and why --
    quite different from a plain 'no raw file found'."""
    monkeypatch.setattr(transform_module, "RAW_DIR", tmp_path)

    _write_raw_file(tmp_path, "shopee_raw_1_a.json",
                    {"error": 1, "error_msg": "blocked", "data": None}, mtime=1000)
    _write_raw_file(tmp_path, "shopee_raw_1_b.json", "garbage", mtime=2000)

    with pytest.raises(FileNotFoundError) as excinfo:
        transform_module.find_latest_raw_file("1")

    msg = str(excinfo.value)
    assert "2" in msg
    assert "shopee_raw_1_a.json" in msg and "shopee_raw_1_b.json" in msg


def test_find_latest_raw_file_still_reports_an_empty_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(transform_module, "RAW_DIR", tmp_path)

    with pytest.raises(FileNotFoundError):
        transform_module.find_latest_raw_file("1")


def test_build_record_gives_a_clear_error_on_a_poisoned_file(tmp_path):
    """This used to raise TypeError: 'NoneType' object is not subscriptable --
    accurate, but it said nothing about which file was broken or why."""
    p = tmp_path / "poisoned.json"
    p.write_text(json.dumps({"data": {"error": 1, "error_msg": "blocked",
                                      "data": None}, "url": "x"}), encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        build_record(p, LISTING_CFG)

    assert "poisoned.json" in str(excinfo.value)


def test_find_latest_raw_file_skips_a_file_with_broken_utf8(tmp_path, monkeypatch):
    """A file cut off in the middle of a multi-byte character.

    read_text(encoding="utf-8") raises UnicodeDecodeError BEFORE json.loads ever
    runs, and UnicodeDecodeError is neither an OSError nor a JSONDecodeError.
    Not catching it drops us right back into the "broken once, broken always"
    trap this function exists to remove. It is a real scenario: extract.py
    writes with ensure_ascii=False, so the files are full of multi-byte
    characters, and a Ctrl-C mid-write is enough."""
    monkeypatch.setattr(transform_module, "RAW_DIR", tmp_path)

    _write_raw_file(tmp_path, "shopee_raw_1_old.json",
                    {"error": None, "data": {"item": HEALTHY_ITEM}}, mtime=1000)
    truncated = tmp_path / "shopee_raw_1_cut.json"
    body = json.dumps({"data": {"error": None, "data": {"item": {"title": "Mouse™"}}}},
                      ensure_ascii=False).encode("utf-8")
    truncated.write_bytes(body[:-3] + b"\xe1\xba")   # cut mid multi-byte character
    os.utime(truncated, (2000, 2000))

    assert transform_module.find_latest_raw_file("1").name == "shopee_raw_1_old.json"


def test_find_latest_raw_file_accepts_an_old_bare_payload_file(tmp_path, monkeypatch):
    """A bare payload file (pre-envelope code) is still usable -- do not skip it."""
    monkeypatch.setattr(transform_module, "RAW_DIR", tmp_path)

    bare = tmp_path / "shopee_raw_1_bare.json"
    bare.write_text(json.dumps({"bff_meta": {}, "error": None, "error_msg": None,
                                "data": {"item": HEALTHY_ITEM}}), encoding="utf-8")
    os.utime(bare, (2000, 2000))

    assert transform_module.find_latest_raw_file("1").name == "shopee_raw_1_bare.json"


def test_build_record_reads_an_old_bare_payload_file(tmp_path):
    p = tmp_path / "shopee_raw_6765591429_20260820T035111Z.json"
    p.write_text(json.dumps({"bff_meta": {}, "error": None, "error_msg": None,
                             "data": {"item": HEALTHY_ITEM}}), encoding="utf-8")

    record = build_record(p, LISTING_CFG)

    # item_id comes from the CONFIG (a string), not from the payload (a number)
    # -- see the comment in build_record: without the field the staging file
    # would be named shopee_record_None_<ts>.json and two listings would
    # overwrite each other.
    assert record["item_id"] == "6765591429"
    assert record["source"] == "shopee"
    assert record["price"] == VND_489K


# ---------------------------------------------------------------------------
# scraped_at must be the SCRAPE time, not the time transform ran.
#
# Why it matters: find_latest_raw_file() may return an OLD scrape when the
# newest one is broken. If build_record() stamped datetime.now(), the record
# would carry an OLD PRICE with TODAY'S TIMESTAMP. Run daily while Shopee blocks
# us for a week and the mart layer gets a perfectly flat price series that looks
# entirely real -- LAG() sees nothing odd, and nobody knows the data is fake.
# ---------------------------------------------------------------------------

SCRAPED_AT_IN_FILE = "2026-08-20T03:51:11+00:00"


def _write_raw_named(tmp_path, name: str, *, scraped_at: str | None) -> Path:
    """A raw file in the envelope shape, with a chosen name and scraped_at
    switched on or off."""
    raw = {
        "data": {"data": {"item": {
            "item_id": 6765591429,
            "shop_id": 52679373,
            "title": "Logitech G102 gaming mouse",
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

    record = build_record(raw_path, LISTING_CFG)

    assert record["scraped_at"] == SCRAPED_AT_IN_FILE


def test_build_record_falls_back_to_the_filename_timestamp(tmp_path):
    """Files scraped by older code have no scraped_at in the envelope.

    data/raw/ holds real files of that kind -- treating them as broken throws
    away good data, so the timestamp has to be readable from the filename.
    """
    raw_path = _write_raw_named(
        tmp_path, "shopee_raw_6765591429_20260820T035111Z.json",
        scraped_at=None)

    record = build_record(raw_path, LISTING_CFG)

    assert record["scraped_at"] == SCRAPED_AT_IN_FILE


def test_build_record_does_not_stamp_an_old_file_with_today(tmp_path):
    """The original bug, stated directly as a test."""
    raw_path = _write_raw_named(
        tmp_path, "shopee_raw_6765591429_20260820T035111Z.json",
        scraped_at=None)

    record = build_record(raw_path, LISTING_CFG)
    today = datetime.now(timezone.utc).date().isoformat()

    assert not record["scraped_at"].startswith(today)
    assert record["scraped_at"].startswith("2026-08-20")


def test_build_record_refuses_a_file_with_no_derivable_scrape_time(tmp_path):
    """If the scrape time cannot be derived, it must NOT quietly use now().

    Quietly using now() is the very bug being fixed. Failing loudly and early
    beats producing a wrong row nobody ever notices.
    """
    raw_path = _write_raw_named(tmp_path, "does_not_follow_convention.json",
                                scraped_at=None)

    with pytest.raises(ValueError, match="scrape time"):
        build_record(raw_path, LISTING_CFG)


def test_build_record_ignores_a_garbage_envelope_timestamp(tmp_path):
    """Garbage in the envelope must fall through to the filename, not reach the
    record.

    Checking only "is a non-empty string" lets garbage through, and it flows on
    into the warehouse. The filename is usually still intact when the envelope
    is not.
    """
    raw_path = _write_raw_named(
        tmp_path, "shopee_raw_6765591429_20260820T035111Z.json",
        scraped_at="sometime yesterday")

    record = build_record(raw_path, LISTING_CFG)

    assert record["scraped_at"] == SCRAPED_AT_IN_FILE


def test_build_record_normalises_a_z_suffix_timestamp(tmp_path):
    """Whether it is written as 'Z' or '+00:00', the record comes out in one
    single format."""
    raw_path = _write_raw_named(
        tmp_path, "shopee_raw_6765591429_20260820T035111Z.json",
        scraped_at="2026-08-20T03:51:11Z")

    record = build_record(raw_path, LISTING_CFG)

    assert record["scraped_at"] == SCRAPED_AT_IN_FILE


def test_save_record_is_idempotent_for_the_same_scrape(tmp_path, monkeypatch):
    """Re-running transform on the same scrape must not produce another file.

    data/staging/ will be loaded into the warehouse. Every re-run creating a new
    file manufactures duplicate rows downstream -- exactly what dbt's
    incremental unique_key exists to clean up, so do not create them in the
    first place.
    """
    monkeypatch.setattr(transform_module, "STAGING_DIR", tmp_path)
    raw_path = _write_raw_named(
        tmp_path, "shopee_raw_6765591429_20260820T035111Z.json",
        scraped_at=SCRAPED_AT_IN_FILE)

    record = build_record(raw_path, LISTING_CFG)
    first = transform_module.save_record(record)
    second = transform_module.save_record(build_record(raw_path, LISTING_CFG))

    assert first == second
    assert len(list(tmp_path.glob("shopee_record_*.json"))) == 1
    assert "20260820T035111Z" in first.name


def test_find_latest_raw_file_only_looks_at_the_requested_sku(tmp_path, monkeypatch):
    """The bug shows up the moment there is a second SKU: globbing
    shopee_raw_*.json sweeps up every SKU and returns ONE newest file, so N-1
    SKUs are dropped silently -- transform finishes, reports success, and
    produces a single record."""
    monkeypatch.setattr(transform_module, "RAW_DIR", tmp_path)

    _write_raw_file(tmp_path, "shopee_raw_111_old.json",
                    {"error": None, "data": {"item": HEALTHY_ITEM}}, mtime=1000)
    # A different SKU with a NEWER file -- must not leak into SKU 111's result
    _write_raw_file(tmp_path, "shopee_raw_222_new.json",
                    {"error": None, "data": {"item": HEALTHY_ITEM}}, mtime=5000)

    assert transform_module.find_latest_raw_file("111").name == "shopee_raw_111_old.json"
    assert transform_module.find_latest_raw_file("222").name == "shopee_raw_222_new.json"


def test_find_latest_raw_file_reads_the_per_day_folders(tmp_path, monkeypatch):
    """extract.py writes into data/raw/<YYYY-MM-DD>/ so the directory does not
    grow to 36,500 files a year. The reader has to follow it down."""
    monkeypatch.setattr(transform_module, "RAW_DIR", tmp_path)
    day = tmp_path / "2026-08-28"
    day.mkdir()

    _write_raw_file(day, "shopee_raw_1_20260828T010000Z.json",
                    {"error": None, "data": {"item": HEALTHY_ITEM}}, mtime=2000)

    assert transform_module.find_latest_raw_file("1").name == \
        "shopee_raw_1_20260828T010000Z.json"


def test_find_latest_raw_file_still_finds_the_old_flat_files(tmp_path, monkeypatch):
    """Switching to per-day folders must not orphan the history already on disk.

    Both layouts have to coexist, and the newest wins regardless of which
    layout it sits in."""
    monkeypatch.setattr(transform_module, "RAW_DIR", tmp_path)
    day = tmp_path / "2026-08-28"
    day.mkdir()

    _write_raw_file(tmp_path, "shopee_raw_1_flat.json",
                    {"error": None, "data": {"item": HEALTHY_ITEM}}, mtime=9000)
    _write_raw_file(day, "shopee_raw_1_dated.json",
                    {"error": None, "data": {"item": HEALTHY_ITEM}}, mtime=1000)

    assert transform_module.find_latest_raw_file("1").name == "shopee_raw_1_flat.json"


def test_find_latest_raw_file_message_names_the_sku_when_it_finds_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(transform_module, "RAW_DIR", tmp_path)

    _write_raw_file(tmp_path, "shopee_raw_222_new.json",
                    {"error": None, "data": {"item": HEALTHY_ITEM}}, mtime=5000)

    with pytest.raises(FileNotFoundError) as excinfo:
        transform_module.find_latest_raw_file("111")

    assert "111" in str(excinfo.value)


# ---------------------------------------------------------------------------
# The two identity layers in a record -- what the mart layer lives on.
# ---------------------------------------------------------------------------

def test_build_record_carries_the_logical_sku_as_the_join_key(tmp_path):
    """`sku` must reach the record, or the mart cannot join reference_price.

    Many sellers list the same product, each listing with a different item_id.
    reference_price is attached to the logical SKU. Without the `sku` column
    there is no link between the two -- no price_gap_pct, and the entire point
    of the project is gone."""
    raw_path = _write_fake_raw(tmp_path, item={"item_id": 6765591429,
                                               "shop_id": 52679373,
                                               "title": "G102",
                                               "price": RAW_PRICE_489K})

    record = build_record(raw_path, LISTING_CFG)

    assert record["sku"] == "G102-LIGHTSYNC"
    assert record["item_id"] == "6765591429", "item_id is the marketplace listing id, taken from config"
    assert record["seller_id"] == 52679373


def test_build_record_carries_is_official_from_config(tmp_path):
    """is_official is not in the Shopee payload -- without it the mart cannot
    separate the official price from another seller's, which is the exact
    question we are answering."""
    raw_path = _write_fake_raw(tmp_path, item={"item_id": 1, "shop_id": 2,
                                               "title": "x",
                                               "price": RAW_PRICE_489K})

    reseller_cfg = {**LISTING_CFG, "item_id": "26201330261",
                    "shop_id": "1256164758", "is_official": False}

    assert build_record(raw_path, LISTING_CFG)["is_official"] is True
    assert build_record(raw_path, reseller_cfg)["is_official"] is False


def test_two_listings_of_one_sku_share_the_join_key_but_differ_on_listing(tmp_path):
    """This is exactly the data shape the price gap relies on: same `sku`,
    different `item_id`/`seller_id`, one official and one not."""
    official_raw = _write_fake_raw(tmp_path, item={"item_id": 6765591429,
                                                   "shop_id": 52679373,
                                                   "title": "official",
                                                   "price": RAW_PRICE_489K},
                                   name="shopee_raw_6765591429_20260820T035111Z.json")
    reseller_raw = _write_fake_raw(tmp_path, item={"item_id": 26201330261,
                                                    "shop_id": 1256164758,
                                                    "title": "reseller",
                                                    "price": 45_000_000_000},
                                   name="shopee_raw_26201330261_20260820T035111Z.json")
    reseller_cfg = {**LISTING_CFG, "item_id": "26201330261",
                    "shop_id": "1256164758", "is_official": False}

    a = build_record(official_raw, LISTING_CFG)
    b = build_record(reseller_raw, reseller_cfg)

    assert a["sku"] == b["sku"], "The same logical product"
    assert a["item_id"] == "6765591429" and b["item_id"] == "26201330261"
    assert a["item_id"] != b["item_id"], "Different listings"
    assert a["seller_id"] != b["seller_id"], "Different sellers"
    assert a["price"] != b["price"]


def test_save_record_names_the_file_after_the_listing(tmp_path, monkeypatch):
    """The staging filename must follow item_id: naming it after the sku means
    two listings of one SKU overwrite each other, losing half the data."""
    monkeypatch.setattr(transform_module, "STAGING_DIR", tmp_path)

    out = transform_module.save_record({
        "sku": "G102-LIGHTSYNC", "item_id": 26201330261,
        "scraped_at": "2026-08-27T05:55:22+00:00"})

    assert "26201330261" in out.name


def test_build_record_never_leaves_item_id_empty_even_if_shopee_omits_it(tmp_path):
    """A payload missing item_id must not cost the record its listing identity.

    Taking item_id from the payload would yield None here, and save_record would
    name the file shopee_record_None_<ts>.json -- two listings scraped in the
    same second overwrite each other, silently losing half the data."""
    raw_path = _write_fake_raw(tmp_path, item={"shop_id": 52679373,
                                               "title": "item_id missing",
                                               "price": RAW_PRICE_489K})

    record = build_record(raw_path, LISTING_CFG)

    assert record["item_id"] == "6765591429"
