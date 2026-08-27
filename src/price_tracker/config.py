"""Cấu hình dùng chung cho MỌI nguồn dữ liệu.

Cố ý không chứa gì riêng của Shopee: thứ riêng từng nguồn nằm ở
sources/<nguồn>/settings.py, còn danh sách SKU là dữ liệu nên nằm ở
config/skus.yaml.
"""
from pathlib import Path
import logging
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


logger = logging.getLogger(__name__)

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
# Nơi lưu JSON đã đóng gói theo schema chung (sku, item_id, seller_id, price...)
STAGING_DIR = PROJECT_ROOT / "data" / "staging"
STAGING_DIR.mkdir(parents=True, exist_ok=True)

# Danh sách SKU cần theo dõi — dữ liệu, không phải code (xem config/skus.yaml)
SKUS_FILE = PROJECT_ROOT / "config" / "skus.yaml"


def load_skus() -> list[dict]:
    """Đọc toàn bộ danh sách SKU từ config/skus.yaml.

    Kiểm luôn hình dạng tài liệu. Sửa YAML thành mapping thay vì list là lỗi
    gõ nhầm rất dễ mắc, mà nếu không chặn thì vòng lặp phía dưới đi qua các
    key kiểu chuỗi rồi nổ AttributeError: 'str' object has no attribute 'get'
    — chẳng nói được gì về việc file cấu hình sai ở đâu.
    """
    with SKUS_FILE.open(encoding="utf-8") as f:
        parsed = yaml.safe_load(f)

    if not isinstance(parsed, list):
        raise ValueError(
            f"{SKUS_FILE} phải là một DANH SÁCH các SKU (mỗi mục bắt đầu bằng '- sku:'), "
            f"nhưng đọc ra {type(parsed).__name__}."
        )
    for i, entry in enumerate(parsed):
        if not isinstance(entry, dict):
            raise ValueError(
                f"{SKUS_FILE}: mục thứ {i + 1} phải là một khối key/value, "
                f"nhưng là {type(entry).__name__}: {entry!r}"
            )
    return parsed


def get_listings(sku: str, source: str) -> list[dict]:
    """Danh sách LISTING của một SKU trên một sàn.

    Trả list chứ không phải một dict: cùng một sản phẩm được nhiều người bán
    rao trên cùng một sàn, mỗi người một item_id. Chính chỗ đó mới đẻ ra được
    price gap — schema cũ mỗi nguồn một listing thì hoá ra so giá shop chính
    hãng với chính nó.

    Ném KeyError kèm tên file thay vì trả None: thiếu cấu hình là lỗi cấu hình,
    phải vỡ ngay và chỉ đúng chỗ cần sửa, chứ không để None trôi xuống rồi nổ
    ở một chỗ chẳng liên quan.
    """
    for entry in load_skus():
        if entry.get("sku") == sku:
            listings = (entry.get("sources") or {}).get(source)
            if not listings:
                raise KeyError(
                    f"SKU {sku!r} chưa khai báo listing nào cho nguồn {source!r} trong {SKUS_FILE}"
                )
            return _as_listing_list(sku, source, listings)
    raise KeyError(f"Không tìm thấy SKU {sku!r} trong {SKUS_FILE}")


def _as_listing_list(sku: str, source: str, listings) -> list[dict]:
    """Ép về list và kiểm HÌNH DẠNG, cố ý không kiểm nội dung từng listing.

    Ranh giới này có chủ đích. Hình dạng sai (mapping thay vì list, listing
    không phải khối key/value) là hỏng cả file cấu hình — không đọc tiếp được,
    phải ném. Còn một listing THIẾU FIELD thì chỉ hỏng đúng listing đó, và nó
    được xử lý ở tầng dưới (fetch_one_listing) để một dòng gõ nhầm chỉ giết
    listing của nó, không giết cả mẻ.

    Trước đây chỗ này ném luôn khi thiếu item_id/url, và thế là mâu thuẫn với
    chính lời hứa "cô lập từng listing": load_source_listings() chạy TRƯỚC khi
    mở browser, nên quên một dòng url là cả mẻ chết, kể cả những listing đã
    chạy tốt hàng tuần.
    """
    if not isinstance(listings, list):
        raise ValueError(
            f"{SKUS_FILE}: sources.{source} của SKU {sku!r} phải là danh sách listing "
            f"(mỗi listing bắt đầu bằng '- shop_id:'), nhưng là {type(listings).__name__}."
        )

    for listing in listings:
        if not isinstance(listing, dict):
            raise ValueError(
                f"{SKUS_FILE}: listing của SKU {sku!r} trên {source!r} phải là khối "
                f"key/value, nhưng là {type(listing).__name__}: {listing!r}"
            )
    return listings


