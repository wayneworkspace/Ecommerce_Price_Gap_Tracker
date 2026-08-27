# ADR 0004 — Dùng `launch_persistent_context()` thay vì export/import cookie

- **Trạng thái:** Đã chốt
- **Nguồn:** `docs/issues.md` Issue 1, 2, 3

## Bối cảnh

Shopee chuyển hướng mọi phiên ẩn danh (`is_logged_in=false`) thẳng sang trang tường
đăng nhập khi truy cập trực tiếp URL trang sản phẩm.

Đã xác nhận đây không phải vấn đề riêng của Playwright: cùng một chặn đó xảy ra trên
trình duyệt điện thoại thật, mạng khác (5G), không có tự động hoá nào — loại trừ khả
năng bị nhận dạng bot ở tầng này.

## Các phương án

**Export cookie ra `storage_state.json` rồi nạp lại vào một context Chromium mới.**
Cookie xuất theo cách này mang những token phiên (ví dụ `SPC_SEC_SI`) bị buộc vào dấu
vân tay thiết bị tại thời điểm đăng nhập. Một instance Chromium mới, tách biệt, có
dấu vân tay khác với cái đã tạo ra cookie — Shopee đánh dấu sự lệch đó là đáng ngờ và
bật tường captcha.

**Giữ mọi thứ trong cùng một profile `launch_persistent_context()`.**

## Quyết định

Bỏ hẳn việc export/import cookie thành file riêng. Khởi chạy trình duyệt bằng
`launch_persistent_context()` trỏ vào một `user_data_dir` riêng, đăng nhập bằng tay
một lần trong profile đó; cookie/session sau đó được giữ tự động qua các lần chạy.

Nhờ vậy dấu vân tay trình duyệt giữ nguyên giữa phiên đăng nhập và mọi lần cào sau —
không còn chỗ lệch nào để Shopee đánh dấu.

## Hệ quả

`user_data_dir` là đường dẫn tuyệt đối riêng của từng máy nên phải nằm trong `.env`
(`SHOPEE_USER_DATA_DIR`), không hard-code vào code. Bản thân thư mục profile chứa
session đăng nhập thật nên phải nằm ngoài repo và trong `.gitignore`.

Việc đăng nhập lần đầu là thao tác tay, không tự động hoá được — đó là lý do
`scripts/shopee_login.py` tồn tại và có `input()` chờ Enter, tức nó là script chạy
tay chứ không phải thư viện.

Chú ý: cách này vẫn chưa đủ để thoát captcha ở lần đăng nhập đầu tiên trên profile
sạch (Issue 3). Thứ giải quyết được phần đó là `patchright` — xem Issue 4.
