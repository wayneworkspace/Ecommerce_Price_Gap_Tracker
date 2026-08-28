# Bản đồ thư viện — hàm nào đến từ đâu, và làm gì

> Sinh từ AST của `src/`, không viết tay. Dùng khi đang đọc code mà gặp một cái
> tên không biết nó ở đâu ra.

Mọi cái tên trong code chỉ đến từ **5 nơi**:

| Nơi | Cách nhận ra | Bạn sửa được không? |
|---|---|---|
| 1. Built-in | Không có ở dòng `import` nào mà vẫn dùng được | Không |
| 2. Method của kiểu dữ liệu | `.get()`, `.append()` trên dict/list/str | Không |
| 3. Thư viện chuẩn | `import json`, `import re`... — có sẵn khi cài Python | Không |
| 4. Thư viện ngoài | `import yaml`... — phải `pip install` | Không |
| 5. Code của dự án | Import từ `price_tracker.`, hoặc có `def` ngay trong file | **Có** |

---

# 1. Thư viện ngoài (phải `pip install`)

## `patchright` — điều khiển Chrome thật

Bản vá của Playwright. Khai trong `pyproject.toml` extra `[crawler]`, phiên bản `>=1.62`.
Lý do dùng bản vá thay vì Playwright gốc: xem `docs/issues.md` Issue 4.

### Import trực tiếp

| Tên | Loại | Chức năng | Dùng ở |
|---|---|---|---|
| `sync_playwright` | hàm | Khởi động Playwright, trả về context manager quản lý vòng đời trình duyệt | `extract.py` |
| `Error` (đổi tên `PWError`) | lớp lỗi | Lỗi gốc của MỌI lỗi Playwright. Bắt nó là bắt được cả timeout, target đã đóng, browser chết | `extract.py` |
| `TimeoutError` | lớp lỗi | Hết thời gian chờ. Là **lớp con** của `Error`, nên bắt `Error` đã phủ luôn nó | test |

`Error`/`TimeoutError` không phải hàm — chúng đứng trong `except (...)` và trong
`@shopee_scrape_retry(PWError, FetchFailedError)`.

### Chuỗi object sinh ra từ `sync_playwright()`

Phần hay gây rối nhất: các method dưới đây **không import được**. Chúng là method
của object mà thư viện trả về.

```
sync_playwright()                →  Playwright            (biến p)
  p.chromium                     →  BrowserType
    .launch_persistent_context() →  BrowserContext        (biến browser)
      .new_page()                →  Page                  (biến page)
        .expect_response()       →  EventContextManager   (biến response_info)
          .value                 →  Response              (biến response)
```

| Lớp | Method / thuộc tính | Chức năng | Số lần |
|---|---|---|---|
| `Playwright` | `p.chromium` | Chọn dòng trình duyệt Chromium (thay vì firefox/webkit) | 1 |
| `BrowserType` | `.launch_persistent_context()` | Mở Chrome kèm thư mục profile → **giữ session đăng nhập** qua các lần chạy. Khác `launch()` ở chỗ này (Issue 1) | 1 |
| `BrowserContext` | `browser.new_page()` | Mở một tab mới trong phiên đang có | 1 |
| | `browser.close()` | Đóng cả trình duyệt và **nhả khoá** trên thư mục profile | 1 |
| `Page` | `page.goto()` | Điều hướng tới URL, chờ tới mức được chỉ định (`domcontentloaded`) | 1 |
| | `page.expect_response()` | Chờ đúng response khớp điều kiện. **Đây là cách bắt JSON giá** thay vì đọc CSS (ADR 0002) | 1 |
| | `page.on()` | Đăng ký hàm lắng nghe sự kiện `console` / `pageerror` để ghi log lỗi của trang | 2 |
| | `page.bring_to_front()` | Đưa tab lên trước — trang chạy nền có thể bị Chrome giảm ưu tiên | 1 |
| | `page.content()` | Lấy HTML hiện tại. Dùng lưu bằng chứng khi fail (nhìn là biết tường login hay captcha) | 1 |
| | `page.screenshot()` | Chụp ảnh trang. Bằng chứng thứ hai khi fail | 1 |
| | `page.close()` | Đóng **tab**, giữ nguyên browser cho listing kế tiếp | 1 |
| `EventContextManager` | `response_info.value` | Chặn chờ tới khi response về. Đây mới là lúc thật sự đợi, không phải lúc gọi `expect_response()` | 1 |
| `Response` | `response.json()` | Parse body thành dict. Thực chất là `json.loads(body().decode())` | 1 |
| | `response.url` / `r.url` | URL của response — dùng lọc đúng API `pdp/get_pc` và đúng `item_id` | 2 |
| `ConsoleMessage` | `msg.type` / `msg.text` | Loại và nội dung một dòng console của trang, để chỉ log khi là `error` | 3 |

