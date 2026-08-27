# Kế hoạch tổ chức source code — Ecommerce_Price_Gap_Tracker

> Bản v2, viết lại theo 2 mục tiêu: **(1) scale lên Airflow/dbt dễ**, và
> **(2) 3 tháng sau quay lại vẫn đọc hiểu**.
>
> Sau khi thực thi, file này chuyển vào `docs/PROJECT_STRUCTURE.md` — nó là bản
> đồ của repo, phải sống cạnh code.

---

## Phần 1 — Sáu nguyên tắc (phần quan trọng hơn cái cây)

Cây thư mục chỉ là hệ quả. Hiểu 6 nguyên tắc này rồi thì bạn tự sắp xếp được mọi
dự án sau, không cần ai vẽ hộ.

### NT1. Một thư mục = một câu trả lời cho "cái này chứa gì?"

Nếu bạn không nói được trong 3 từ thư mục đó chứa gì, thư mục đó sai.

`src/crawler/shopee/` hiện đang chứa: code lấy dữ liệu, code biến đổi dữ liệu,
cấu hình, script đăng nhập tay, test, và một script debug đã chết. Sáu loại việc
khác nhau trong một thư mục. Ba tháng nữa mở ra bạn phải đọc từng file mới biết
cái nào làm gì.

### NT2. Cấu trúc phải **nhân bản được**, không phải **mở rộng được**

Đây là định nghĩa thực tế của "scale" trong DE.

Bạn sắp thêm TikTok Shop và Logitech official store. Cấu trúc tốt là cấu trúc mà
thêm nguồn mới = **copy khuôn của nguồn cũ**, không phải sửa code cũ.

```
sources/shopee/     extract.py  transform.py  settings.py
sources/tiktok/     extract.py  transform.py  settings.py   <- y hệt khuôn
sources/logitech/   extract.py  transform.py  settings.py   <- y hệt khuôn
```

Ba nguồn, ba thư mục giống hệt nhau. Mở cái nào cũng biết ngay file nào làm gì.
Đó vừa là scale (NT2) vừa là đọc hiểu (mở `tiktok/` không cần học lại gì).

### NT3. DAG phải MỎNG — đây là bài học đắt nhất

Sai lầm phổ biến nhất khi người mới lên Airflow: nhét logic vào trong DAG file.

**DAG chỉ được làm đúng 3 việc:** chạy lúc nào, chạy theo thứ tự nào, hỏng thì báo ai.
Mọi logic nằm trong package, DAG chỉ gọi vào.

```python
# airflow/dags/daily_price_scrape.py — TOÀN BỘ file, không hơn
from airflow.decorators import dag, task
from price_tracker.sources.shopee import extract, transform
from price_tracker.warehouse import load

@dag(schedule="0 2 * * *", catchup=False, tags=["price"])
def daily_price_scrape():
    @task
    def scrape_shopee():
        return extract.fetch_all_skus()

    @task
    def load_raw(paths):
        return load.to_raw_table(paths)

    load_raw(scrape_shopee())

daily_price_scrape()
```

Vì sao quan trọng đến thế:

| Logic trong DAG | Logic trong package |
|---|---|
| Muốn test phải dựng cả Airflow | `pytest` chạy trong 0.3 giây |
| Muốn chạy tay phải qua UI | `python -m price_tracker...` là chạy |
| Đổi orchestrator = viết lại hết | Đổi orchestrator = viết lại 15 dòng |

Bạn đã có 12 test chạy trong 0.27s. Nhét logic vào DAG là vứt bỏ toàn bộ số đó.

### NT4. Thứ thay đổi thường xuyên là **dữ liệu**, không phải **code**

Đây là thứ **sẽ chặn bạn ngay tuần sau**, và bản kế hoạch trước bỏ sót.

`config.py` hiện đang có:

```python
TARGET_ITEM_ID = "6765591429"
PRODUCT_URL = r"https://shopee.vn/Chu%E1%BB%99t-gaming...i.52679373.6765591429"
```

**Hard-code cho đúng một SKU.** Nhưng README của bạn viết: 2–3 SKU × 3 kênh.
Tức là 9 cặp `(item_id, url)`. Đi theo đường hiện tại thì bạn sẽ có 9 biến
hard-code trong Python, và mỗi lần đổi SKU là sửa code + commit.

Danh sách SKU là **dữ liệu**, không phải code. Nó thuộc về một file config:

```yaml
# config/skus.yaml
- sku: G102-LIGHTSYNC
  name: "Logitech G102 Lightsync"
  reference_price: 489000        # giá niêm yết chính hãng, để tính price_gap
  sources:
    shopee:
      item_id: "6765591429"
      shop_id: "52679373"
      url: "https://shopee.vn/...i.52679373.6765591429"
    tiktok:
      item_id: "..."
```

