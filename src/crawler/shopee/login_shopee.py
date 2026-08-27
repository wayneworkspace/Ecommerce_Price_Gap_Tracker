from patchright.sync_api import sync_playwright
from config import require_user_data_dir

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        user_data_dir=require_user_data_dir(),
        channel="chrome",
        headless=False,
    )

    page = browser.new_page()
    page.goto("https://shopee.vn/buyer/login")

    input("Đăng nhập bằng tay xong (kể cả giải captcha nếu có) thì Enter ở đây...")

    print("Đã lưu session vào profile — có thể đóng và chạy scrape_product.py bình thường.")
    browser.close()