> **Vì sao `page.close()` mà không `browser.close()` trong vòng lặp:** cả mẻ dùng
> chung một browser, mỗi listing chỉ đóng tab của nó. Xem `fetch_all_listings()`.

## `tenacity` — thử lại có backoff

Extra `[crawler]`, `>=9.1`. **Cả 5 tên chỉ xuất hiện ở đúng một file: `common/retry.py`.**

| Tên | Chức năng |
|---|---|
| `retry` | Decorator chính. Bọc một hàm để nó tự chạy lại khi ném lỗi |
| `stop_after_attempt` | Điều kiện dừng: thử tối đa N lần rồi chịu thua (ở đây N=3) |
| `wait_exponential` | Thời gian chờ tăng theo cấp số nhân giữa các lần thử — tránh nện liên tiếp vào server đang trục trặc |
| `retry_if_exception_type` | Bộ lọc: **chỉ** thử lại với những loại lỗi được liệt kê. Lỗi logic của mình thì cho vỡ luôn, thử lại vô ích |
| `before_sleep_log` | Ghi log trước mỗi lần chờ, để biết nó đang thử lại chứ không phải treo |

`extract.py` chỉ import `shopee_scrape_retry` — **nó không hề biết tenacity tồn tại.**
Đổi sang thư viện retry khác thì sửa đúng một file.

## `pyyaml` (import là `yaml`) — bắt buộc

`>=6.0`. Đọc `config/skus.yaml`.

| Hàm | Chức năng | Số lần |
|---|---|---|
| `yaml.safe_load()` | Đọc YAML → dict/list Python. **Luôn dùng `safe_load`, không dùng `load`** — `load()` dựng được object Python tuỳ ý từ file, tức chạy được code lạ | 1 |
| `yaml.safe_dump()` | Ngược lại: dict/list → chuỗi YAML. Chỉ dùng trong test để tạo file giả | 1 |

## `python-dotenv` (import là `dotenv`) — bắt buộc

`>=1.2`.

| Hàm | Chức năng | Số lần |
|---|---|---|
| `load_dotenv()` | Đọc file `.env` rồi nạp từng dòng vào biến môi trường, để `os.getenv()` sau đó thấy được. Chỉ định rõ đường dẫn thay vì để nó tự đoán, nên chạy đúng dù đứng ở thư mục nào | 1 |

## `pytest` — extra `[dev]`, chỉ trong test

| Tên | Chức năng | Số lần |
|---|---|---|
| `pytest.raises` | Khẳng định đoạn code **phải ném** đúng loại lỗi đó. Không ném là test fail | 19 |

Ngoài ra test dùng **fixture** — không import, pytest tự truyền vào theo tên tham số:

| Fixture | Chức năng |
|---|---|
| `tmp_path` | Thư mục tạm riêng cho mỗi test, tự xoá sau — để ghi file giả mà không đụng `data/` thật |
| `monkeypatch` | Thay tạm một biến/hàm trong lúc test, tự khôi phục sau. Dùng để trỏ `RAW_DIR` sang thư mục tạm, hoặc chặn `time.sleep` cho test khỏi chạy chậm |
| `caplog` | Bắt lại log mà code ghi ra, để khẳng định nó có cảnh báo đúng chỗ |

---

# 2. Thư viện chuẩn (có sẵn, không cài gì)

## `pathlib` — thứ dùng nhiều nhất

`Path` xuất hiện 10 lần. Nếu chỉ học một thứ, học cái này.

| Method / thuộc tính | Chức năng | Số lần |
|---|---|---|
| `Path()` | Tạo đối tượng đường dẫn. Thay cho việc nối chuỗi bằng `+` và `\\` — tự xử lý khác biệt Windows/Linux | 10 |
| `/` (toán tử) | Nối đường dẫn: `RAW_DIR / "abc.json"`. Đây là `Path.__truediv__` | nhiều |
| `.glob()` | Liệt kê file khớp mẫu, ví dụ `shopee_raw_*.json` | 1 |
| `.mkdir()` | Tạo thư mục. `parents=True` tạo cả cây cha, `exist_ok=True` không báo lỗi nếu đã có | 3 |
| `.open()` | Mở file để đọc/ghi, dùng với `with` | 1 |
| `.read_text()` | Đọc cả file thành một chuỗi. Gọn hơn `open()` + `read()` + `close()` | 2 |
| `.write_text()` | Ghi cả chuỗi ra file, tự đóng | 2 |
| `.stat()` | Lấy metadata của file. Ở đây dùng `.st_mtime` (thời điểm sửa cuối) để sắp xếp file raw | 1 |
| `.resolve()` | Đổi thành đường dẫn tuyệt đối, khử `..` và symlink | 1 |
| `.parents` | Danh sách mọi thư mục cha, đi ngược lên. Dùng dò tìm gốc project | 1 |
| `.parent` | Thư mục cha trực tiếp (một cấp) | 1 |
| `.name` | Tên file kèm đuôi, bỏ phần thư mục | 7 |

