"""Tests for extract.py -- only the JSON-unwrapping and debug-evidence parts.

Those two functions were split out of fetch_one_listing() precisely so they can
be tested without opening a browser: they only take an object with .json() /
.screenshot(), so a fake object is enough. fetch_one_listing() itself is not
tested here because it has to open a real Chrome with a real session.
"""

import json

import pytest
from patchright.sync_api import Error as PWError, TimeoutError as PWTimeout

from price_tracker.sources.shopee.extract import (
    FetchFailedError,
    extract_json_or_fail,
    dump_debug_evidence,
    validate_payload_or_fail,
    fetch_one_listing,
)


FAKE_URL = "https://shopee.vn/api/v4/pdp/get_pc?item_id=6765591429"


class _FakeResponse:
    """A stand-in for a patchright Response -- it only needs .url and .json()."""

    def __init__(self, payload=None, raises: Exception | None = None):
        self.url = FAKE_URL
        self._payload = payload
        self._raises = raises

    def json(self):
        if self._raises is not None:
            raise self._raises
        return self._payload


def test_extract_json_returns_payload_when_body_is_valid_json():
    response = _FakeResponse(payload={"data": {"item": {"item_id": 1}}})

    assert extract_json_or_fail(response) == {"data": {"item": {"item_id": 1}}}


def test_extract_json_converts_patchright_error_to_fetch_failed():
    """The most common real case: the session expires -> Shopee 302s to the
    login wall, and patchright raises
    Error('Response body is unavailable for redirect responses').

    That is NOT a JSONDecodeError. Unconverted, it escapes both the except block
    and tenacity's filter -> no retry, and the browser is never closed."""
    response = _FakeResponse(
        raises=PWError("Response body is unavailable for redirect responses"))

    with pytest.raises(FetchFailedError):
        extract_json_or_fail(response)


def test_extract_json_converts_json_decode_error_to_fetch_failed():
    response = _FakeResponse(raises=json.JSONDecodeError("Expecting value", "", 0))

    with pytest.raises(FetchFailedError):
        extract_json_or_fail(response)