Đổi SKU = sửa 1 file YAML, không đụng code, không cần test lại. dbt cũng đọc được
file này làm seed để join ra `reference_price`. Đây là thứ phân biệt một pipeline
chạy được với một script chạy được.

### NT5. `tests/` soi gương `src/`

```
src/price_tracker/sources/shopee/transform.py
tests/          sources/shopee/test_transform.py
```

Đường dẫn giống hệt, chỉ thêm `test_`. Không bao giờ phải đi tìm test ở đâu.
Cũng lộ ngay chỗ nào chưa có test — như `fetch_raw.py` hiện tại.

### NT6. Ghi lại **lý do**, không chỉ **kết quả**

Đây là nguyên tắc phục vụ thẳng mục tiêu 2 của bạn.

Code nói *cái gì đang chạy*. Nó không bao giờ nói được *vì sao không chọn cách kia*.
Ba tháng sau, thứ bạn quên là lý do — và đó cũng đúng là thứ người phỏng vấn hỏi.

Bạn **đã có sẵn** thứ này rồi: `Day_1_Shopee_Scape.txt`, `Day_2_.txt`, `Day_3.txt`.
Nội dung trong đó (vì sao Playwright chứ không requests, vì sao bắt API chứ không
CSS selector, vì sao sync chứ không async, tenacity khác pytest chỗ nào) là tài
sản quý nhất của dự án — mà hiện đang nằm **ngoài repo**, dạng file .txt rời, tên
không nói lên gì.

Chuyển chúng thành **ADR** (Architecture Decision Record) — chuẩn công nghiệp:

```
docs/decisions/
├── 0001-dung-playwright-thay-vi-requests.md
├── 0002-bat-api-json-thay-vi-css-selector.md
├── 0003-playwright-sync-thay-vi-async.md
├── 0004-persistent-context-thay-vi-export-cookie.md
├── 0005-mot-postgres-hai-schema.md
└── 0006-dbt-incremental-thay-vi-dedup-dag.md
```

Mỗi file theo khuôn 4 phần: **Bối cảnh → Các phương án → Quyết định → Hệ quả**.
Bạn đã viết sẵn nội dung, chỉ là đổi chỗ và đặt tên tử tế.

---

## Phần 2 — Cây thư mục đích

```
Ecommerce_Price_Gap_Tracker/
│
├── README.md                       # cửa vào: dự án làm gì, chạy thế nào
├── pyproject.toml                  # 1 nguồn sự thật: dependency + cấu hình tool
├── docker-compose.yml              # tuần 3-4
├── .env.example                    # khai báo biến, KHÔNG chứa giá trị thật
├── .gitignore
│
├── config/                         # ⭐ CẤU HÌNH = DỮ LIỆU (xem NT4)
│   └── skus.yaml                    # danh sách SKU + URL + giá niêm yết
│
├── src/price_tracker/              # toàn bộ logic Python
│   ├── __init__.py
│   ├── config.py                   # đọc .env + skus.yaml. KHÔNG chứa gì riêng Shopee
│   │
│   ├── sources/                    # 1 thư mục = 1 nguồn dữ liệu (xem NT2)
│   │   ├── shopee/
│   │   │   ├── extract.py          # <- fetch_raw.py   : lấy JSON thô
│   │   │   ├── transform.py        # <- build_record.py: ép về schema chung
│   │   │   └── settings.py         # chỉ thứ riêng Shopee (URL API, selector)
│   │   ├── tiktok/                 # tuần sau
│   │   └── logitech/
│   │
│   ├── warehouse/                  # mọi thứ chạm Postgres
│   │   ├── connection.py
│   │   └── load.py                 # ghi vào schema raw
│   │
│   └── common/                     # dùng chung mọi nguồn
│       ├── retry.py                # <- retry.py
│       ├── logging.py              # cấu hình log tập trung
│       └── models.py               # PriceRecord: schema chung 3 nguồn phải khớp
│
├── sql/ddl/                        # CREATE SCHEMA/TABLE cho raw (tuần 3-4)
│
├── dbt/                            # dự án dbt — theo chuẩn riêng của dbt
│   ├── dbt_project.yml
│   ├── seeds/                      # đọc config/skus.yaml -> bảng reference_price
│   └── models/
│       ├── staging/                # cast, dedup (incremental unique_key)
│       └── marts/                  # price_gap_pct, LAG(), các view Power BI
│
├── airflow/dags/                   # DAG MỎNG (xem NT3)
│   └── daily_price_scrape.py
│
├── tests/                          # soi gương src/ (xem NT5)
│   ├── conftest.py
│   ├── sources/shopee/{test_extract,test_transform}.py
│   └── common/test_retry.py
│
├── scripts/                        # chạy tay, KHÔNG phải thư viện
│   └── shopee_login.py             # có input() chờ Enter -> không phải lib
│
├── docs/
│   ├── decisions/                  # ⭐ ADR — Day_1/2/3 chuyển vào đây (NT6)
│   ├── issues.md                   # <- Issue_Logs.md
│   ├── errors.md                   # <- Error_Logs.md
│   ├── images/                     # gộp Issue_image/ + Succes/
│   └── PROJECT_STRUCTURE.md        # <- chính file này
│
└── data/                           # gitignored
    ├── raw/
    └── staging/
```

