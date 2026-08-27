# ADR 0007 — `tenacity` và `pytest` giải quyết hai việc khác nhau

- **Trạng thái:** Đã chốt
- **Ngày:** 2026-08-26
- **Nguồn:** `Day_3.txt`

## Bối cảnh

Hai công cụ dễ bị gộp làm một khi nghĩ về "chống lỗi", nhưng chúng nhắm vào hai loại
lỗi hoàn toàn khác nhau.

## Các phương án

Không phải chọn một trong hai — đây là ghi lại ranh giới giữa chúng, để sau này không
dùng nhầm cái nọ cho việc của cái kia.

## Quyết định

**`tenacity`** — chống chịu lỗi mạng thật, chập chờn thật, pipeline nghẽn thật (khi
chạy production/thật sự cào dữ liệu).

**`pytest`** — bắt lỗi logic code (khi code sai, viết test giả lập input để kiểm tra
logic đúng/sai, không cần chạm vào mạng thật).

## Hệ quả

Cấu hình `tenacity` dùng chung nằm ở `src/price_tracker/common/retry.py`, để mọi nguồn
dùng lại một cấu hình thay vì chép lại nhiều lần.

Test nằm ở `tests/`, soi gương cấu trúc `src/`, và không chạm mạng thật — object giả
đưa vào là đủ.

Ranh giới này quyết định một câu hỏi rất cụ thể trong code: exception nào nên quy về
`FetchFailedError` để `tenacity` thử lại, và exception nào phải để nó vỡ ra ngoài vì
đó là bug logic — retry một bug logic chỉ làm nó chạy sai ba lần.
