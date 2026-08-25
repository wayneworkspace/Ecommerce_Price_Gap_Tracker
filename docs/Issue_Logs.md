## Issue Log — Shopee Playwright Scraper

### Issue 1: Blocked with "Login Required" (redirected to /verify/traffic/error)

**Evidence:**

Direct navigation via Playwright/Chromium:

![Issue 1 - direct navigation via Chromium](Issue_image/Issue_1_Gotolinkwithchromium.jpg)

Same block reproduced on a real phone, different network (5G), no automation involved — rules out bot fingerprinting as the cause at this layer:

![Issue 1 - same block on phone via 5G](Issue_image/Issue_1_Gotolinkwithphone.jpg)

**Reason:**
- Shopee redirects any anonymous session (`is_logged_in=false`) straight to a login-wall page when navigating directly to a product detail URL.
- Confirmed this is not Playwright-specific: the same block occurred on a real mobile browser, on a different network (5G), with no automation involved at all — ruling out bot fingerprinting as the cause at this layer.

**Solve:**
- Launch the browser with `launch_persistent_context()` instead of `launch()`, pointing to a dedicated `user_data_dir`.
- Log in manually once inside that persistent profile; cookies/session are then retained automatically across future runs — no login wall on subsequent visits.

---

### Issue 2: Blocked with anti-bot captcha (`/verify/captcha?anti_bot_tracking_id=...`) despite being logged in

**Reason:**
- Cookies exported via `storage_state.json` and re-injected into a *fresh* Chromium context carry session tokens (e.g. `SPC_SEC_SI`) that are tied to the device fingerprint present at login time.
- A new, separate Chromium instance has a different fingerprint than the one that created the cookies — Shopee flags the mismatch as suspicious and triggers a captcha wall.

**Solve:**
- Stop exporting/re-importing cookies as a separate file.
- Keep everything inside the same `launch_persistent_context()` profile so the browser fingerprint stays consistent between the login session and every later scrape — no fingerprint mismatch to flag.

---

### Issue 3: Blocked with anti-bot captcha even in a clean, fresh, real-Chrome persistent profile

**Evidence:**

![Issue 3 - anti-bot captcha wall](Issue_image/Issue_3_CaptchaAntiBot.jpg)

**Reason:**
- Even with real Chrome (`channel="chrome"`), a brand-new persistent profile, and no prior automation history, the captcha still triggered — this time at the very first login attempt.
- Root cause: Shopee's anti-bot system (URL pattern consistent with Akamai Bot Manager) detects the Chrome DevTools Protocol (CDP) connection itself — the mechanism Playwright uses to control the browser — regardless of fingerprint or login state.

**Solve:**
- Installed `playwright-stealth` (`stealth_sync(page)`), which patches multiple automation-detection signals at once (beyond the single `navigator.webdriver` flag), applied immediately after page creation and before any navigation.
- Combined with the persistent profile from Issue 1/2, this consistently reached the product page without triggering the anti-bot wall.
- **Update:** this fix was later replaced entirely — see Issue 4. `playwright-stealth` is no longer used in the final scraper.

---

### Issue 4: `playwright-stealth` avoids the captcha but breaks Shopee's own page JavaScript (price never renders)

**Evidence:**

Console showed a cascade of errors starting from the stealth patch itself, then breaking Shopee's own inline scripts:

```
Uncaught Error: skipping chrome loadtimes update, running in headfull mode
Uncaught ReferenceError: utils is not defined
Uncaught ReferenceError: opts is not defined
Uncaught ReferenceError: BROWSER_YEAR is not defined
```

The rendered page showed the product title, images, and breadcrumb (server-rendered, no JS required) correctly, but the price widget and shipping info stayed as empty grey placeholder boxes forever — the client-side fetch/render logic for those sections never ran.

