from config import USER_DATA_DIR, RAW_DIR, TARGET_ITEM_ID, PRODUCT_URL
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
from patchright.sync_api import sync_playwright, TimeoutError as PWTimeout
from pathlib import Path
from datetime import datetime, timezone
import time
import logging
import json


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s"
)
logger = logging.getLogger(__name__)


class FetchFailedError(Exception):
    """Raise khi hết trang mà vẫn không bắt được đúng API response."""
    pass


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=3, max=30),
    retry=retry_if_exception_type((PWTimeout, FetchFailedError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def fetch_raw() -> Path:
    captured = {"data": None}

    def on_response(response):
        if captured["data"] is not None:
            return
        if TARGET_ITEM_ID in response.url:
            try:
                if "application/json" in (response.headers.get("content-type") or ""):
                    captured["data"] = response.json()
                    logger.info("Captured API response: %s", response.url)
            except Exception:
                pass  # body không phải JSON hợp lệ / đã bị tiêu thụ -> bỏ qua

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            channel="chrome",
            headless=False,
        )
        page = browser.new_page()
        page.bring_to_front()
        page.on("response", on_response)
        page.on("console", lambda msg: logger.warning(
            "CONSOLE[%s]: %s", msg.type, msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: logger.warning("PAGE ERROR: %s", exc))

        page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=30_000)
        # Chờ theo kiểu polling thay vì sleep cố định: kiểm tra mỗi 0.5s,
        # tối đa 15s — vừa nhanh khi mạng tốt, vừa chắc khi mạng chậm.
        max_wait = 25
        waited = 0.0
        while captured["data"] is None and waited < max_wait:
            time.sleep(0.5)
            waited += 0.5

        if captured["data"] is None:
            logger.warning("Hết %.1fs vẫn chưa bắt được API response", waited)
            # Lưu bằng chứng NGAY KHI page còn sống, trước khi đóng browser.
            debug_dir = RAW_DIR.parent / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            page.screenshot(
                path=str(debug_dir / f"fail_{ts}.png"), full_page=True)
            (debug_dir /
             f"fail_{ts}.html").write_text(page.content(), encoding="utf-8")

            browser.close()
            # Không bắt được response đúng item_id -> coi như lần thử này fail,
            # tenacity sẽ bắt exception này và tự retry.
            raise FetchFailedError(
                f"Không bắt được API response chứa item_id={TARGET_ITEM_ID}")

        browser.close()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RAW_DIR / f"shopee_raw_{TARGET_ITEM_ID}_{ts}.json"
    out_path.write_text(
        json.dumps(captured["data"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("Saved raw -> %s", out_path)
    return out_path


if __name__ == "__main__":
    fetch_raw()
