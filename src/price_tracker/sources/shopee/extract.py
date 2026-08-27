from price_tracker.config import RAW_DIR, require_user_data_dir
from price_tracker.sources.shopee.settings import TARGET_ITEM_ID, PRODUCT_URL
from price_tracker.common.retry import shopee_scrape_retry
from price_tracker.sources.shopee.payload import (
    find_item, describe_problem, format_timestamp)
from patchright.sync_api import sync_playwright, Error as PWError
from pathlib import Path
from datetime import datetime, timezone
import logging
import json


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s"
)
logger = logging.getLogger(__name__)

# Bằng chứng chẩn đoán thôi, không đáng chờ lâu: mặc định Playwright là 30s, mà
# khối này chạy lại ở CẢ 3 lần retry -> đốt thêm 90s mỗi lần fetch hỏng.
# Đặt cho CẢ content() lẫn screenshot(): chỉ chặn screenshot thì content()
# vẫn tự do treo 30s, coi như chưa chặn được gì.
DEBUG_CAPTURE_TIMEOUT_MS = 10_000

GOTO_TIMEOUT_MS = 30_000
RESPONSE_TIMEOUT_MS = 40_000


class FetchFailedError(Exception):
    """Raise khi một lần thử cào không lấy được JSON dùng được.

    Mọi lỗi 'có thể thử lại được' đều phải quy về đúng loại này, vì đây là
    loại duy nhất (cùng PWError) mà tenacity chịu retry — xem retry.py.
    """
    pass


def extract_json_or_fail(response) -> dict:
    try:
        return response.json()
    except Exception as exc:
        raise FetchFailedError(
            f"Không đọc được JSON từ response {response.url}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


def validate_payload_or_fail(payload: dict) -> dict:
    """Kiểm payload có dùng được không, TRẢ VỀ item, ném FetchFailedError nếu không.

    Đây là lỗ hổng thật của bản trước: extract_json_or_fail() chỉ đảm bảo body
    PARSE được thành JSON. Nhưng khi bị chặn hoặc throttle, Shopee trả HTTP 200
    kèm một JSON hoàn toàn hợp lệ dạng {"error": 1, "data": null} — parse ngon
    lành, nên nó lọt qua và bị coi là thành công. Hậu quả dây chuyền:

      - tenacity không retry, dù đây đúng là ca đáng retry nhất (chặn tạm thời);
      - file độc được ghi vào data/raw/ và trở thành file mới nhất, nên
        transform.py nhặt đúng nó cho MỌI lần chạy sau — hỏng một lần, hỏng mãi.

    Gọi hàm này trong khối try của fetch_raw() là cố ý: FetchFailedError ném ra
    sẽ rơi vào đúng except sẵn có, nên tự động được lưu bằng chứng debug (nhìn
    HTML là biết ngay bị tường login hay captcha) rồi mới ném tiếp cho tenacity.
    Và vì ném trước khi tới lệnh ghi file, không có gì ra đĩa cả.
    """
    item = find_item(payload)
    if item is None:
        raise FetchFailedError(
            f"Shopee trả JSON hợp lệ nhưng không dùng được — {describe_problem(payload)}"
        )
    return item


def dump_debug_evidence(page, debug_dir: Path | None = None) -> None:

    if debug_dir is None:
        debug_dir = RAW_DIR.parent / "debug"

    ts = format_timestamp(datetime.now(timezone.utc))

    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"fail_{ts}.html").write_text(
            page.content(timeout=DEBUG_CAPTURE_TIMEOUT_MS), encoding="utf-8")
        logger.info("Đã lưu HTML debug -> %s", debug_dir / f"fail_{ts}.html")
    except Exception as exc:
        logger.warning("Không lưu được HTML debug (%s: %s)",
                       type(exc).__name__, exc)

    try:
        page.screenshot(path=str(debug_dir / f"fail_{ts}.png"), full_page=True,
                        timeout=DEBUG_CAPTURE_TIMEOUT_MS)
        logger.info("Đã lưu ảnh debug -> %s", debug_dir / f"fail_{ts}.png")
    except Exception as exc:
        logger.warning("Không chụp được ảnh debug (%s: %s)",
                       type(exc).__name__, exc)


@shopee_scrape_retry(PWError, FetchFailedError)
def fetch_raw() -> Path:

    user_data_dir = require_user_data_dir()

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir,
            channel="chrome",
            headless=False,
        )
        page = None
        try:
            page = browser.new_page()
            page.bring_to_front()
            page.on("console", lambda msg: logger.warning(
                "CONSOLE[%s]: %s", msg.type, msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: logger.warning(
                "PAGE ERROR: %s", exc))

            with page.expect_response(
                lambda r: "pdp/get_pc" in r.url and TARGET_ITEM_ID in r.url,
                timeout=RESPONSE_TIMEOUT_MS,
            ) as response_info:
                page.goto(PRODUCT_URL, wait_until="domcontentloaded",
                          timeout=GOTO_TIMEOUT_MS)

            response = response_info.value
            logger.info("Captured API response: %s", response.url)

            data = extract_json_or_fail(response)

            # Cân nhắc rồi bỏ: khôi phục guard content-type == application/json
            # mà bản trước từng có. Nó không chặn thêm được ca nào — body không
            # phải JSON thì extract_json_or_fail() đã ném, còn JSON sai hình
            # dạng thì validate_payload_or_fail() bắt. Nó chỉ có thể chặn một
            # response vừa có content-type lạ, vừa parse ra JSON, vừa đúng shape
            # — tức là dữ liệu vẫn dùng được. Thêm một lớp không chặn thêm gì
            # chỉ làm code dài ra.
            validate_payload_or_fail(data)

        except (PWError, FetchFailedError) as exc:
            logger.warning("Lần thử này fail: %s", exc)
            if page is not None:
                dump_debug_evidence(page)

            if isinstance(exc, FetchFailedError):
                raise
            raise FetchFailedError(
                f"Không bắt được API response chứa item_id={TARGET_ITEM_ID} "
                f"(goto {GOTO_TIMEOUT_MS}ms / expect_response {RESPONSE_TIMEOUT_MS}ms): {exc}"
            ) from exc

        finally:
            try:
                browser.close()
            except Exception as exc:
                logger.warning("Đóng browser lỗi (%s: %s)",
                               type(exc).__name__, exc)

    # MỘT lời gọi now() duy nhất, dùng cho cả tên file lẫn field scraped_at.
    # Gọi hai lần thì hai giá trị lệch nhau vài mili-giây — nhỏ, nhưng nó phá
    # đúng cái bất biến mà transform dựa vào: tên file và envelope phải nói
    # cùng một thời điểm, vì transform đọc envelope trước rồi mới tới tên file.
    scraped_at = datetime.now(timezone.utc)
    out_path = RAW_DIR / \
        f"shopee_raw_{TARGET_ITEM_ID}_{format_timestamp(scraped_at)}.json"

    # scraped_at nằm trong file chứ không chỉ ở tên file: tên file có thể bị
    # đổi khi copy/backup, còn nội dung thì đi đâu cũng mang theo thời điểm cào.
    out_path.write_text(
        json.dumps({"data": data, "url": PRODUCT_URL,
                    "scraped_at": scraped_at.isoformat()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("Saved raw -> %s", out_path)
    return out_path


if __name__ == "__main__":
    fetch_raw()
