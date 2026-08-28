"""Shopee constants that hold for every SKU.

Thứ chỉ riêng Shopee mới có, và KHÔNG phụ thuộc vào SKU nào.

Tách khỏi config.py chung để khi thêm TikTok/Logitech, mỗi nguồn có
settings.py của riêng nó mà không ai giẫm chân ai.

Trước đây file này còn ghim cứng TARGET_ITEM_ID/PRODUCT_URL của đúng một SKU,
đọc từ skus.yaml ngay lúc import. Cách đó không lặp được: hằng số ở tầng module
thì cả tiến trình chỉ có một giá trị, nên muốn cào SKU thứ hai là phải sửa code.
Giờ cấu hình listing đi vào hàm dưới dạng tham số (xem extract.fetch_one_listing),
đây chỉ giữ lại phần đúng với mọi SKU.
"""

# API nội bộ Shopee gọi để lấy giá. Bắt response của đúng đường dẫn này thay vì
# đọc CSS selector — xem ADR 0002 và docs/issues.md Issue 5.
PDP_API_PATH = "pdp/get_pc"

# Tiền tố tên file raw. Dùng chung bởi extract.py (lúc ghi) và transform.py
# (lúc glob tìm lại), nên phải nằm một chỗ: hai bên lệch nhau một ký tự là
# transform không tìm thấy gì mà cũng chẳng có lỗi nào chỉ ra vì sao.
RAW_FILE_PREFIX = "shopee_raw"
