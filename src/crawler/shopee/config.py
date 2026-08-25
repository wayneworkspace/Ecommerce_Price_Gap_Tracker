from pathlib import Path

# Dùng bởi: login_shopee.py, fetch_raw.py
# Đường dẫn folder profile Chrome persistent (giữ session đăng nhập qua các lần chạy)
USER_DATA_DIR = r"C:\Users\ADMIN\OneDrive\Desktop\Personal_Tracker\1_End-to-End Project\Shopee Profile"

# Dùng bởi: fetch_raw.py (ghi file), build_record.py (đọc file)
# Nơi lưu JSON thô, y nguyên Shopee trả về, chưa qua xử lý
RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# Dùng bởi: build_record.py (ghi file)
# Nơi lưu JSON đã đóng gói theo schema riêng của mình (sku_id, seller_id, price...)
STAGING_DIR = Path(__file__).resolve().parents[3] / "data" / "staging"
STAGING_DIR.mkdir(parents=True, exist_ok=True)

# Dùng bởi: fetch_raw.py
# item_id lấy từ URL sản phẩm (.i<shop_id>.<item_id>) — dùng để lọc đúng response API,
# tránh bắt nhầm API khác (như vụ flash_sale_get_items trước đây)
TARGET_ITEM_ID = "6765591429"

# Dùng bởi: fetch_raw.py
# URL sản phẩm Shopee cần cào
PRODUCT_URL = r"https://shopee.vn/Chu%E1%BB%99t-gaming-c%C3%B3-d%C3%A2y-Logitech-G102-Lightsync-T%C3%B9y-ch%E1%BB%89nh-RGB-6-n%C3%BAt-l%E1%BA%ADp-tr%C3%ACnh-nh%E1%BA%B9-i.52679373.6765591429"