def test_extract_json_converts_unicode_decode_error_to_fetch_failed():
    """A non-UTF-8 body -> .decode() raises UnicodeDecodeError, which is also
    not a JSONDecodeError."""
    response = _FakeResponse(
        raises=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"))

    with pytest.raises(FetchFailedError):
        extract_json_or_fail(response)


def test_extract_json_keeps_original_exception_as_cause():
    """Converting must not swallow the root cause, or the log only ever says
    'fetch failed' without saying why."""
    original = PWError("No resource with given identifier found")
    response = _FakeResponse(raises=original)

    with pytest.raises(FetchFailedError) as excinfo:
        extract_json_or_fail(response)

    assert excinfo.value.__cause__ is original


class _ExplodingPage:
    """A fake page where every operation raises -- simulating a crashed or
    closed target, which is exactly when the evidence is needed most."""

    def screenshot(self, **kwargs):
        raise PWTimeout("Timeout 30000ms exceeded taking screenshot")

    def content(self):
        raise PWError("Target page, context or browser has been closed")


def test_dump_debug_evidence_never_raises(tmp_path):
    """The evidence-capture block must never raise: if it did, it would replace
    the original diagnostic exception and stop browser.close() from running."""
    dump_debug_evidence(_ExplodingPage(), debug_dir=tmp_path)  # must not raise


# ---------------------------------------------------------------------------
# prune_debug_evidence -- housekeeping, so it may never raise and may never
# delete anything it did not write.
# ---------------------------------------------------------------------------

import os
import time as _time

from price_tracker.sources.shopee.extract import prune_debug_evidence


def _aged_file(path, days_old: float):
    path.write_text("x", encoding="utf-8")
    when = _time.time() - days_old * 86_400
    os.utime(path, (when, when))
    return path


def test_prune_debug_evidence_deletes_only_what_is_too_old(tmp_path):
    old = _aged_file(tmp_path / "fail_111_20260101T000000Z.html", days_old=30)
    recent = _aged_file(tmp_path / "fail_222_20260827T000000Z.html", days_old=1)

    removed = prune_debug_evidence(tmp_path, max_age_days=7)

    assert removed == 1
    assert not old.exists()
    assert recent.exists(), "Evidence from this week is still being investigated"


def test_prune_debug_evidence_leaves_files_it_did_not_write(tmp_path):
    """Deleting purely by age would make this a loaded gun aimed at whatever
    else ends up in the folder."""
    stranger = _aged_file(tmp_path / "notes.md", days_old=365)
    evidence = _aged_file(tmp_path / "fail_111_20260101T000000Z.png", days_old=365)

    prune_debug_evidence(tmp_path, max_age_days=7)

    assert stranger.exists(), "Only fail_*.html / fail_*.png belong to this function"
    assert not evidence.exists()


def test_prune_debug_evidence_is_a_no_op_when_the_dir_is_missing(tmp_path):
    """Runs on every batch, including the very first one, before anything has
    ever failed."""
    assert prune_debug_evidence(tmp_path / "never_created") == 0


def test_retry_covers_the_exceptions_fetch_one_listing_actually_raises():
    """Pins down the wiring: the exception types fetch_one_listing raises must
    be the ones tenacity agrees to retry, otherwise the retry is decorative."""
    retry_config = fetch_one_listing.retry

    assert retry_config.stop.max_attempt_number == 3
    assert FetchFailedError in retry_config.retry.exception_types
    assert PWError in retry_config.retry.exception_types


def test_validate_payload_or_fail_passes_a_healthy_payload():
    payload = {"error": None, "data": {"item": {"item_id": 6765591429}}}

    assert validate_payload_or_fail(payload) == {"item_id": 6765591429}


def test_validate_payload_or_fail_rejects_shopee_error_payload():
    """Layer 1 of C1: block it BEFORE anything is written to data/raw/.

    It has to be a FetchFailedError so tenacity retries -- this is the most
    retry-worthy case there is (a temporary block or throttle), and the old
    version counted it as a success."""
    payload = {"error": 1, "error_msg": "server busy", "data": None}

    with pytest.raises(FetchFailedError) as excinfo:
        validate_payload_or_fail(payload)

    msg = str(excinfo.value)
    assert "1" in msg and "server busy" in msg, \
        "Must quote Shopee's real error/error_msg, not swallow the clue"


# ---------------------------------------------------------------------------
# fetch_all_listings -- orchestrating a batch of N SKUs.
#
# fetch_one_listing is replaced with a fake here: the goal is to test the
# ORCHESTRATION (looping, isolating failures, pausing between SKUs, raising at
# the end), not to re-test the scraping -- that already has its own tests above.
# As a result these tests open no browser, touch no network, and need no .env.
# ---------------------------------------------------------------------------

from price_tracker.sources.shopee.extract import (
    fetch_all_listings,
    BatchIncompleteError,
)
from price_tracker.sources.shopee import extract as extract_module

LISTING_A = {"sku": "SKU-A", "item_id": "111", "url": "https://shopee.vn/a"}
LISTING_B = {"sku": "SKU-B", "item_id": "222", "url": "https://shopee.vn/b"}
LISTING_C = {"sku": "SKU-C", "item_id": "333", "url": "https://shopee.vn/c"}


class _FakeBrowser:
    def __init__(self):
        self.close_count = 0

    def close(self):
        self.close_count += 1


class _FakePlaywright:
    """Enough to replace sync_playwright(): both a context manager and a
    holder of .chromium."""

    def __init__(self, browser):
        self._browser = browser
        self.launch_count = 0
        self.chromium = self

    def launch_persistent_context(self, *args, **kwargs):
        self.launch_count += 1
        return self._browser

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_browser(monkeypatch):
    """Block everything that touches a real browser, and the .env requirement."""
    browser = _FakeBrowser()
    fake_pw = _FakePlaywright(browser)
    monkeypatch.setattr(extract_module, "sync_playwright", lambda: fake_pw)
    monkeypatch.setattr(extract_module, "require_user_data_dir",
                        lambda: "C:/fake/profile")
    monkeypatch.setattr(extract_module, "sleep_between_listings", lambda: None)
    return browser, fake_pw


def test_fetch_all_listings_keeps_going_when_one_sku_fails(tmp_path, monkeypatch):
    """A SKU failing in the MIDDLE of the list must not cost us the SKUs after it.

    This is the easiest behaviour to get wrong and the most silent when it is:
    if it is wrong, it only surfaces when Shopee blocks the first SKU in the
    list -- and by then the whole batch is gone."""
    _patch_browser(monkeypatch)
    seen = []

    def fake_fetch_one(browser, sku_cfg):
        seen.append(sku_cfg["sku"])
        if sku_cfg["sku"] == "SKU-B":
            raise FetchFailedError("Shopee blocked SKU-B")
        return tmp_path / f"raw_{sku_cfg['item_id']}.json"

    monkeypatch.setattr(extract_module, "fetch_one_listing", fake_fetch_one)

    with pytest.raises(BatchIncompleteError) as excinfo:
        fetch_all_listings([LISTING_A, LISTING_B, LISTING_C])

    assert seen == ["SKU-A", "SKU-B", "SKU-C"], "Must try them ALL, not stop at the failure"
    assert [path.name for path, _ in excinfo.value.succeeded] == ["raw_111.json", "raw_333.json"]


def test_fetch_all_listings_reports_which_sku_failed_and_why(monkeypatch):
    _patch_browser(monkeypatch)

    def fake_fetch_one(browser, sku_cfg):
        raise FetchFailedError("Shopee returned error=1, error_msg='blocked'")

    monkeypatch.setattr(extract_module, "fetch_one_listing", fake_fetch_one)

    with pytest.raises(BatchIncompleteError) as excinfo:
        fetch_all_listings([LISTING_A])

    assert "SKU-A/111" in str(excinfo.value), "The label must carry both sku and item_id"
    assert "blocked" in str(excinfo.value), "Swallow the reason and the log still cannot say why"
    assert "SKU-A/111" in excinfo.value.failures


def test_fetch_all_listings_returns_paths_when_every_sku_works(tmp_path, monkeypatch):
    _patch_browser(monkeypatch)
    monkeypatch.setattr(extract_module, "fetch_one_listing",
                        lambda browser, cfg: tmp_path / f"raw_{cfg['item_id']}.json")

    fetched = fetch_all_listings([LISTING_A, LISTING_B])

    assert [path.name for path, _ in fetched] == ["raw_111.json", "raw_222.json"]
    assert [cfg["sku"] for _, cfg in fetched] == ["SKU-A", "SKU-B"], \
        "The config must come back too: sku/is_official are not in the Shopee payload"


def test_fetch_all_listings_opens_the_browser_once_for_the_whole_batch(tmp_path, monkeypatch):
    """Opening and closing Chrome per SKU invites lock contention on
    USER_DATA_DIR -- and the history of Issues 1-3 shows profile trouble means
    captcha trouble."""
    browser, fake_pw = _patch_browser(monkeypatch)
    monkeypatch.setattr(extract_module, "fetch_one_listing",
                        lambda b, cfg: tmp_path / f"raw_{cfg['item_id']}.json")

    fetch_all_listings([LISTING_A, LISTING_B, LISTING_C])

    assert fake_pw.launch_count == 1, "3 SKUs, but the browser may only open once"
    assert browser.close_count == 1


def test_fetch_all_listings_closes_the_browser_even_if_every_sku_fails(monkeypatch):
    browser, _ = _patch_browser(monkeypatch)

    def boom(browser_, cfg):
        raise FetchFailedError("failed")

    monkeypatch.setattr(extract_module, "fetch_one_listing", boom)

    with pytest.raises(BatchIncompleteError):
        fetch_all_listings([LISTING_A, LISTING_B])

    assert browser.close_count == 1, "Not closing means Chrome holds the profile lock for the next run"


def test_fetch_all_listings_waits_between_skus_but_not_before_the_first(tmp_path, monkeypatch):
    """The README promises a 'randomized 3-8s delay between requests' -- it has
    to be real.

    BETWEEN SKUs, not BEFORE the first one: waiting before doing anything at all
    only makes each run slower without spacing out a single request."""
    _patch_browser(monkeypatch)
    calls = []
    monkeypatch.setattr(extract_module, "sleep_between_listings",
                        lambda: calls.append("slept"))
    monkeypatch.setattr(extract_module, "fetch_one_listing",
                        lambda b, cfg: tmp_path / f"raw_{cfg['item_id']}.json")

    fetch_all_listings([LISTING_A, LISTING_B, LISTING_C])

    assert len(calls) == 2, "3 SKUs -> 2 pauses (between 1-2 and 2-3), not 3"


def test_fetch_all_listings_does_not_wait_for_a_single_sku(tmp_path, monkeypatch):
    _patch_browser(monkeypatch)
    calls = []
    monkeypatch.setattr(extract_module, "sleep_between_listings",
                        lambda: calls.append("slept"))
    monkeypatch.setattr(extract_module, "fetch_one_listing",
                        lambda b, cfg: tmp_path / "raw.json")

    fetch_all_listings([LISTING_A])

    assert calls == []


def test_retry_is_attached_to_one_sku_not_to_the_whole_batch():
    """A transient failure on one SKU is not worth restarting Chrome for the
    whole batch."""
    assert hasattr(fetch_one_listing, "retry"), "fetch_one_listing must be tenacity-wrapped"
    assert fetch_one_listing.retry.stop.max_attempt_number == 3
    assert not hasattr(fetch_all_listings, "retry"), \
        "Wrapping the whole batch re-scrapes the SKUs that already succeeded"


def test_sleep_between_listings_stays_inside_the_promised_window(monkeypatch):
    """Check the pause really is the 3-8s the README promises, without sleeping."""
    slept = []
    monkeypatch.setattr(extract_module.time, "sleep", slept.append)

    for _ in range(50):
        extract_module.sleep_between_listings()

    assert all(extract_module.DELAY_BETWEEN_LISTINGS_MIN_S <= s <= extract_module.DELAY_BETWEEN_LISTINGS_MAX_S
               for s in slept)


# ---------------------------------------------------------------------------
# main.run_batch -- scraping plus packaging, collecting failures from both.
# ---------------------------------------------------------------------------

from price_tracker.sources.shopee import main as main_module


def test_batch_failed_tolerates_noise_but_not_a_bad_day():
    """The rule that decides the exit code, at the two sizes that matter.

    At 2 listings any failure is half the catalogue, so it stays red. At 100 a
    handful is ordinary -- and a run that goes red every single morning teaches
    everyone to ignore the colour long before the scrape actually breaks."""
    two_listings = (["ok"], {"a": "boom"})                       # 50% failed
    hundred_small = (["ok"] * 95, {str(i): "boom" for i in range(5)})   # 5%
    hundred_bad = (["ok"] * 60, {str(i): "boom" for i in range(40)})    # 40%

    assert main_module.batch_failed(*two_listings) is True
    assert main_module.batch_failed(*hundred_small) is False
    assert main_module.batch_failed(*hundred_bad) is True


def test_batch_failed_is_always_red_when_nothing_was_scraped():
    """An empty harvest is an incident whatever the threshold is set to --
    otherwise someone raising the threshold to 1.0 would make total failure
    report green."""
    assert main_module.batch_failed([], {"a": "boom", "b": "boom"},
                                    threshold=1.0) is True


def test_batch_failed_does_not_divide_by_zero_on_an_empty_batch():
    """load_source_listings() already raises for a config with no listings, so
    0/0 must not blow up on the way to that error."""
    assert main_module.batch_failed([], {}) is False


def test_run_batch_keeps_records_from_the_skus_that_worked(monkeypatch, tmp_path):
    """A batch missing SKUs must still keep the records of the SKUs it did get."""
    good = tmp_path / "raw_111.json"

    monkeypatch.setattr(
        main_module, "fetch_all_listings",
        lambda cfgs: (_ for _ in ()).throw(
            BatchIncompleteError([(good, LISTING_A)],
                                 {"SKU-B/222": "FetchFailedError: blocked"})))
    monkeypatch.setattr(main_module, "build_record",
                        lambda path, cfg: {"sku": cfg["sku"], "item_id": 111,
                                           "product_name": "A", "price": 489000.0,
                                           "is_official": True,
                                           "scraped_at": "2026-08-27T00:00:00+00:00"})
    monkeypatch.setattr(main_module, "save_record", lambda record: tmp_path / "rec.json")

    records, failures = main_module.run_batch([LISTING_A, LISTING_B])

    assert len(records) == 1
    assert records[0]["sku"] == "SKU-A"
    assert "SKU-B/222" in failures


def test_run_batch_counts_a_transform_failure_as_a_failed_sku(monkeypatch, tmp_path):
    """Scraped but not packaged still means that SKU has no data today."""
    raw = tmp_path / "raw_111.json"
    monkeypatch.setattr(main_module, "fetch_all_listings",
                        lambda cfgs: [(raw, LISTING_A)])

    def boom(path, cfg):
        raise ValueError("Raw file is broken")

    monkeypatch.setattr(main_module, "build_record", boom)

    records, failures = main_module.run_batch([LISTING_A])

    assert records == []
    # The label must match the one the scrape stage uses, not the raw filename
    # -- if the two stages name things differently, per-listing reconciliation
    # becomes impossible.
    assert "SKU-A/111" in failures
    assert "Raw file is broken" in failures["SKU-A/111"]


def test_fetch_all_listings_prunes_old_evidence_before_it_starts(tmp_path, monkeypatch):
    """Pruning runs even when the batch later dies, and never sweeps away the
    evidence this same run is about to write."""
    _patch_browser(monkeypatch)
    order = []
    monkeypatch.setattr(extract_module, "prune_debug_evidence",
                        lambda *a, **k: order.append("pruned"))
    monkeypatch.setattr(extract_module, "fetch_one_listing",
                        lambda b, cfg: order.append("fetched") or tmp_path / "raw.json")

    fetch_all_listings([LISTING_A])

    assert order == ["pruned", "fetched"]


def test_browser_visibility_follows_the_config_flag(monkeypatch, tmp_path):
    """headless must stay a config decision, not a hard-coded False.

    A visible window is the safer default against fingerprinting, but Airflow in
    a container has no desktop session at all, so the flag has to reach
    launch_persistent_context()."""
    browser, fake_pw = _patch_browser(monkeypatch)
    seen = {}

    def spy_launch(*args, **kwargs):
        seen.update(kwargs)
        return browser

    monkeypatch.setattr(fake_pw, "launch_persistent_context", spy_launch)
    monkeypatch.setattr(extract_module, "SHOPEE_HEADLESS", True)
    monkeypatch.setattr(extract_module, "fetch_one_listing",
                        lambda b, cfg: tmp_path / "raw.json")

    fetch_all_listings([LISTING_A])

    assert seen["headless"] is True


def test_a_listing_missing_url_only_kills_that_listing(tmp_path, monkeypatch):
    """A missing `url:` in skus.yaml must kill only that listing.

    This is where the code used to say one thing and do another: the comment
    promised isolated config errors, but the field check lived in the YAML
    layer -- running BEFORE the browser opens -- so one forgotten url line lost
    the entire batch."""
    _patch_browser(monkeypatch)
    broken = {"sku": "SKU-X", "item_id": "444"}          # no url

    monkeypatch.setattr(
        extract_module, "fetch_one_listing",
        extract_module.fetch_one_listing.__wrapped__
        if hasattr(extract_module.fetch_one_listing, "__wrapped__")
        else extract_module.fetch_one_listing)

    real_fetch = extract_module.fetch_one_listing

    def dispatch(browser, cfg):
        if cfg is broken:
            return real_fetch(browser, cfg)          # let it raise ValueError itself
        return tmp_path / f"raw_{cfg['item_id']}.json"

    monkeypatch.setattr(extract_module, "fetch_one_listing", dispatch)

    with pytest.raises(BatchIncompleteError) as excinfo:
        fetch_all_listings([LISTING_A, broken, LISTING_C])

    assert [path.name for path, _ in excinfo.value.succeeded] == [
        "raw_111.json", "raw_333.json"]
    assert "SKU-X/444" in excinfo.value.failures
    assert "url" in excinfo.value.failures["SKU-X/444"]
