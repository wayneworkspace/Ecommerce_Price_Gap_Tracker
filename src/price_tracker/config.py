"""Cấu hình dùng chung cho MỌI nguồn dữ liệu.

Cố ý không chứa gì riêng của Shopee: thứ riêng từng nguồn nằm ở
sources/<nguồn>/settings.py, còn danh sách SKU là dữ liệu nên nằm ở
config/skus.yaml.
"""
from pathlib import Path
import os

import yaml
from dotenv import load_dotenv


def find_project_root() -> Path:
    """Dò ngược lên tìm thư mục chứa pyproject.toml.

    Không dùng parents[n] nữa. Con số n phụ thuộc file này nằm sâu mấy cấp,
    nên mỗi lần đổi cấu trúc thư mục là nó sai — và sai IM LẶNG, không có
    exception nào: RAW_DIR.mkdir(parents=True) vẫn chạy ngon, chỉ là tạo
    data/raw ở ngoài repo. Crawler báo thành công còn bạn ngồi tự hỏi sao
    data/raw trong repo vẫn rỗng.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError(
        "Không tìm thấy gốc project — không có pyproject.toml ở bất kỳ thư mục cha nào."
    )


PROJECT_ROOT = find_project_root()

# Đọc .env ở gốc project (không commit — xem .env.example để biết cần khai gì).
# Chỉ định rõ đường dẫn thay vì để load_dotenv() tự đoán, để chạy đúng dù bạn
# đứng ở thư mục nào khi gọi script.
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

# Dùng bởi: scripts/shopee_login.py, sources/shopee/extract.py
# Đường dẫn folder profile Chrome persistent (giữ session đăng nhập qua các lần chạy).
# Lấy từ .env thay vì hard-code, vì đây là đường dẫn tuyệt đối riêng của từng máy
# — hard-code sẽ gãy ngay nếu người khác (hoặc chính bạn trên máy khác) chạy code.
USER_DATA_DIR = os.getenv("SHOPEE_USER_DATA_DIR")


def require_user_data_dir() -> str:
    """Kiểm tra USER_DATA_DIR ngay trước khi thực sự cần mở browser.

    Cố tình KHÔNG raise ở tầng module: config bị import gián tiếp bởi
    transform.py và cả test suite, mà hai chỗ đó không hề đụng tới browser.
    Raise lúc import sẽ làm pytest không collect nổi trên máy chưa có .env
    (clone sạch, CI) — hỏng đúng thứ đáng lẽ phải chạy được ở mọi nơi vì nó
    không cần mạng lẫn browser.
    """
    if not USER_DATA_DIR:
        raise RuntimeError(
            "Thiếu biến SHOPEE_USER_DATA_DIR trong file .env — xem .env.example để biết cách khai báo."
        )
    return USER_DATA_DIR


# Dùng bởi: extract.py (ghi file), transform.py (đọc file)
# Nơi lưu JSON thô, y nguyên nguồn trả về, chưa qua xử lý
RAW_DIR = PROJECT_ROOT / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# Dùng bởi: transform.py (ghi file)
# Nơi lưu JSON đã đóng gói theo schema chung (sku_id, seller_id, price...)
STAGING_DIR = PROJECT_ROOT / "data" / "staging"
STAGING_DIR.mkdir(parents=True, exist_ok=True)

# Danh sách SKU cần theo dõi — dữ liệu, không phải code (xem config/skus.yaml)
SKUS_FILE = PROJECT_ROOT / "config" / "skus.yaml"


def load_skus() -> list[dict]:
    """Đọc toàn bộ danh sách SKU từ config/skus.yaml."""
    with SKUS_FILE.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_sku_source(sku: str, source: str) -> dict:
    """Lấy phần cấu hình của một SKU trên một nguồn cụ thể.

    Ném KeyError kèm tên file thay vì trả None: thiếu cấu hình là lỗi cấu hình,
    phải vỡ ngay và chỉ đúng chỗ cần sửa, chứ không để None trôi xuống rồi nổ
    ở một chỗ chẳng liên quan.
    """
    for entry in load_skus():
        if entry.get("sku") == sku:
            try:
                return entry["sources"][source]
            except KeyError:
                raise KeyError(
                    f"SKU {sku!r} chưa khai báo nguồn {source!r} trong {SKUS_FILE}"
                ) from None
    raise KeyError(f"Không tìm thấy SKU {sku!r} trong {SKUS_FILE}")