### Vì sao cây này đọc dễ hơn

Mở repo lần đầu, đọc từ trên xuống, bạn tự trả lời được:

| Câu hỏi | Nhìn vào |
|---|---|
| Dữ liệu từ đâu ra? | `src/price_tracker/sources/` — mỗi nguồn 1 thư mục |
| Theo dõi SKU nào? | `config/skus.yaml` — 1 file, không phải mò trong code |
| Dữ liệu đi đâu? | `warehouse/` → `sql/ddl/` → `dbt/` |
| Chạy lúc nào? | `airflow/dags/` |
| Vì sao làm thế này? | `docs/decisions/` |
| Từng gặp lỗi gì? | `docs/issues.md` |

Không có thư mục nào phải mở ra mới biết nó chứa gì.

---

## Phần 3 — Bảng ánh xạ

| Hiện tại | Đích | Ghi chú |
|---|---|---|
| `src/crawler/shopee/config.py` | tách 2: `src/price_tracker/config.py` + `sources/shopee/settings.py` | ⚠️ `parents[3]` — xem rủi ro #1 |
| `src/crawler/shopee/fetch_raw.py` | `sources/shopee/extract.py` | tên nói đúng việc nó làm |
| `src/crawler/shopee/build_record.py` | `sources/shopee/transform.py` | |
| `src/crawler/shopee/retry.py` | `common/retry.py` | dùng chung 3 nguồn |
| `src/crawler/shopee/main.py` | entry point trong `pyproject.toml` | |
| `src/crawler/shopee/login_shopee.py` | `scripts/shopee_login.py` | có `input()` → script tay |
| `src/crawler/shopee/debug/find_price.py` | **xoá** | code chết, xem `to_delete.md` mục 1.3 |
| `test_case/test_fetch_raw.py` | tách 2 theo `tests/` soi gương `src/` | |
| `test_case/__init__.py` | **xoá** | file rỗng 0 byte, chỉ là mẹo sys.path |
| `TARGET_ITEM_ID`, `PRODUCT_URL` | `config/skus.yaml` | ⭐ NT4 |
| `src/crawler/requirements.txt` | `pyproject.toml` | bỏ `pandas`/`numpy` chưa dùng |
| `Day_1/2/3.txt` (ngoài repo) | `docs/decisions/000N-*.md` | ⭐ NT6 |
| `docs/Issue_Logs.md` | `docs/issues.md` | |
| `docs/Issue_image/` + `docs/Succes/` | `docs/images/` | `Succes` là lỗi chính tả |

---

## Phần 4 — Bảy thứ sẽ gãy khi move

### ⚠️ #1 — `parents[3]` gãy IM LẶNG (nguy hiểm nhất)

Đã kiểm chứng bằng Python:

```
HIỆN TẠI  src/crawler/shopee/config.py   parents[3] = Ecommerce_Price_Gap_Tracker  ✅
SAU MOVE  src/price_tracker/config.py    parents[3] = 1_End-to-End Project         ❌ ra ngoài repo
                                         parents[2] = Ecommerce_Price_Gap_Tracker
```

`parents[3]` xuất hiện **3 lần** (dòng 8, 35, 40 — `.env`, `RAW_DIR`, `STAGING_DIR`).

Quên sửa thì **không có lỗi nào báo**. `RAW_DIR.mkdir(parents=True, exist_ok=True)`
vui vẻ tạo `data/raw` ở ngoài repo, cạnh `Shopee Profile/`. Crawler báo thành công,
còn bạn ngồi tự hỏi sao `data/raw` trong repo vẫn rỗng.

**Bỏ hẳn kiểu đếm `parents[n]`.** Dò ngược lên tìm thư mục chứa `pyproject.toml`:

```python
def find_project_root() -> Path:
    """Dò ngược lên tìm thư mục có pyproject.toml.

    Không đếm parents[n] vì con số đó phụ thuộc file này nằm sâu bao nhiêu cấp —
    mỗi lần đổi cấu trúc là nó sai, và sai IM LẶNG: mkdir vẫn chạy, chỉ là tạo
    nhầm chỗ.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Không tìm thấy gốc project (thiếu pyproject.toml)")
```

### #2 — Toàn bộ import phẳng
`from config import` → `from price_tracker.config import`. Áp dụng cho cả
`retry`, `build_record`.

