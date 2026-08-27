from pathlib import Path
import os
from dotenv import load_dotenv

# Đọc file .env ở gốc project (không commit lên git — xem .env.example
# để biết cần khai báo những biến nào). Chỉ định rõ đường dẫn thay vì để
# load_dotenv() tự đoán, để chạy đúng dù bạn đứng ở thư mục nào khi gọi script.
load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / ".env")

# Dùng bởi: login_shopee.py, fetch_raw.py
# Đường dẫn folder profile Chrome persistent (giữ session đăng nhập qua các lần chạy).
# Lấy từ .env thay vì hard-code, vì đây là đường dẫn tuyệt đối riêng của từng máy
# — hard-code sẽ gãy ngay nếu người khác (hoặc chính bạn trên máy khác) chạy code.
USER_DATA_DIR = os.getenv("SHOPEE_USER_DATA_DIR")


def require_user_data_dir() -> str:
    """Kiểm tra USER_DATA_DIR ngay trước khi thực sự cần mở browser.

    Cố tình KHÔNG raise ở tầng module: config.py bị import gián tiếp bởi
    build_record.py và cả test suite, mà hai chỗ đó không hề đụng tới
    browser. Raise lúc import sẽ làm pytest không collect nổi trên máy
    chưa có .env (clone sạch, CI) — hỏng đúng thứ đáng lẽ phải chạy được
    ở mọi nơi vì nó không cần mạng lẫn browser.
    """
    if not USER_DATA_DIR:
        raise RuntimeError(
            "Thiếu biến SHOPEE_USER_DATA_DIR trong file .env — xem .env.example để biết cách khai báo."
        )
    return USER_DATA_DIR


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
