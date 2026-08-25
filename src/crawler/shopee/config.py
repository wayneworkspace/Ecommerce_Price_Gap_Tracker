from pathlib import Path

USER_DATA_DIR = r"C:\Users\ADMIN\OneDrive\Desktop\Personal_Tracker\1_End-to-End Project\Shopee Profile"

RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

TARGET_ITEM_ID = "6765591429"  # lấy từ URL: .i<shop_id>.<item_id>
PRODUCT_URL = r"https://shopee.vn/Chu%E1%BB%99t-gaming-c%C3%B3-d%C3%A2y-Logitech-G102-Lightsync-T%C3%B9y-ch%E1%BB%89nh-RGB-6-n%C3%BAt-l%E1%BA%ADp-tr%C3%ACnh-nh%E1%BA%B9-i.52679373.6765591429"