### #3 — pytest đang dựa vào một *mẹo*
`test_case/__init__.py` là file **rỗng 0 byte**, tồn tại chỉ để pytest chèn
`shopee/` vào `sys.path`. Sau reorg: xoá nó, `pip install -e .`, thêm
`[tool.pytest.ini_options]` vào `pyproject.toml`.

### #4 — 4 link ảnh trong docs sẽ vỡ
```
issues.md:9   Issue_1_Gotolinkwithchromium.jpg
issues.md:13  Issue_1_Gotolinkwithphone.jpg
issues.md:41  Issue_3_CaptchaAntiBot.jpg
issues.md:87  Issue_5_PriceNeverLoads.png
```
Đổi `Issue_image/` → `images/` là vỡ cả 4. GitHub hiện ảnh lỗi — thứ nhà tuyển
dụng thấy đầu tiên. Phải sửa cùng commit.

### #5 — `.gitignore`
Thêm `*.egg-info/`, `build/`, `dist/`, `dbt/target/`, `dbt/dbt_packages/`,
`airflow/logs/`, `airflow.db`.

### #6 — `python main.py` hết chạy
Thành entry point: `price-tracker-shopee` (khai trong `pyproject.toml`).

### #7 — README
Mục Setup vốn đã sai (`cd logitech-price-integrity-monitor`, `docker-compose up -d`
chưa tồn tại, không nhắc `SHOPEE_USER_DATA_DIR`). Sau reorg càng sai.

**Bonus:** dòng cuối `login_shopee.py` in *"chạy scrape_product.py"* — file đó
không tồn tại. Trong `shopee/` chỉ có `build_record, config, fetch_raw,
login_shopee, main, retry`.

---

## Phần 5 — Quy ước đặt tên

Rải rác trong repo đang có 4 kiểu đặt tên khác nhau. Chốt một kiểu:

| Loại | Quy ước | Sai hiện tại → Đúng |
|---|---|---|
| Thư mục, file Python | `snake_case`, thường | `test_case/` → `tests/` |
| Thư mục docs | thường, không viết hoa | `Issue_image/` → `images/` |
| File markdown trong docs | thường | `Issue_Logs.md` → `issues.md` |
| ADR | `000N-mo-ta-ngan.md` | `Day_1_Shopee_Scape.txt` → `0001-dung-playwright-thay-vi-requests.md` |

**Không bao giờ dùng dấu cách trong tên file/thư mục** — nó bắt mọi lệnh shell
phải quote, và gãy trong Docker/Airflow. (`Shopee Profile/` nằm ngoài repo nên
tạm chấp nhận được, nhưng nếu đưa vào bất kỳ script nào thì phải đổi.)

Và sửa `Succes` → `success`. Lỗi chính tả trong repo public là thứ người ta để ý.

---

## Phần 6 — Thứ tự thực thi

Chia **4 commit riêng**. Không gộp.

| # | Commit | Nội dung |
|---|---|---|
| 1 | `fix: harden shopee crawler error handling` | Batch A (đã xong, chờ commit) |
| 2 | `chore: remove dead files and debug artifacts` | theo `to_delete.md` |
| 3 | `refactor: restructure into installable package` | move + sửa import. **Không đổi 1 dòng logic** |
| 4 | `docs: add ADRs and project structure` | Day_1/2/3 → `docs/decisions/` |

**Cách chứng minh commit 3 không làm hỏng gì:** chạy đúng 12 test đó trước và
sau, kết quả phải giống hệt (`12 passed`). Dùng `git mv` để giữ `git log --follow`.

Vì sao không gộp: trộn move file với đổi hành vi thì review không đọc nổi (200
dòng logic lẫn trong 30 file đổi chỗ), và nếu hỏng thì `git bisect` không tách
được là do reorg hay do fix.

---

## Cần bạn quyết

1. **Tên package `price_tracker`** — ổn không? (repo tên `Ecommerce_Price_Gap_Tracker`
   quá dài để làm tên package Python)
2. **Đổi `fetch_raw.py`/`build_record.py` → `extract.py`/`transform.py`?**
   Được: khuôn giống nhau cho cả 3 nguồn, ai đọc cũng hiểu ngay. Mất: bạn đang
   quen tên cũ, và Issue_Logs có nhắc tên file cũ.
3. **Làm `config/skus.yaml` ngay (NT4) hay đợi tới lúc thêm SKU thứ 2?**
   Tôi nghiêng về làm ngay — làm lúc có 1 SKU thì rẻ, làm lúc có 9 thì đau.
4. **Chuyển Day_1/2/3 thành ADR luôn?** Đây là việc tốn công nhất nhưng phục vụ
   thẳng mục tiêu "quay lại đọc hiểu" của bạn.
