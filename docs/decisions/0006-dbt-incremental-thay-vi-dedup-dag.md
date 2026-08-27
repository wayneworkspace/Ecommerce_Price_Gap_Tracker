# ADR 0006 — Chống trùng bằng dbt incremental thay vì một "dedup DAG" riêng

- **Trạng thái:** Đã chốt (kế hoạch tuần 5–6)
- **Nguồn:** `README.md` mục Challenges & Solutions

## Bối cảnh

Chạy lại pipeline không được phép nhân đôi các dòng trong `raw`.

## Các phương án

**Một DAG riêng chuyên đi xoá bản ghi trùng.**

**Xử lý ở tầng transform bằng dbt incremental model (`unique_key` merge/upsert).**

## Quyết định

Xử lý ở tầng transform bằng dbt incremental model. Một DAG riêng mà việc duy nhất
của nó là xoá bản ghi trùng thì thừa, khi chiến lược merge sẵn có của dbt đã giải
quyết xong.

## Hệ quả

`raw` giữ đúng tính chất append-only: một lần cào là một dòng, không sửa, không xoá —
nên vẫn dùng làm bằng chứng kiểm toán được.

dbt đồng thời gánh luôn phần kiểm tra chất lượng dữ liệu (`not_null`,
`accepted_range`) và lineage, thứ mà SQL rời rạc viết trong Python không có, và tránh
xử lý lại toàn bộ lịch sử ở mỗi lần chạy.

Trường hợp giá bị lỗi hoặc null sau khi cast thì đi vào bảng `quarantine` chứ không
âm thầm chui vào `mart` — một lỗi cast lọt xuống mart mà không ai biết thì bày ra
lớp mart để làm gì.
