"""Thứ chỉ riêng Shopee mới có.

Tách khỏi config.py chung để khi thêm TikTok/Logitech, mỗi nguồn có
settings.py của riêng nó mà không ai giẫm chân ai.
"""
from price_tracker.config import get_sku_source

# Hiện mới theo dõi 1 SKU nên ghim cứng ở đây. Khi mở rộng lên nhiều SKU thì
# extract() nhận sku làm tham số và lặp qua load_skus() — đó là thay đổi hành
# vi nên để riêng, không gộp vào lần dọn cấu trúc này.
DEFAULT_SKU = "G102-LIGHTSYNC"

_shopee = get_sku_source(DEFAULT_SKU, "shopee")

# Dùng bởi: extract.py — lọc đúng response API, tránh bắt nhầm API khác
# (như vụ flash_sale_get_items trước đây)
TARGET_ITEM_ID = _shopee["item_id"]

# Dùng bởi: extract.py — URL sản phẩm cần cào
PRODUCT_URL = _shopee["url"]
