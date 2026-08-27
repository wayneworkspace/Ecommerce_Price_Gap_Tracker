"""Test cho extract.py — chỉ phần bóc JSON và lưu bằng chứng debug.

Hai hàm này được tách ra khỏi fetch_one_listing() chính là để test được mà không cần
mở browser: chúng chỉ nhận vào object có .json() / .screenshot(), nên đưa
object giả vào là đủ. Bản thân fetch_one_listing() không test ở đây vì nó bắt buộc
phải mở Chrome thật bằng session thật.
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
    """Object giả thay cho patchright Response — chỉ cần có .url và .json()."""

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
    """Ca thật hay gặp nhất: session hết hạn -> Shopee 302 sang tường login,
    patchright ném Error('Response body is unavailable for redirect responses').

    Đây KHÔNG phải JSONDecodeError. Nếu không convert, nó thoát ra khỏi cả
    khối except lẫn bộ lọc của tenacity -> không retry, browser không đóng."""
    response = _FakeResponse(
        raises=PWError("Response body is unavailable for redirect responses"))

    with pytest.raises(FetchFailedError):
        extract_json_or_fail(response)


def test_extract_json_converts_json_decode_error_to_fetch_failed():
    response = _FakeResponse(raises=json.JSONDecodeError("Expecting value", "", 0))

    with pytest.raises(FetchFailedError):
        extract_json_or_fail(response)


def test_extract_json_converts_unicode_decode_error_to_fetch_failed():
    """Body không phải UTF-8 -> .decode() ném UnicodeDecodeError, cũng không
    phải JSONDecodeError."""
    response = _FakeResponse(
        raises=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"))

    with pytest.raises(FetchFailedError):
        extract_json_or_fail(response)


def test_extract_json_keeps_original_exception_as_cause():
    """Convert nhưng không được nuốt nguyên nhân gốc, nếu không thì lúc đọc
    log chỉ thấy 'fetch failed' mà không biết vì sao."""
    original = PWError("No resource with given identifier found")
    response = _FakeResponse(raises=original)

    with pytest.raises(FetchFailedError) as excinfo:
        extract_json_or_fail(response)

    assert excinfo.value.__cause__ is original


class _ExplodingPage:
    """Page giả mà mọi thao tác đều ném — mô phỏng lúc target đã crash/đóng,
    đúng lúc ta cần chụp bằng chứng nhất."""

    def screenshot(self, **kwargs):
        raise PWTimeout("Timeout 30000ms exceeded taking screenshot")

    def content(self):
        raise PWError("Target page, context or browser has been closed")


def test_dump_debug_evidence_never_raises(tmp_path):
    """Khối chụp bằng chứng không được phép ném ra ngoài: nếu nó ném, nó sẽ
    thay mất exception chẩn đoán gốc và làm browser.close() không chạy."""
    dump_debug_evidence(_ExplodingPage(), debug_dir=tmp_path)  # không được ném


def test_retry_covers_the_exceptions_fetch_one_listing_actually_raises():
    """Chốt lại phần đấu dây: loại exception fetch_one_listing ném ra phải nằm
    đúng trong danh sách tenacity chịu retry, nếu không retry chỉ là trang trí."""
    retry_config = fetch_one_listing.retry

    assert retry_config.stop.max_attempt_number == 3
    assert FetchFailedError in retry_config.retry.exception_types
    assert PWError in retry_config.retry.exception_types


def test_validate_payload_or_fail_passes_a_healthy_payload():
    payload = {"error": None, "data": {"item": {"item_id": 6765591429}}}

    assert validate_payload_or_fail(payload) == {"item_id": 6765591429}


def test_validate_payload_or_fail_rejects_shopee_error_payload():
    """Lớp 1 của C1: chặn TRƯỚC khi ghi ra data/raw/.

    Phải là FetchFailedError để tenacity retry — đây đúng là ca đáng retry
    nhất (bị chặn/throttle tạm thời), mà bản cũ lại coi là thành công."""
    payload = {"error": 1, "error_msg": "server busy", "data": None}

    with pytest.raises(FetchFailedError) as excinfo:
        validate_payload_or_fail(payload)

    msg = str(excinfo.value)
    assert "1" in msg and "server busy" in msg, \
        "Phải kèm error/error_msg thật của Shopee, đừng nuốt mất manh mối"


# ---------------------------------------------------------------------------
# fetch_all_listings — điều phối cả mẻ N SKU.
#
# Ở đây thay hẳn fetch_one_listing bằng hàm giả: mục tiêu là kiểm phần ĐIỀU PHỐI
# (lặp, cô lập lỗi, nghỉ giữa SKU, ném cuối mẻ), không phải kiểm lại phần cào —
# phần đó đã có test riêng ở trên. Nhờ vậy test không mở browser, không chạm
# mạng, và không cần .env.
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
    """Đủ để thay sync_playwright(): vừa là context manager, vừa có .chromium."""

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
    """Chặn mọi thứ chạm browser thật + chặn cả yêu cầu phải có .env."""
    browser = _FakeBrowser()
    fake_pw = _FakePlaywright(browser)
    monkeypatch.setattr(extract_module, "sync_playwright", lambda: fake_pw)
    monkeypatch.setattr(extract_module, "require_user_data_dir",
                        lambda: "C:/fake/profile")
    monkeypatch.setattr(extract_module, "sleep_between_listings", lambda: None)
    return browser, fake_pw


def test_fetch_all_listings_keeps_going_when_one_sku_fails(tmp_path, monkeypatch):
    """SKU hỏng ở GIỮA danh sách không được làm mất các SKU sau nó.

    Đây là hành vi dễ làm sai nhất và hỏng im lặng nhất: nếu sai, chỉ tới lúc
    Shopee chặn đúng SKU đầu danh sách mới lộ ra, và lúc đó mất cả mẻ."""
    _patch_browser(monkeypatch)
    seen = []

    def fake_fetch_one(browser, sku_cfg):
        seen.append(sku_cfg["sku"])
        if sku_cfg["sku"] == "SKU-B":
            raise FetchFailedError("Shopee chặn SKU-B")
        return tmp_path / f"raw_{sku_cfg['item_id']}.json"

    monkeypatch.setattr(extract_module, "fetch_one_listing", fake_fetch_one)

    with pytest.raises(BatchIncompleteError) as excinfo:
        fetch_all_listings([LISTING_A, LISTING_B, LISTING_C])

    assert seen == ["SKU-A", "SKU-B", "SKU-C"], "Phải thử HẾT, không dừng ở SKU hỏng"
    assert [path.name for path, _ in excinfo.value.succeeded] == ["raw_111.json", "raw_333.json"]


def test_fetch_all_listings_reports_which_sku_failed_and_why(monkeypatch):
    _patch_browser(monkeypatch)

    def fake_fetch_one(browser, sku_cfg):
        raise FetchFailedError("Shopee trả error=1, error_msg='blocked'")

    monkeypatch.setattr(extract_module, "fetch_one_listing", fake_fetch_one)

    with pytest.raises(BatchIncompleteError) as excinfo:
        fetch_all_listings([LISTING_A])

    assert "SKU-A/111" in str(excinfo.value), "Nhãn phải có cả sku lẫn item_id"
    assert "blocked" in str(excinfo.value), "Nuốt lý do thì đọc log xong vẫn không biết vì sao"
    assert "SKU-A/111" in excinfo.value.failures


def test_fetch_all_listings_returns_paths_when_every_sku_works(tmp_path, monkeypatch):
    _patch_browser(monkeypatch)
    monkeypatch.setattr(extract_module, "fetch_one_listing",
                        lambda browser, cfg: tmp_path / f"raw_{cfg['item_id']}.json")

    fetched = fetch_all_listings([LISTING_A, LISTING_B])

    assert [path.name for path, _ in fetched] == ["raw_111.json", "raw_222.json"]
    assert [cfg["sku"] for _, cfg in fetched] == ["SKU-A", "SKU-B"], \
        "Phải trả kèm cấu hình: sku/is_official không có trong payload Shopee"


def test_fetch_all_listings_opens_the_browser_once_for_the_whole_batch(tmp_path, monkeypatch):
    """Mở/đóng Chrome mỗi SKU là tự chuốc rủi ro lock trên USER_DATA_DIR —
    mà lịch sử Issue 1-3 cho thấy dính chuyện profile là dính captcha."""
    browser, fake_pw = _patch_browser(monkeypatch)
    monkeypatch.setattr(extract_module, "fetch_one_listing",
                        lambda b, cfg: tmp_path / f"raw_{cfg['item_id']}.json")

    fetch_all_listings([LISTING_A, LISTING_B, LISTING_C])

    assert fake_pw.launch_count == 1, "3 SKU nhưng chỉ được mở browser 1 lần"
    assert browser.close_count == 1


def test_fetch_all_listings_closes_the_browser_even_if_every_sku_fails(monkeypatch):
    browser, _ = _patch_browser(monkeypatch)

    def boom(browser_, cfg):
        raise FetchFailedError("hỏng")

    monkeypatch.setattr(extract_module, "fetch_one_listing", boom)

    with pytest.raises(BatchIncompleteError):
        fetch_all_listings([LISTING_A, LISTING_B])

    assert browser.close_count == 1, "Không đóng là Chrome giữ lock profile cho lần chạy sau"


def test_fetch_all_listings_waits_between_skus_but_not_before_the_first(tmp_path, monkeypatch):
    """README hứa 'randomized 3-8s delay between requests' — phải có thật.

    GIỮA các SKU, không phải TRƯỚC SKU đầu: nghỉ trước khi làm gì cả chỉ làm
    mỗi lần chạy chậm thêm mà chẳng giãn được request nào."""
    _patch_browser(monkeypatch)
    calls = []
    monkeypatch.setattr(extract_module, "sleep_between_listings",
                        lambda: calls.append("slept"))
    monkeypatch.setattr(extract_module, "fetch_one_listing",
                        lambda b, cfg: tmp_path / f"raw_{cfg['item_id']}.json")

    fetch_all_listings([LISTING_A, LISTING_B, LISTING_C])

    assert len(calls) == 2, "3 SKU -> 2 lần nghỉ (giữa 1-2 và 2-3), không phải 3"


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
    """Lỗi tạm của 1 SKU không đáng khởi động lại Chrome cho cả mẻ."""
    assert hasattr(fetch_one_listing, "retry"), "fetch_one_listing phải là hàm được tenacity bọc"
    assert fetch_one_listing.retry.stop.max_attempt_number == 3
    assert not hasattr(fetch_all_listings, "retry"), \
        "Bọc retry ở cả mẻ là cào lại cả những SKU đã thành công"


def test_sleep_between_listings_stays_inside_the_promised_window(monkeypatch):
    """Kiểm khoảng nghỉ đúng 3-8s như README hứa, mà không ngủ thật."""
    slept = []
    monkeypatch.setattr(extract_module.time, "sleep", slept.append)

    for _ in range(50):
        extract_module.sleep_between_listings()

    assert all(extract_module.DELAY_BETWEEN_LISTINGS_MIN_S <= s <= extract_module.DELAY_BETWEEN_LISTINGS_MAX_S
               for s in slept)


# ---------------------------------------------------------------------------
# main.run_batch — ghép cào + đóng gói, gom lỗi của cả hai khâu.
# ---------------------------------------------------------------------------

from price_tracker.sources.shopee import main as main_module


def test_run_batch_keeps_records_from_the_skus_that_worked(monkeypatch, tmp_path):
    """Mẻ thiếu SKU vẫn phải giữ lại record của những SKU đã cào được."""
    good = tmp_path / "raw_111.json"

    monkeypatch.setattr(
        main_module, "fetch_all_listings",
        lambda cfgs: (_ for _ in ()).throw(
            BatchIncompleteError([(good, LISTING_A)],
                                 {"SKU-B/222": "FetchFailedError: bị chặn"})))
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
    """Cào được nhưng đóng gói hỏng thì SKU đó vẫn là không có dữ liệu hôm nay."""
    raw = tmp_path / "raw_111.json"
    monkeypatch.setattr(main_module, "fetch_all_listings",
                        lambda cfgs: [(raw, LISTING_A)])

    def boom(path, cfg):
        raise ValueError("File raw hỏng")

    monkeypatch.setattr(main_module, "build_record", boom)

    records, failures = main_module.run_batch([LISTING_A])

    assert records == []
    # Nhãn phải giống hệt nhãn khâu cào dùng, không phải tên file raw — hai
    # khâu đặt tên khác nhau là hết đối chiếu theo listing được.
    assert "SKU-A/111" in failures
    assert "File raw hỏng" in failures["SKU-A/111"]


def test_a_listing_missing_url_only_kills_that_listing(tmp_path, monkeypatch):
    """Gõ thiếu `url:` trong skus.yaml chỉ được giết đúng listing đó.

    Đây là chỗ trước đây nói một đằng làm một nẻo: comment hứa cô lập lỗi cấu
    hình, nhưng việc kiểm field lại nằm ở tầng đọc YAML — chạy TRƯỚC khi browser
    mở — nên quên một dòng url là mất trắng cả mẻ."""
    _patch_browser(monkeypatch)
    broken = {"sku": "SKU-X", "item_id": "444"}          # thiếu url

    monkeypatch.setattr(
        extract_module, "fetch_one_listing",
        extract_module.fetch_one_listing.__wrapped__
        if hasattr(extract_module.fetch_one_listing, "__wrapped__")
        else extract_module.fetch_one_listing)

    real_fetch = extract_module.fetch_one_listing

    def dispatch(browser, cfg):
        if cfg is broken:
            return real_fetch(browser, cfg)          # để nó tự ném ValueError
        return tmp_path / f"raw_{cfg['item_id']}.json"

    monkeypatch.setattr(extract_module, "fetch_one_listing", dispatch)

    with pytest.raises(BatchIncompleteError) as excinfo:
        fetch_all_listings([LISTING_A, broken, LISTING_C])

    assert [path.name for path, _ in excinfo.value.succeeded] == [
        "raw_111.json", "raw_333.json"]
    assert "SKU-X/444" in excinfo.value.failures
    assert "url" in excinfo.value.failures["SKU-X/444"]