def listing_label(listing_cfg: dict) -> str:
    """Nhãn nhận dạng một listing, dùng thống nhất ở log, tóm tắt và báo lỗi.

    Phải có CẢ sku lẫn item_id: hai listing của cùng một SKU mà chỉ ghi sku thì
    không biết cái nào hỏng; chỉ ghi item_id thì đọc log không biết là sản phẩm
    gì. Dùng chung một hàm để khâu cào và khâu transform không đặt tên khác
    nhau cho cùng một listing — khác nhau là hết đối chiếu được.
    """
    return f"{listing_cfg.get('sku')}/{listing_cfg.get('item_id')}"


def load_source_listings(source: str) -> list[dict]:
    """Mọi cặp (SKU, listing) của một sàn, đã trộn phẳng thành dict duy nhất.

    Đây là thứ vòng lặp cào dùng: lặp theo LISTING chứ không theo SKU, vì mỗi
    listing là một request thật tới sàn.

    Trộn phẳng vì hàm gọi chỉ cần đúng thế: item_id/url để cào, còn
    sku/is_official để nhét vào record. Bắt chúng tự lần vào
    entry["sources"][source][i]["item_id"] là rải kiến thức về hình dạng YAML
    ra khắp code.

    QUAN TRỌNG: `sku` phải đi kèm xuống tận record. Nó là khoá join tới
    reference_price ở mart layer — reference_price gắn với SKU logic, không
    gắn với listing. Không có nó thì không tính được price_gap_pct, tức mất
    toàn bộ mục đích của dự án.

    SKU chưa khai báo nguồn này thì BỎ QUA kèm warning, không ném: thêm TikTok
    cho một SKU không có nghĩa là các SKU còn lại phải dừng cào Shopee.
    """
    resolved: list[dict] = []

    for entry in load_skus():
        sku = entry.get("sku")
        listings = (entry.get("sources") or {}).get(source)
        if not listings:
            logger.warning(
                "SKU %r chưa khai báo listing nào cho nguồn %r trong %s — bỏ qua",
                sku, source, SKUS_FILE)
            continue

        for listing in _as_listing_list(sku, source, listings):
            # Phần riêng listing đặt sau nên nó thắng nếu trùng key — cấu hình
            # cụ thể phải đè cấu hình chung, không phải ngược lại.
            merged = {
                "sku": sku,
                "name": entry.get("name"),
                "reference_price": entry.get("reference_price"),
                **listing,
            }

            # is_official thiếu thì mặc định False, NHƯNG phải kêu lên. Để None
            # trôi xuống là nguy hiểm một chiều: mọi filter kiểu `WHERE
            # is_official` coi NULL là không-chính-hãng, nên quên đúng một dòng
            # `is_official: true` sẽ biến giá cửa hàng chính hãng thành giá
            # người bán lẻ — đảo ngược đúng câu hỏi dự án sinh ra để trả lời.
            if merged.get("is_official") is None:
                logger.warning(
                    "Listing %s/%s thiếu is_official trong %s — tạm coi là KHÔNG "
                    "chính hãng; nếu đây là cửa hàng chính hãng thì price gap sẽ sai",
                    sku, merged.get("item_id"), SKUS_FILE)
                merged["is_official"] = False

            resolved.append(merged)

    if not resolved:
        raise ValueError(
            f"Không SKU nào trong {SKUS_FILE} khai báo nguồn {source!r} — "
            f"không có gì để cào."
        )

    # Cảnh báo listing trùng. Thêm người bán mới bằng cách copy-paste khối cũ
    # rồi quên sửa item_id là lỗi rất dễ mắc với khuôn YAML này. Hậu quả kép:
    # gõ cửa Shopee hai lần cho cùng một trang (thừa, và không tôn trọng ToS),
    # và vì failures là dict khoá theo nhãn nên hai listing trùng mà cùng hỏng
    # sẽ gộp thành một dòng — đếm sai kích thước mẻ.
    seen: set[str] = set()
    for listing in resolved:
        label = listing_label(listing)
        if label in seen:
            logger.warning(
                "Listing %s xuất hiện nhiều lần trong %s — sẽ bị cào lặp, "
                "kiểm tra lại item_id", label, SKUS_FILE)
        seen.add(label)

    return resolved
