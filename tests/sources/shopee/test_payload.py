"""Test cho payload.py — biết thế nào là một payload Shopee dùng được.

Đây là nơi duy nhất mô tả hình dạng payload, nên cũng là nơi duy nhất cần test
hình dạng đó. extract.py và transform.py đều dựa vào nó.
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
    """Ca nguy hiểm nhất: Shopee trả HTTP 200 + JSON HỢP LỆ khi chặn/throttle.

    JSON hợp lệ nên khâu parse không bắt được. Không chặn ở đây thì file độc
    được ghi ra data/raw/ và phá mọi lần chạy transform sau đó."""
    poisoned = {"error": 1, "error_msg": "server busy", "data": None}

    assert find_item(poisoned) is None


def test_find_item_treats_error_zero_as_success():
    """error=0 là 'không lỗi', đừng nhầm với error=1.

    Vì thế phải kiểm giá trị thật chứ không phải chỉ kiểm key có tồn tại."""
    ok = {"error": 0, "error_msg": None,
          "data": {"item": {"item_id": 1}}}

    assert find_item(ok) == {"item_id": 1}


def test_find_item_rejects_payload_with_null_data():
    assert find_item({"error": None, "data": None}) is None


def test_find_item_rejects_payload_without_item():
    assert find_item({"error": None, "data": {"account": {}}}) is None


def test_find_item_rejects_empty_item():
    """item rỗng thì cũng vô dụng như không có item."""
    assert find_item({"error": None, "data": {"item": {}}}) is None


def test_find_item_rejects_non_dict_payload():
    assert find_item(None) is None
    assert find_item("not a payload") is None


# ---------------------------------------------------------------------------
# find_item_in_raw — đọc NỘI DUNG FILE, phải chấp nhận cả 2 khuôn file raw.
# ---------------------------------------------------------------------------

from price_tracker.sources.shopee.payload import find_item_in_raw, describe_raw_problem


def test_find_item_in_raw_reads_the_current_envelope_shape():
    envelope = {"data": HEALTHY, "url": "https://shopee.vn/x"}

    assert find_item_in_raw(envelope) == {"item_id": 6765591429,
                                          "price": 48_900_000_000}


def test_find_item_in_raw_still_reads_old_bare_payload_files():
    """File cào bằng bản code TRƯỚC khi có envelope là payload trần.

    data/raw/ đang có file thật dạng này. Nó chứa dữ liệu hoàn toàn dùng được
    nên không có lý do gì coi là hỏng rồi bỏ qua."""
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
