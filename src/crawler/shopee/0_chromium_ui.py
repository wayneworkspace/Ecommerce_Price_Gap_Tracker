# Open Chromium UI

# Terminal run
# pip install playwright
# playwright install chromium

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto(r"https://shopee.vn/Chu%E1%BB%99t-gaming-c%C3%B3-d%C3%A2y-Logitech-G102-Lightsync-T%C3%B9y-ch%E1%BB%89nh-RGB-6-n%C3%BAt-l%E1%BA%ADp-tr%C3%ACnh-nh%E1%BA%B9-i.52679373.6765591429?extraParams=%7B%22display_model_id%22%3A200911671614%2C%22model_selection_logic%22%3A3%7D")
    print("Title: ", page.title())
    input("Press Enter to close ...")
    browser.close()