> **Bẫy đọc code:** biến `p` là `Playwright` trong `extract.py:326` nhưng là `Path`
> trong `transform.py:47` (`lambda p: p.stat().st_mtime`). Cùng tên, khác kiểu,
> khác phạm vi. Nhìn dòng gán để biết nó là gì.

## `datetime`

| Tên | Loại | Chức năng | Số lần |
|---|---|---|---|
| `datetime.now()` | class method | Thời điểm hiện tại. **Luôn truyền `timezone.utc`** để ra aware datetime | 2 |
| `datetime.fromisoformat()` | class method | Parse chuỗi ISO 8601 → datetime. Dùng đọc lại `scraped_at` | 2 |
| `datetime.strptime()` | class method | Parse theo định dạng tự đặt. Dùng đọc `20260827T055522Z` từ tên file | 1 |
| `.astimezone()` | instance | Đổi sang múi giờ khác, giữ nguyên mốc thời gian thật | 2 |
| `.replace()` | instance | Tạo **bản sao** đổi vài trường. Ở đây gắn `tzinfo=utc` cho datetime chưa có múi giờ | 2 |
| `.isoformat()` | instance | Xuất chuỗi ISO 8601 — định dạng chuẩn để lưu và trao đổi | 3 |
| `.strftime()` | instance | Xuất theo định dạng tự đặt. Dùng đặt tên file | 1 |
| `.tzinfo` | thuộc tính | Múi giờ của datetime. `None` nghĩa là **naive** — nguồn bug thầm lặng khi so sánh | 1 |
| `timezone.utc` | hằng số | Đối tượng múi giờ UTC | 6 |

Cả dự án chỉ dùng **aware datetime** (luôn kèm `timezone.utc`).

## `json`

| Tên | Loại | Chức năng | Số lần |
|---|---|---|---|
| `json.loads()` | hàm | Chuỗi JSON → dict/list Python (`s` là *string*) | 2 |
| `json.dumps()` | hàm | dict/list → chuỗi JSON. `ensure_ascii=False` giữ tiếng Việt đọc được, `indent=2` xuống dòng cho dễ đọc | 4 |
| `json.JSONDecodeError` | lớp lỗi | Ném khi chuỗi không phải JSON hợp lệ. Bắt trong `except` để bỏ qua file hỏng | 1 |

## `logging`

| Tên | Loại | Chức năng | Số lần |
|---|---|---|---|
| `logging.getLogger()` | hàm module | Lấy logger theo tên (`__name__`), để log biết đến từ module nào | 5 |
| `logging.basicConfig()` | hàm module | Cấu hình định dạng và mức log cho toàn chương trình. Chỉ nên gọi một lần | 1 |
| `logging.INFO` / `logging.WARNING` | hằng số | Mức độ nghiêm trọng, dùng lọc log | 2 |
| `logger.info()` | method của `Logger` | Ghi việc bình thường: đã bắt được response, đã lưu file | 7 |
| `logger.warning()` | method của `Logger` | Ghi việc bất thường nhưng chưa chết: bỏ qua file hỏng, đang thử lại, giá không dùng được | 16 |

`logger` là object do `getLogger()` trả về — `.info()`/`.warning()` là method của nó.

## `re` — biểu thức chính quy

| Tên | Loại | Chức năng | Số lần |
|---|---|---|---|
| `re.compile()` | hàm module | Biên dịch sẵn mẫu regex thành object `Pattern`, dùng lại nhiều lần khỏi biên dịch lại | 1 |
| `.search()` | method của `Pattern` | Tìm mẫu ở **bất kỳ đâu** trong chuỗi (khác `.match()` chỉ tìm ở đầu) | 1 |
| `.group()` | method của `Match` | Lấy phần chuỗi đã khớp. `group(1)` là nhóm ngoặc đầu tiên | 1 |

Chỉ dùng đúng một chỗ: tìm `20260827T055522Z` trong tên file.

## Ba module còn lại — mỗi cái đúng 1 hàm

| Module | Hàm | Chức năng |
|---|---|---|
| `os` | `os.getenv()` | Đọc biến môi trường, trả `None` nếu không có (khác `os.environ[...]` ném `KeyError`) |
| `random` | `random.uniform()` | Số thực ngẫu nhiên trong khoảng. Delay 3–8s — **ngẫu nhiên** vì khoảng cách đều tăm tắp là dấu hiệu bot dễ nhận nhất |
| `time` | `time.sleep()` | Dừng chương trình N giây |

