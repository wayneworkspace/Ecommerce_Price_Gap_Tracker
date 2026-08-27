from config import RAW_DIR, TARGET_ITEM_ID, PRODUCT_URL, require_user_data_dir
from retry import shopee_scrape_retry
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


def dump_debug_evidence(page, debug_dir: Path | None = None) -> None:

    if debug_dir is None:
        debug_dir = RAW_DIR.parent / "debug"

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"fail_{ts}.html").write_text(
            page.content(), encoding="utf-8")
        logger.info("Đã lưu HTML debug -> %s", debug_dir / f"fail_{ts}.html")
    except Exception as exc:
        logger.warning("Không lưu được HTML debug (%s: %s)",
                       type(exc).__name__, exc)

    try:
        page.screenshot(path=str(debug_dir / f"fail_{ts}.png"), full_page=True)
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

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RAW_DIR / f"shopee_raw_{TARGET_ITEM_ID}_{ts}.json"

    out_path.write_text(
        json.dumps({"data": data, "url": PRODUCT_URL},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("Saved raw -> %s", out_path)
    return out_path


if __name__ == "__main__":
    fetch_raw()
