"""What a usable Shopee payload looks like, and what a raw filename carries.

Hợp đồng về file raw: payload Shopee trông thế nào, và tên file mang gì.

Tách riêng vì hai chỗ cần đúng kiến thức này mà không được phụ thuộc nhau:
extract.py (chặn trước khi ghi ra đĩa) và transform.py (bỏ qua file đã hỏng).
Nhét vào một trong hai thì bên còn lại phải import chéo — mà transform.py cố ý
không được kéo theo patchright, đó là lý do có extra `crawler` riêng.

Khuôn thật, lấy từ file trong data/raw/:

    {"bff_meta": {...}, "error": null, "error_msg": null,
     "data": {"item": {...}, "account": {...}, ...}}

extract.py bọc nó thành envelope trước khi ghi:

    {"data": <payload trên>, "url": ..., "scraped_at": "2026-08-27T05:55:22Z"}
"""
import re
from datetime import datetime, timezone

# Dấu thời gian trong TÊN file raw: shopee_raw_<item_id>_20260827T055522Z.json
# extract.py dùng để đặt tên, transform.py dùng để đọc ngược ra thời điểm cào
# với file cũ chưa có scraped_at trong envelope. Hai bên phải dùng CHUNG một
# hằng số, lệch nhau là tên file ghi một kiểu, đọc một kiểu.
RAW_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_RAW_TIMESTAMP_PATTERN = re.compile(r"(\d{8}T\d{6}Z)")


def format_timestamp(moment: datetime) -> str:
    """Format a UTC timestamp for a raw filename.

    Đóng dấu thời gian để đặt tên file. Luôn quy về UTC trước."""
    return moment.astimezone(timezone.utc).strftime(RAW_TIMESTAMP_FORMAT)


def find_scraped_at(raw) -> str | None:
    """Read scraped_at from the envelope, or None if unusable.

    Đọc scraped_at từ envelope, None nếu không có hoặc không đọc được.

    Có kiểm tra parse được chứ không chỉ kiểm tra "là chuỗi khác rỗng": một
    giá trị rác vẫn là chuỗi, và nó sẽ đi thẳng vào record rồi xuống warehouse.
    Trả None khi rác để tụt xuống nguồn kế tiếp (tên file) — file bị sửa tay
    hay hỏng phần envelope thì tên file thường vẫn còn nguyên.

    Trả lại dạng đã chuẩn hoá để mọi record dùng chung một định dạng, dù
    envelope ghi kiểu 'Z' hay '+00:00'.
    """
    if not isinstance(raw, dict):
        return None
    value = raw.get("scraped_at")
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Thiếu tzinfo thì coi là UTC: extract.py luôn ghi kèm offset, nên file
    # không có offset là file lạ — nhưng đoán UTC vẫn đúng hơn là đoán giờ máy
    # đang chạy transform, vì máy đó có thể ở múi giờ khác máy đã cào.
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def scraped_at_from_filename(name: str) -> str | None:
    """Recover the scrape time from a filename.

    Suy ra thời điểm cào từ tên file, None nếu tên không theo quy ước.

    Dùng cho file cào trước khi envelope có scraped_at — data/raw/ đang có
    file thật thuộc loại đó, coi chúng là hỏng là tự vứt dữ liệu còn tốt.

    Tìm bằng regex chứ không cắt chuỗi theo vị trí: tên file có nhiều dấu `_`
    và cắt theo thứ tự sẽ im lặng nhận nhầm khi quy ước đặt tên đổi.
    """
    match = _RAW_TIMESTAMP_PATTERN.search(name)
    if match is None:
        return None
    try:
        moment = datetime.strptime(match.group(1), RAW_TIMESTAMP_FORMAT)
    except ValueError:
        return None
    return moment.replace(tzinfo=timezone.utc).isoformat()


def find_item(payload) -> dict | None:
    """Return the item block, or None if Shopee refused us.

    Trả về block `item`, hoặc None nếu payload này không dùng được.

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
    """Say in one phrase why a payload is unusable.

    Mô tả ngắn gọn payload hỏng ở đâu, để nhét vào thông báo lỗi/log.

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
    """Return the item block from a raw file, either envelope shape.

    Lấy item từ NỘI DUNG một file raw — chấp nhận cả hai khuôn file.

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
    """Say in one phrase why a raw file is unusable.

    Mô tả vì sao nội dung một file raw không dùng được.

    Phân biệt hai khuôn bằng key "url": chỉ envelope mới có. Nếu không phân biệt
    thì với payload trần ta sẽ đi mô tả nhầm lớp bên trong và báo "thiếu item"
    trong khi lỗi thật là Shopee trả error.
    """
    if not isinstance(raw, dict):
        return f"nội dung file không phải dict mà là {type(raw).__name__}"
    if "url" in raw and "data" in raw:
        return describe_problem(raw.get("data"))
    return describe_problem(raw)
