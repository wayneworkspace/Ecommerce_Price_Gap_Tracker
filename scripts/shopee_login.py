from patchright.sync_api import sync_playwright
from price_tracker.config import require_user_data_dir

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        user_data_dir=require_user_data_dir(),
        channel="chrome",
        headless=False,
    )

    page = browser.new_page()
    page.goto("https://shopee.vn/buyer/login")

    input("Press Enter here once you have logged in by hand (including any captcha)...")

    print("Session saved to the profile -- you can close this window and run: python -m price_tracker.sources.shopee.main")
    browser.close()
