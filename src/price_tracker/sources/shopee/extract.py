from price_tracker.config import (
    RAW_DIR, require_user_data_dir, load_source_listings, listing_label)
from price_tracker.sources.shopee.settings import PDP_API_PATH, RAW_FILE_PREFIX
from price_tracker.common.retry import shopee_scrape_retry
from price_tracker.sources.shopee.payload import (
    find_item, describe_problem, format_timestamp)
from patchright.sync_api import sync_playwright, Error as PWError
from pathlib import Path
from datetime import datetime, timezone
import logging
import random
import time
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

# Nghỉ ngẫu nhiên GIỮA hai LISTING. README (mục Challenges) đã hứa "randomized
# 3-8s delay between requests" từ lâu mà code chưa từng có dòng nào — với đúng
# 1 listing thì không ai kiểm chứng được, còn từ listing thứ 2 trở đi thì đó là
# khác biệt giữa tôn trọng ToS và nện liên tiếp vào cùng một endpoint.
# Đơn vị là LISTING chứ không phải SKU: mỗi listing là một request thật, hai
# listing của cùng một SKU vẫn là hai lần gõ cửa Shopee.
# Ngẫu nhiên chứ không cố định: khoảng cách đều tăm tắp giữa các request là dấu
# hiệu tự động hoá dễ nhận ra nhất.
DELAY_BETWEEN_LISTINGS_MIN_S = 3.0
DELAY_BETWEEN_LISTINGS_MAX_S = 8.0


class FetchFailedError(Exception):
    """Raise khi một lần thử cào không lấy được JSON dùng được.

    Mọi lỗi 'có thể thử lại được' đều phải quy về đúng loại này, vì đây là
    loại duy nhất (cùng PWError) mà tenacity chịu retry — xem retry.py.
    """
    pass


class BatchIncompleteError(Exception):
    """Mẻ đã chạy hết danh sách listing nhưng có listing không lấy được.

    Mang theo cả phần THÀNH CÔNG lẫn phần hỏng, để hàm gọi vẫn xử lý tiếp được
    những gì đã có rồi mới báo đỏ — thay vì mất trắng cả mẻ vì một listing.

    `succeeded` cố ý để chung chung: khâu cào bỏ vào đây các cặp
    (đường dẫn raw, cấu hình listing), còn main() sau khi đóng gói xong thì bỏ
    vào các record. Cả hai đều chỉ cần đúng một thứ — ĐẾM được — để mẫu số
    trong thông báo là kích thước mẻ thật. Truyền list rỗng vào đây sẽ ra
    "1/1 listing hỏng" trong khi thực tế là 1/5, đọc log tưởng sập cả mẻ.
    """

    def __init__(self, succeeded: list, failures: dict[str, str]):
        self.succeeded = succeeded
        self.failures = failures
        detail = "; ".join(f"{label}: {why}" for label, why in failures.items())
        super().__init__(
            f"{len(failures)}/{len(failures) + len(succeeded)} listing hỏng — {detail}"
        )


def sleep_between_listings() -> None:
    """Nghỉ ngẫu nhiên trước khi sang listing kế tiếp.

    Tách thành hàm riêng thay vì gọi thẳng time.sleep() trong vòng lặp, để test
    thay được nó mà không phải ngồi chờ thật.
    """
    seconds = random.uniform(DELAY_BETWEEN_LISTINGS_MIN_S, DELAY_BETWEEN_LISTINGS_MAX_S)
    logger.info("Nghỉ %.1fs trước listing tiếp theo", seconds)
    time.sleep(seconds)


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

    Gọi hàm này trong khối try của fetch_one_listing() là cố ý: FetchFailedError ném ra
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


def dump_debug_evidence(page, debug_dir: Path | None = None,
                        item_id: str | None = None) -> None:
    """Lưu HTML + ảnh màn hình ngay khi page còn sống, trước khi đóng.

    Tên file kèm item_id vì giờ mẻ chạy nhiều listing: dấu thời gian chỉ chính
    xác tới giây, hai listing hỏng trong cùng một giây sẽ ghi đè bằng chứng của
    nhau — mà đây đúng là thứ duy nhất phân biệt được bị captcha hay bị tường
    đăng nhập. Kể cả không đè nhau thì nhìn tên file cũng phải biết nó của
    listing nào.
    """
    if debug_dir is None:
        debug_dir = RAW_DIR.parent / "debug"

    stem = f"fail_{item_id}" if item_id else "fail"
    ts = format_timestamp(datetime.now(timezone.utc))

    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"{stem}_{ts}.html").write_text(
            page.content(timeout=DEBUG_CAPTURE_TIMEOUT_MS), encoding="utf-8")
        logger.info("Đã lưu HTML debug -> %s", debug_dir / f"{stem}_{ts}.html")
    except Exception as exc:
        logger.warning("Không lưu được HTML debug (%s: %s)",
                       type(exc).__name__, exc)

    try:
        page.screenshot(path=str(debug_dir / f"{stem}_{ts}.png"), full_page=True,
                        timeout=DEBUG_CAPTURE_TIMEOUT_MS)
        logger.info("Đã lưu ảnh debug -> %s", debug_dir / f"{stem}_{ts}.png")
    except Exception as exc:
        logger.warning("Không chụp được ảnh debug (%s: %s)",
                       type(exc).__name__, exc)


