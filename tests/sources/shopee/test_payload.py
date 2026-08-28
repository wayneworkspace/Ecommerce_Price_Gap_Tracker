"""Tests for payload.py -- what makes a Shopee payload usable.

This is the only place that describes the payload shape, so it is also the only
place that needs to test it. Both extract.py and transform.py rely on it.
"""

from price_tracker.sources.shopee.payload import find_item

HEALTHY = {
    "bff_meta": {},
    "error": None,
    "error_msg": None,
    "data": {"item": {"item_id": 6765591429, "price": 48_900_000_000}},
}


def test_find_item_returns_item_for_a_healthy_payload():
    assert find_item(HEALTHY) == {"item_id": 6765591429, "price": 48_900_000_000}


def test_find_item_rejects_payload_where_shopee_signalled_an_error():
    """The most dangerous case: Shopee returns HTTP 200 + VALID JSON when it
    blocks or throttles.

    The JSON is valid, so the parsing stage cannot catch it. Without this guard
    the poisoned file is written to data/raw/ and breaks every later transform
    run."""
    poisoned = {"error": 1, "error_msg": "server busy", "data": None}

    assert find_item(poisoned) is None


def test_find_item_treats_error_zero_as_success():
    """error=0 means 'no error' -- do not confuse it with error=1.

    Which is why the check must look at the value, not merely at whether the key
    exists."""
    ok = {"error": 0, "error_msg": None,
          "data": {"item": {"item_id": 1}}}

    assert find_item(ok) == {"item_id": 1}


def test_find_item_rejects_payload_with_null_data():
    assert find_item({"error": None, "data": None}) is None


def test_find_item_rejects_payload_without_item():
    assert find_item({"error": None, "data": {"account": {}}}) is None


def test_find_item_rejects_empty_item():
    """An empty item is as useless as a missing one."""
    assert find_item({"error": None, "data": {"item": {}}}) is None


def test_find_item_rejects_non_dict_payload():
    assert find_item(None) is None
    assert find_item("not a payload") is None


# ---------------------------------------------------------------------------
# find_item_in_raw -- reads FILE CONTENT, so it must accept both raw shapes.
# ---------------------------------------------------------------------------

from price_tracker.sources.shopee.payload import find_item_in_raw, describe_raw_problem


def test_find_item_in_raw_reads_the_current_envelope_shape():
    envelope = {"data": HEALTHY, "url": "https://shopee.vn/x"}

    assert find_item_in_raw(envelope) == {"item_id": 6765591429,
                                          "price": 48_900_000_000}


def test_find_item_in_raw_still_reads_old_bare_payload_files():
    """Files scraped BEFORE the envelope existed are bare payloads.

    data/raw/ holds real files of that kind. They contain perfectly usable data,
    so there is no reason to treat them as broken and skip them."""
    assert find_item_in_raw(HEALTHY) == {"item_id": 6765591429,
                                         "price": 48_900_000_000}


def test_find_item_in_raw_rejects_a_poisoned_envelope():
    poisoned = {"data": {"error": 1, "error_msg": "blocked", "data": None},
                "url": "https://shopee.vn/x"}

    assert find_item_in_raw(poisoned) is None


def test_describe_raw_problem_reports_the_shopee_error_for_an_envelope():
    poisoned = {"data": {"error": 1, "error_msg": "blocked", "data": None},
                "url": "https://shopee.vn/x"}

    msg = describe_raw_problem(poisoned)

    assert "1" in msg and "blocked" in msg
