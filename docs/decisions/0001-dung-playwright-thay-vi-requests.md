# ADR 0001 — Dùng Playwright thay vì requests

- **Trạng thái:** Đã chốt
- **Ngày:** 2026-08-23
- **Nguồn:** `Day_1_Shopee_Scape.txt` mục 2, `Day_2_.txt` câu hỏi 1

## Bối cảnh

Shopee là web kiểu SPA (Single Page Application).

Khi mở link sản phẩm, cái HTML đầu tiên trình duyệt nhận được gần như trống rỗng,
không có giá, không có tên sản phẩm. Sau đó JavaScript chạy, gọi ngầm một API để
lấy dữ liệu, rồi mới "vẽ" giá/tên lên màn hình.

## Các phương án

**Tải HTML thô** bằng `requests.get()` — sẽ không thấy gì cả, vì phần giá và tên
sản phẩm chỉ xuất hiện sau khi JavaScript chạy xong.

**Dùng Playwright** — nó chạy được JavaScript như trình duyệt thật.

## Quyết định

Dùng Playwright.

Bước chuẩn bị: `playwright install chromium` — tải bản trình duyệt Chromium thật
(một bộ binary riêng, không phải Chrome đang dùng để lướt web) về máy, để thư viện
Playwright điều khiển nó chạy ngầm.

## Hệ quả

Đây là câu trả lời cho câu hỏi phỏng vấn *"Tại sao lúc đầu chọn Playwright mà
không phải requests/BeautifulSoup?"*.

Đổi lại, phải nuôi một trình duyệt thật: nặng hơn, chậm hơn, và mở ra một loạt vấn
đề chống bot mà `requests` không có — xem `docs/issues.md` Issue 1–4 và ADR 0004.
