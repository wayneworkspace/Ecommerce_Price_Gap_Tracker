# Ecommerce_Price_Gap_Tracker

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Airflow](https://img.shields.io/badge/Apache%20Airflow-Orchestration-017CEE?logo=apacheairflow&logoColor=white)
![dbt](https://img.shields.io/badge/dbt-Transformation-FF694B?logo=dbt&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Warehouse-4169E1?logo=postgresql&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-Scraping-2EAD33?logo=playwright&logoColor=white)
![Power BI](https://img.shields.io/badge/Power%20BI-Consumption-F2C811?logo=powerbi&logoColor=black)
![Status](https://img.shields.io/badge/Status-In%20Progress-yellow)

An automated ELT pipeline that scrapes prices for a small set of Logitech SKUs from the brand's official store and two major Vietnamese marketplaces (Shopee, TikTok Shop), then compares them against the official reference price to flag unauthorized-reseller price violations (MAP compliance).

---

## Business Value

Unauthorized resellers routinely undercut or misrepresent official pricing on third-party marketplaces, which erodes brand trust and margin for authorized channels. Manually checking prices across channels does not scale and produces inconsistent, stale snapshots.

This pipeline answers a concrete business question: **"Which SKUs and which sellers on Shopee/TikTok are currently priced below Logitech's official reference price, and by how much?"**

Planned outputs (Power BI):

| # | View | Question it answers |
|---|---|---|
| 1 | Price Gap % | How far is marketplace price from the official reference price, per SKU, per day? |
| 2 | Anomaly Alert Table | Which SKUs are priced >15% below reference — likely unauthorized/grey-market stock? |
| 3 | Seller Compliance Ranking | Which sellers repeatedly violate MAP? |
| 4 | Price Volatility Index | Which SKUs swing in price the most day-to-day? |
| 5 | Historical Price Trend | How does price move across the three channels over time (sale cycles)? |
| 6 | Discount Depth Distribution | How aggressive is each channel's discounting? |
| 7 | Pipeline Health Tile | When did each source last scrape successfully, and how often does it fail? |
| 8 | Stock Availability Tracker | Do suspicious sellers sell out unusually fast (small-batch grey-market signal)? |
| 9 | Cross-Channel Consistency | Does the same SKU differ in price between TikTok and Shopee? |
| 10 | Weekly Executive Summary | Top 3 SKUs with the largest price deviation this week |

This is not a "learn Airflow/dbt" exercise — the tools exist because the underlying problem (ordered, auditable, repeatable price comparison across sources) requires them.

---

## Architecture

(architecture.png)

> **Design note:** the diagram above shows the initial design with a dedicated "Orchestration Metadata Store" Postgres instance. That instance was cut in the current plan — Airflow already requires a metadata database to track DAG runs, so a second, separate Postgres for "orchestration logs" duplicates that without adding capability. The current plan runs a **single Postgres instance** with two schemas: `airflow` (orchestrator metadata) and `warehouse` (raw/staging/mart).

- **raw** → untouched scrape output, one row per scrape event (append-only, no dedup).
- **staging** → cast, type-enforced, deduplicated via dbt `unique_key` merge (no separate "dedup DAG" — see Challenges).
- **mart** → `price_gap_pct` and aggregate views computed with window functions, ready for Power BI.

---

## Tech Stack Rationale

| Tool | Why it's here | What breaks without it |
|---|---|---|
| **Playwright** | Marketplace pages render client-side JS; a plain HTTP client can't reliably extract price/stock fields | No usable HTML to parse |
| **Pandas / NumPy** | Lightweight structural validation before data leaves the ingestion layer | Malformed records reach the warehouse undetected |
| **Airflow** | Scrape → stage → transform must run in order; a failed step (e.g., Shopee blocked) must not silently corrupt downstream data | Cron jobs run independently with no dependency guarantee — an out-of-order run produces meaningless comparisons |
| **dbt** | Transform logic includes a window function (`LAG()`) comparing price across days, plus schema tests (`not_null`, `accepted_range`) and incremental merge for idempotency | Ad hoc SQL in Python has no lineage, no automated data-quality gate, and reprocesses full history on every run |
| **PostgreSQL** | Single relational store, sufficient at this data volume (a handful of SKUs, ~1 MB/month) | N/A — no case for a separate object store at this scale |
| **Docker Compose** | Reproducible local environment for anyone reviewing the project | Reviewer cannot run the pipeline without manually replicating the local setup |
| **Power BI** | Consumption layer for the business questions above | N/A |

No Kafka, Spark, or object storage — data volume does not justify them, and adding them without justification is the failure mode this project is explicitly avoiding.

---

## Challenges & Solutions

| Challenge | Solution |
|---|---|
| Anti-bot / selector instability on Shopee and TikTok | Validated manually before building any orchestration: run the scraper repeatedly against a single SKU to confirm selectors hold and no IP block occurs, *before* writing a single DAG |
| Scrape failures (site layout change, transient block) | `tenacity`-based exponential backoff, randomized 3–8s delay between requests |
| Re-running the pipeline must not duplicate raw rows | Handled at the transform layer with a dbt incremental model (`unique_key` merge/upsert) instead of a second "dedup DAG" — a dedicated DAG whose only job is deleting duplicates is redundant when dbt's native merge strategy already solves it |
| Malformed or null price fields after cast | Routed to a `quarantine` table rather than silently entering `mart` — a cast failure that reaches the mart layer undetected defeats the purpose of having a mart layer |
| Marketplace Terms of Service | Rate-limited scraping respecting `robots.txt`; representative raw HTML samples are cached locally so the project can be demonstrated offline if a live source becomes unavailable |

---

## Roadmap

| Week | Phase | Status |
|---|---|---|
| 1–2 | Manual Playwright validation + raw ingestion for 2–3 SKUs | In progress |
| 3–4 | Postgres warehouse schema + Docker Compose | Planned |
| 5–6 | dbt transformations + Airflow orchestration | Planned |
| 7–8 | Power BI dashboards + README polish | Planned |

---

## Setup Instructions

Weeks 1-2 of the roadmap cover the crawler only. Postgres, Docker Compose, dbt and Airflow arrive in weeks 3-6 and are **not** part of this setup yet.

```bash
git clone https://github.com/wayneworkspace/Ecommerce_Price_Gap_Tracker.git
cd Ecommerce_Price_Gap_Tracker

pip install -e ".[crawler,dev]"   # crawler = patchright + tenacity, dev = pytest
patchright install chrome         # real Chrome, not bundled Chromium - see Issue 3

cp .env.example .env              # then edit it, see the table below
```

`.env` has one required variable:

| Variable | What it is | What breaks without it |
|---|---|---|
| `SHOPEE_USER_DATA_DIR` | Absolute path to the Chrome persistent-profile directory holding your logged-in Shopee session | The crawler raises before opening a browser. Shopee redirects anonymous sessions to a login wall, so there is no scrape without a session - see `docs/decisions/0004-persistent-context-thay-vi-export-cookie.md` |

Log into that profile once, by hand:

```bash
python scripts/shopee_login.py
```

The script opens a real browser and waits. You log in yourself - including the captcha, if one appears - then press Enter. The session persists inside the profile directory, so this is a one-time step; repeat it only when the session expires.

Run the pipeline:

```bash
price-tracker-shopee
# equivalently: python -m price_tracker.sources.shopee.main
```

It writes the untouched API response to `data/raw/` and the mapped record to `data/staging/`. Which SKUs are scraped is configured in `config/skus.yaml`, not in code.

Run the tests - they need neither network nor browser, and work without a `.env`:

```bash
pytest
```

### Not available yet

| Step | Status |
|---|---|
| `docker-compose up -d` | Planned, weeks 3-4 |
| Airflow UI at `localhost:8080`, triggering `scrape_prices_dag` | Planned, weeks 5-6 |

---

## Data Model (planned)

`raw_prices`: `sku_id`, `source`, `seller_id`, `product_name`, `price`, `url`, `scraped_at`
`staging_prices`: cast + deduplicated version of the above
`mart_price_gap`: `sku_id`, `source`, `price`, `price_change_pct` (day-over-day, via `LAG()`)