**Reason:**
- `playwright-stealth`'s injected patch for `chrome.loadTimes` throws an uncaught error early in page execution on the current Chrome version (151.x) — the library is unmaintained and not tested against modern Chrome.
- That early crash breaks the execution order of Shopee's own inline `<script>` tags, so globals like `utils` and `opts` (defined by scripts that never got to run) are undefined for everything downstream — including the component responsible for fetching and rendering price.
- Removing `stealth_sync` fixes the JS crash but reintroduces Issue 3's CDP-detection captcha — a genuine dead end with this library.

**Solve:**
- Replaced `playwright` + `playwright-stealth` with **`patchright`** — a Playwright fork that avoids automation detection by patching at the binary/CDP level instead of injecting JavaScript into the page.
- No `stealth_sync()` call needed. Drop-in replacement: `from patchright.sync_api import sync_playwright` instead of `from playwright.sync_api import sync_playwright`.
- Result: no captcha, no JS errors, price and shipping info render correctly.

---

### Issue 5: Price API response consistently arrives too late — price widget never renders, despite no captcha and no JS errors (status: investigating)

**Evidence:**

Page renders cleanly — title, images, breadcrumb, and logged-in account all correct — but the price box stays an empty grey placeholder even after waiting 25 seconds:

![Issue 5 - price widget stays empty after 25s wait](Issue_image/Issue_5_PriceNeverLoads.png)

Console/page-error listeners (`page.on("console")`, `page.on("pageerror")`) were added to rule out a JS crash (the Issue 4 pattern) — no errors were logged, ruling that out. The `pdp/get_pc` API response for the correct `item_id` was still captured on some runs, but consistently *after* the wait cutoff (confirmed at both 15s and 25s cutoffs), not before it.

**Reason (not yet fully confirmed):**
- No captcha, no login wall, no JS error — the page and session are healthy by every check available so far.
- Leading hypothesis: Shopee applies a *soft* anti-scraping delay — rather than an outright block, repeated automated requests for the same `item_id` from the same account/profile in a short time window may get their price-API response deliberately slowed down. This would explain why the same script worked reliably on earlier runs (first few calls) but degraded after dozens of repeated calls against the same SKU within about an hour.
- Alternative (ruled less likely but not fully eliminated): background-tab throttling by Chrome — tested by forcing the window to foreground with `page.bring_to_front()`, which made no measurable difference, so this is probably not the main cause.

**Solve (mitigations in place / next steps):**
- Replaced the fixed `time.sleep(6)` wait with a polling loop (`while captured["data"] is None and waited < max_wait`) so the wait adapts to actual response time instead of guessing a fixed duration.
- Added evidence capture (`page.screenshot()` + `page.content()` saved to `data/debug/`) on every failed attempt, *before* closing the browser — this is what made this issue diagnosable at all instead of a silent black box.
- Added `page.on("console", ...)` and `page.on("pageerror", ...)` listeners for future runs, to catch a JS-crash cause immediately if it recurs.
- Next step to confirm/rule out the rate-limiting hypothesis: stop running the script for 10-15 minutes, then run once and compare the response delay against previous back-to-back attempts. If the delay drops back to normal after a cooldown, this confirms Shopee-side soft throttling, and the long-term fix is to add spacing (e.g. a minimum interval) between scrape runs against the same SKU rather than retrying immediately.

---

## Notes — data extraction learnings (not blockers, just corrections)

- The product's title field in the `pdp/get_pc` API response is `"title"`, not `"name"` as initially assumed — update any code that reads `item.get("name")` to `item.get("title")`.
- The API returns multiple price-shaped fields: `price`, `price_min`, `price_max` (variant range) and `price_before_discount`. These are all **list prices**, before any personalized voucher is applied. The price shown on-screen ("After Voucher") is computed client-side from list price minus shop/personal vouchers and will differ per account — for MAP/price-integrity monitoring, `price` (or `price_min`) is the correct field to store in `raw_prices`, not the post-voucher display price.
- `on_response` filters that match generic keys like `"price"` + `"name"` in *any* JSON response are unreliable — Shopee's page loads many unrelated JSON APIs (flash-sale carousels, recommendations) that happen to contain the same key names for *other* products. Filter instead by the known `item_id` from the URL to make sure the captured response is actually for the target product.
