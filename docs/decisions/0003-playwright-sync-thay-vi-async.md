# ADR 0003 — Dùng API đồng bộ của Playwright thay vì async

- **Trạng thái:** Đã chốt
- **Ngày:** 2026-08-23
- **Nguồn:** `Day_1_Shopee_Scape.txt` mục 3

## Bối cảnh

Playwright có cả hai bản API: đồng bộ (sync) và bất đồng bộ (async). Phải chọn một.

## Các phương án

**async:** sử dụng khi cào nhiều (> 20 – 100 trang) web một lần. Giảm thời gian mở
đóng UI và cào song song nhiều web.

**sync:** dùng khi cào ít (khoảng dưới 20) trang web để tối ưu code, dễ test, không
chênh lệch thời gian nhiều giữa các web.

## Quyết định

Dùng bản đồng bộ.

## Hệ quả

Khối lượng hiện tại nằm đúng vùng "cào ít": `config/skus.yaml` mới có 1 SKU, kế hoạch
là 2–3 SKU × 3 kênh. Chưa chạm ngưỡng đáng để đổi sang async.

Nếu sau này số trang vượt ngưỡng đó thì đây là quyết định phải xem lại — và lúc đó
toàn bộ code gọi Playwright phải viết lại theo `async`/`await`.
