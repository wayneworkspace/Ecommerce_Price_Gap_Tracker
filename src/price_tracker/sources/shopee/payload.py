"""Hình dạng của một payload Shopee trả về, và thế nào là "dùng được".

Tách riêng vì hai chỗ cần đúng kiến thức này mà không được phụ thuộc nhau:
extract.py (chặn trước khi ghi ra đĩa) và transform.py (bỏ qua file đã hỏng).
Nhét vào một trong hai thì bên còn lại phải import chéo — mà transform.py cố ý
không được kéo theo patchright, đó là lý do có extra `crawler` riêng.

Khuôn thật, lấy từ file trong data/raw/:

    {"bff_meta": {...}, "error": null, "error_msg": null,
     "data": {"item": {...}, "account": {...}, ...}}
"""


def find_item(payload) -> dict | None:
    """Trả về block `item`, hoặc None nếu payload này không dùng được.

    Trả None thay vì ném: hai chỗ gọi cần phản ứng khác nhau — extract.py biến
    nó thành FetchFailedError để tenacity retry, còn find_latest_raw_file()
    chỉ bỏ qua file đó rồi đi tiếp.
    """
    if not isinstance(payload, dict):
        return None

    # Shopee KHÔNG trả HTTP 4xx/5xx khi chặn hay throttle — nó trả 200 kèm JSON
    # hợp lệ có "error" khác null. Vì thế phải soi giá trị `error`, không phải
    # soi HTTP status hay xem JSON có parse được không.
    #
    # Dùng truthiness chứ không phải `is not None`: error=0 nghĩa là KHÔNG lỗi,
    # gộp chung với null. Chỉ giá trị khác 0/null mới là lỗi thật.
    if payload.get("error"):
        return None

    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    item = data.get("item")
    # item rỗng cũng vô dụng như không có item, nên chặn luôn cả `{}`.
    if not isinstance(item, dict) or not item:
        return None

    return item


def describe_problem(payload) -> str:
    """Mô tả ngắn gọn payload hỏng ở đâu, để nhét vào thông báo lỗi/log.

    Kèm nguyên văn error/error_msg Shopee trả về — nuốt mất hai giá trị này là
    vứt đi manh mối tốt nhất để biết mình bị chặn hay chỉ gặp trục trặc tạm.
    """
    if not isinstance(payload, dict):
        return f"payload không phải dict mà là {type(payload).__name__}"
    if payload.get("error"):
        return (f"Shopee báo lỗi: error={payload.get('error')!r}, "
                f"error_msg={payload.get('error_msg')!r}")
    if not isinstance(payload.get("data"), dict):
        return f"payload['data'] không dùng được: {payload.get('data')!r}"
    return "payload['data']['item'] thiếu hoặc rỗng"


def find_item_in_raw(raw) -> dict | None:
    """Lấy item từ NỘI DUNG một file raw — chấp nhận cả hai khuôn file.

    extract.py hiện ghi envelope {"data": <payload>, "url": ...}, nhưng file cào
    bằng bản code trước khi có envelope là payload trần. data/raw/ đang có file
    thật thuộc cả hai loại. Cả hai đều chứa dữ liệu dùng được, nên coi khuôn cũ
    là "file hỏng" rồi bỏ qua là tự vứt đi dữ liệu còn tốt.
    """
    if isinstance(raw, dict) and "data" in raw:
        item = find_item(raw.get("data"))
        if item is not None:
            return item
    return find_item(raw)


def describe_raw_problem(raw) -> str:
    """Mô tả vì sao nội dung một file raw không dùng được.

    Phân biệt hai khuôn bằng key "url": chỉ envelope mới có. Nếu không phân biệt
    thì với payload trần ta sẽ đi mô tả nhầm lớp bên trong và báo "thiếu item"
    trong khi lỗi thật là Shopee trả error.
    """
    if not isinstance(raw, dict):
        return f"nội dung file không phải dict mà là {type(raw).__name__}"
    if "url" in raw and "data" in raw:
        return describe_problem(raw.get("data"))
    return describe_problem(raw)