@shopee_scrape_retry(PWError, FetchFailedError)
def fetch_one_listing(browser, listing_cfg: dict) -> Path:
    """Cào đúng MỘT listing trên một browser đã mở sẵn.

    Đơn vị là listing, không phải SKU: một SKU có thể được nhiều người bán rao,
    mỗi người một item_id và một trang riêng — tức mỗi listing là một request
    thật tới Shopee.

    Nhận browser từ ngoài chứ không tự mở: cả mẻ dùng chung một
    launch_persistent_context(), vì hàm đó khoá USER_DATA_DIR và mở/đóng liên
    tục là tự chuốc rủi ro tranh lock — mà lịch sử Issue 1-3 cho thấy hễ dính
    chuyện profile là dính captcha.

    Decorator retry nằm ở ĐÂY chứ không ở fetch_all_listings(): một listing
    trục trặc tạm thời chỉ đáng thử lại chính nó, không đáng khởi động lại
    Chrome và cào lại từ đầu những listing đã xong.
    """
    # Kiểm field bắt buộc Ở ĐÂY chứ không ở tầng đọc cấu hình: hỏng một dòng
    # trong skus.yaml chỉ nên giết listing của nó. Ném ở tầng cấu hình là chết
    # cả mẻ trước khi browser kịp mở.
    #
    # ValueError cố ý KHÔNG nằm trong danh sách tenacity retry (PWError,
    # FetchFailedError): thiếu url thì thử lại 3 lần vẫn thiếu url.
    missing = [k for k in ("item_id", "url") if not listing_cfg.get(k)]
    if missing:
        raise ValueError(
            f"Listing {listing_cfg!r} thiếu field bắt buộc: {', '.join(missing)} "
            f"— sửa trong config/skus.yaml"
        )

    item_id = str(listing_cfg["item_id"])
    product_url = listing_cfg["url"]
    label = listing_label(listing_cfg)

    page = None
    try:
        page = browser.new_page()
        page.bring_to_front()
        page.on("console", lambda msg: logger.warning(
            "CONSOLE[%s]: %s", msg.type, msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: logger.warning(
            "PAGE ERROR: %s", exc))

        logger.info("Bắt đầu cào %s", label)

        with page.expect_response(
            lambda r: PDP_API_PATH in r.url and item_id in r.url,
            timeout=RESPONSE_TIMEOUT_MS,
        ) as response_info:
            page.goto(product_url, wait_until="domcontentloaded",
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
        item = validate_payload_or_fail(data)

        # Đối chiếu item_id trong payload với item_id đã cấu hình. Bộ lọc
        # response chỉ so KHỚP CHUỖI trên URL, nên về lý một response khác có
        # id chứa id của mình như chuỗi con vẫn lọt. Hậu quả rất khó lần: file
        # mang tên shopee_raw_<id_mình>_*.json nhưng bên trong là sản phẩm
        # khác, rồi record đi tiếp xuống mart với sai người bán, sai giá.
        # Rẻ để kiểm, đắt để phát hiện về sau.
        actual_item_id = item.get("item_id")
        if actual_item_id is not None and str(actual_item_id) != item_id:
            raise FetchFailedError(
                f"Bắt nhầm response: cấu hình item_id={item_id} nhưng payload "
                f"trả về item_id={actual_item_id}"
            )

    except (PWError, FetchFailedError) as exc:
        logger.warning("Lần thử này fail (%s): %s", label, exc)
        if page is not None:
            dump_debug_evidence(page, item_id=item_id)

        if isinstance(exc, FetchFailedError):
            raise
        raise FetchFailedError(
            f"Không bắt được API response chứa item_id={item_id} "
            f"(goto {GOTO_TIMEOUT_MS}ms / expect_response {RESPONSE_TIMEOUT_MS}ms): {exc}"
        ) from exc

    finally:
        # Đóng PAGE, không đóng browser: browser thuộc về cả mẻ, do
        # fetch_all_listings() sở hữu và dọn. Không đóng page thì mỗi listing
        # (và mỗi lần retry) để lại một tab sống, ăn RAM tới hết mẻ.
        if page is not None:
            try:
                page.close()
            except Exception as exc:
                logger.warning("Đóng page lỗi (%s: %s)",
                               type(exc).__name__, exc)

    # MỘT lời gọi now() duy nhất, dùng cho cả tên file lẫn field scraped_at.
    # Gọi hai lần thì hai giá trị lệch nhau vài mili-giây — nhỏ, nhưng nó phá
    # đúng cái bất biến mà transform dựa vào: tên file và envelope phải nói
    # cùng một thời điểm, vì transform đọc envelope trước rồi mới tới tên file.
    scraped_at = datetime.now(timezone.utc)
    out_path = RAW_DIR / \
        f"{RAW_FILE_PREFIX}_{item_id}_{format_timestamp(scraped_at)}.json"

    # scraped_at nằm trong file chứ không chỉ ở tên file: tên file có thể bị
    # đổi khi copy/backup, còn nội dung thì đi đâu cũng mang theo thời điểm cào.
    out_path.write_text(
        json.dumps({"data": data, "url": product_url,
                    "scraped_at": scraped_at.isoformat()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("Saved raw -> %s", out_path)
    return out_path


def fetch_all_listings(
    listing_configs: list[dict] | None = None,
) -> list[tuple[Path, dict]]:
    """Cào cả danh sách listing trong một phiên browser duy nhất.

    Trả về từng cặp (đường dẫn file raw, cấu hình listing) chứ không chỉ đường
    dẫn: khâu đóng gói cần lại `sku` và `is_official` từ cấu hình, mà hai thứ
    đó KHÔNG có trong payload Shopee trả về. Trả mỗi Path thì hàm gọi phải tự
    dò ngược từ tên file về cấu hình — mong manh và thừa.

    Ba quyết định đáng nói, để người đọc sau biết đây là lựa chọn chứ không
    phải vô tình:

    1. Browser mở một lần cho cả mẻ (xem fetch_one_listing).

    2. Một listing hỏng KHÔNG làm dừng mẻ. Shopee chặn theo từng trang sản phẩm
       chứ không chặn cả tài khoản, nên mất listing đầu danh sách mà bỏ luôn
       phần còn lại là tự vứt dữ liệu còn lấy được.

    3. Nhưng cuối mẻ vẫn NÉM nếu có bất kỳ listing nào hỏng — sau khi đã thử
       hết. Lấy được bao nhiêu giữ bấy nhiêu, nhưng Airflow phải thấy đỏ: một
       mẻ thiếu listing mà báo xanh thì thủng dữ liệu chỉ lộ ra ở dashboard,
       hàng tuần sau. Ngưỡng này có thể nới về sau (ví dụ chỉ đỏ khi hỏng quá
       X%), khi đã biết Shopee thật sự hành xử thế nào — hiện chưa đủ dữ liệu
       để chọn ngưỡng đó, nên chọn cái nghiêm nhất.
    """
    if listing_configs is None:
        listing_configs = load_source_listings("shopee")

    user_data_dir = require_user_data_dir()
    fetched: list[tuple[Path, dict]] = []
    failures: dict[str, str] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir,
            channel="chrome",
            headless=False,
        )
        try:
            for index, listing_cfg in enumerate(listing_configs):
                # Nghỉ GIỮA các listing, không nghỉ trước cái đầu tiên: nghỉ
                # trước khi làm gì cả chỉ làm mỗi lần chạy chậm thêm mà không
                # giãn được request nào.
                if index > 0:
                    sleep_between_listings()

                label = listing_label(listing_cfg)
                try:
                    fetched.append(
                        (fetch_one_listing(browser, listing_cfg), listing_cfg))
                # Bắt rộng ở đây là cố ý: mục đích của khối này là CÔ LẬP một
                # listing hỏng. Lỗi cấu hình (thiếu key url) cũng chỉ nên giết
                # listing đó chứ không giết cả mẻ. Dùng Exception chứ không
                # BaseException để Ctrl-C vẫn dừng được ngay.
                except Exception as exc:
                    failures[label] = f"{type(exc).__name__}: {exc}"
                    logger.warning("Bỏ qua listing %s sau khi đã retry hết: %s",
                                   label, exc)
        finally:
            try:
                browser.close()
            except Exception as exc:
                logger.warning("Đóng browser lỗi (%s: %s)",
                               type(exc).__name__, exc)

    logger.info("Xong mẻ: %d listing ok, %d listing hỏng",
                len(fetched), len(failures))

    if failures:
        raise BatchIncompleteError(fetched, failures)

    return fetched


if __name__ == "__main__":
    fetch_all_listings()
