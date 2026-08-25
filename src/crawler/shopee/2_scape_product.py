import json
from patchright.sync_api import sync_playwright
from config import USER_DATA_DIR
from datetime import datetime, timezone
from config import USER_DATA_DIR, RAW_DIR, TARGET_ITEM_ID, PRODUCT_URL


captured = {"data": None, "url": None}


def on_response(response):
    try:
        ct = response.headers.get("content-type") or ""
        if "application/json" not in ct:
            return
        body = response.json()
    except Exception:
        return

    text = json.dumps(body)
    if TARGET_ITEM_ID in text and '"price"' in text:
        captured["data"] = body
        captured["url"] = response.url


with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        channel="chrome",
        headless=False,   # đổi thành True khi chạy quen tay, không cần xem UI nữa
    )

    page = browser.new_page()
    page.on("response", on_response)

    page.goto(PRODUCT_URL)
    page.wait_for_timeout(6000)

if captured["data"]:
    item = captured["data"]["data"]["item"]
    record = {
        "sku_id": item.get("item_id"),
        "seller_id": item.get("shop_id"),
        "product_name": item.get("title"),
        "price": (item.get("price") or item.get("price_min") or 0) / 100_000,
        "url": PRODUCT_URL,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RAW_DIR / f"shopee_{record['sku_id']}_{ts}.json"
    out_path.write_text(json.dumps(
        record, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Đã lưu: {out_path}")
    print(json.dumps(record, indent=2, ensure_ascii=False))
else:
    print("Không bắt được data — session có thể đã hết hạn, thử chạy lại login_shopee.py")

    browser.close()
