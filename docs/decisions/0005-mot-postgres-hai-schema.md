# ADR 0005 — Một Postgres, hai schema, không dựng instance metadata riêng

- **Trạng thái:** Đã chốt (kế hoạch tuần 3–6)
- **Nguồn:** `README.md` mục Architecture (Design note)

## Bối cảnh

Bản thiết kế ban đầu (sơ đồ kiến trúc) có một instance Postgres riêng đóng vai
"Orchestration Metadata Store".

## Các phương án

**Hai instance Postgres tách biệt:** một cho log điều phối, một cho warehouse.

**Một instance Postgres, hai schema.**

## Quyết định

Cắt instance riêng đó. Chạy **một instance Postgres duy nhất** với hai schema:
`airflow` (metadata của orchestrator) và `warehouse` (raw/staging/mart).

Lý do: Airflow vốn đã cần sẵn một database metadata để theo dõi các lần chạy DAG,
nên dựng thêm một Postgres thứ hai riêng cho "orchestration logs" là làm trùng đúng
việc đó mà không thêm được năng lực gì.

## Hệ quả

Ba lớp trong schema `warehouse`:

- **raw** — output cào để nguyên, mỗi lần cào một dòng (append-only, không dedup).
- **staging** — đã cast, ép kiểu, khử trùng lặp bằng `unique_key` merge của dbt
  (không có "dedup DAG" riêng — xem ADR 0006).
- **mart** — `price_gap_pct` và các view tổng hợp tính bằng window function, sẵn sàng
  cho Power BI.

Không dùng object store riêng: khối lượng dữ liệu (vài SKU, khoảng 1 MB/tháng) không
đủ để biện minh. Cũng không Kafka, không Spark — thêm chúng vào mà không có lý do
chính là kiểu thất bại mà dự án này cố tình tránh.
