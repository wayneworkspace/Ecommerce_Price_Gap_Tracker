# ADR 0002 — Bắt API JSON thay vì dùng CSS selector

- **Trạng thái:** Đã chốt
- **Ngày:** 2026-08-23
- **Nguồn:** `Day_1_Shopee_Scape.txt` mục 2 ("Hai cách để lấy được data"), `Day_2_.txt` câu hỏi 3

## Bối cảnh

Có hai cách để lấy được data ra khỏi trang Shopee.

(CSS — Cascading Style Sheets — là ngôn ngữ dùng để định dạng giao diện của trang
web: màu sắc, kích thước chữ, khoảng cách, vị trí các phần tử.)

## Các phương án

**Cách 1 — CSS selector.** Đợi trang load xong, rồi dùng CSS selector kiểu
`page.query_selector(".price-class")` để đọc chữ hiển thị trên màn hình.

Nhược điểm: Shopee đổi tên class CSS thường xuyên → selector vỡ liên tục, code chạy
được hôm nay mai không chạy nữa.

**Cách 2 — "nghe lén" luôn request mạng mà trình duyệt gửi đi.** Khi Shopee load
giá, nó gọi một API nội bộ (URL có chứa `pdp/get_pc`), API đó trả về JSON sạch sẽ
chứa toàn bộ data (giá, tên, seller...). Playwright cho phép gắn một "tai nghe" vào
mọi response mạng bằng `page.on("response", ...)`, thấy response nào khớp URL đó thì
đọc thẳng JSON ra — không cần đoán CSS class gì cả.

## Quyết định

Chọn cách 2. Ổn định hơn nhiều.

## Hệ quả

Đây là câu trả lời cho câu hỏi phỏng vấn *"Nếu Shopee đổi cấu trúc trang, code em
có tự vỡ không? Xử lý sao?"* — câu hỏi thật sự quan trọng với vai trò DE.

Ghi chú thêm từ lúc triển khai (`docs/issues.md`): lọc response bằng những key chung
chung như `"price"` + `"name"` là không đáng tin, vì Shopee load rất nhiều API JSON
không liên quan (flash sale, gợi ý sản phẩm) mà cũng chứa đúng những key đó cho sản
phẩm KHÁC. Phải lọc theo `item_id` lấy từ URL. Về sau còn phải siết thêm: khớp cả
đường dẫn `pdp/get_pc` lẫn `item_id`.

Cách bắt "tai nghe" `page.on("response", ...)` mô tả ở đây sau đó bị thay bằng
`page.expect_response()` — xem `docs/issues.md` Issue 5. Lý do là lỗi lệch dispatch,
không phải vì hướng bắt API sai.