---

# 3. Method của kiểu dữ liệu — KHÔNG phải thư viện

Chỗ hay nhầm nhất. `item.get()` trông giống gọi thư viện, nhưng `item` chỉ là một
`dict` bình thường.

| Method | Kiểu | Chức năng | Số lần |
|---|---|---|---|
| `.get()` | `dict` | Lấy giá trị theo key, trả `None` (hoặc mặc định) nếu thiếu — **không ném `KeyError`**. Đó là lý do nó có mặt khắp nơi khi đọc dữ liệu Shopee: field nào cũng có thể vắng | 35 |
| `.items()` | `dict` | Duyệt đồng thời key và value | 3 |
| `.update()` | `dict` | Trộn dict khác vào, key trùng thì đè | 1 |
| `.append()` | `list` | Thêm một phần tử vào cuối | 5 |
| `.add()` | `set` | Thêm vào tập hợp; đã có rồi thì không thêm nữa — dùng phát hiện listing trùng | 1 |
| `.replace()` | `str` | Thay chuỗi con. Ở đây đổi `"Z"` thành `"+00:00"` cho `fromisoformat()` hiểu được | 1 |

> `.replace()` xuất hiện ở **hai kiểu khác nhau**: `str.replace()` đổi ký tự,
> `datetime.replace()` tạo bản sao đổi trường. Nhìn biến để biết cái nào.

---

# 4. Built-in (không import gì cả)

Toàn bộ built-in dự án dùng — **chỉ 24 cái**.

| Tên | Chức năng |
|---|---|
| `dict` `list` `tuple` `set` | Kiểu dữ liệu; cũng dùng trong `isinstance()` để kiểm kiểu |
| `str` `int` `float` `bool` | Kiểu cơ bản; `str(x)` ép về chuỗi |
| `isinstance` | Kiểm một giá trị có đúng kiểu không. Là nền của mọi câu canh cửa trong `payload.py` |
| `type` | Lấy kiểu của giá trị. Dùng `type(x).__name__` để in tên kiểu vào thông báo lỗi |
| `len` | Đếm phần tử |
| `sorted` | Sắp xếp, có `key=` để chọn tiêu chí và `reverse=` để đảo chiều |
| `enumerate` | Duyệt kèm chỉ số. Dùng `i+1` khi in cho người đọc, vì file YAML đếm từ 1 |
| `super` | Gọi phương thức của lớp cha — dùng trong `BatchIncompleteError.__init__` |
| `print` | In ra màn hình. Chỉ dùng ở `main.py` cho phần tóm tắt; chỗ khác dùng `logger` |
| `Exception` | Lớp gốc của mọi lỗi. Bắt nó là bắt tất |
| `ValueError` | Giá trị sai — YAML sai hình dạng, file raw không suy ra được thời điểm cào |
| `KeyError` | Thiếu key — SKU không có trong `skus.yaml` |
| `TypeError` | Sai kiểu — gọi hàm retry mà không truyền loại lỗi nào |
| `OSError` | Lỗi hệ thống file — không đọc được file |
| `RuntimeError` | Lỗi lúc chạy — thiếu `pyproject.toml`, không xác định được gốc project |
| `FileNotFoundError` | Không tìm thấy file. Là lớp con của `OSError` |
| `UnicodeDecodeError` | File không giải mã được theo UTF-8. **Không** phải lớp con của `OSError` hay `JSONDecodeError` — phải bắt riêng |
| `SystemExit` | Thoát chương trình với mã trạng thái |

Thấy một cái tên **không** nằm trong danh sách này và **không** ở khối `import`
→ chắc chắn nó là `def` trong chính file đó.

---

# 5. Cách tự tra khi quên

**Trong VS Code:** `F12` hoặc `Ctrl` + click vào tên.

| Nhảy tới đâu | Kết luận |
|---|---|
| `src/price_tracker/` | Code của dự án |
| `site-packages/` | Thư viện ngoài |
| `Python313/Lib/` | Thư viện chuẩn |
| Không nhảy | Built-in |

**Trong terminal:**

```bash
grep -rn "def load_skus" src/
```

Có kết quả → hàm của dự án. Không có → tìm ở khối `import` đầu file.

**Xem nhanh mục lục hàm của cả project:**

```bash
python -c "import ast,pathlib;[print(f'\n{f}') or [print(f'  {n.name:26}',(ast.get_docstring(n) or '?').splitlines()[0]) for n in ast.parse(f.read_text(encoding='utf-8')).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))] for f in sorted(pathlib.Path('src').rglob('*.py')) if f.stat().st_size]"
```
