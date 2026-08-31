<div align="center">

# Ecommerce Price Gap Tracker

**Automated ELT pipeline for MAP-compliance monitoring across Vietnamese e-commerce channels**

Scrapes Logitech SKU prices from the official store, Shopee, and TikTok Shop, then flags resellers pricing below the official reference.

![Status](https://img.shields.io/badge/Status-In%20Progress-yellow)

<p align="center">
    <img src="https://skillicons.dev/icons?i=py" alt="Python" width="48" />
    <img src="https://raw.githubusercontent.com/devicons/devicon/master/icons/apacheairflow/apacheairflow-original.svg" alt="Apache Airflow" width="48" />
    <img src="https://raw.githubusercontent.com/gilbarbara/logos/main/logos/dbt-icon.svg" alt="dbt" width="48" />
    <img src="https://skillicons.dev/icons?i=postgres" alt="PostgreSQL" width="48" />
    <img src="https://raw.githubusercontent.com/devicons/devicon/master/icons/playwright/playwright-original.svg" alt="Playwright" width="48" />
    <img src="https://skillicons.dev/icons?i=docker" alt="Docker" width="48" />
    <img src="https://raw.githubusercontent.com/microsoft/PowerBI-Icons/main/SVG/Power-BI.svg" alt="Power BI" width="48" />
</p>

`Python` · `Apache Airflow` · `dbt` · `PostgreSQL` · `Playwright` · `Docker` · `Power BI`

</div>

---

## What This Demonstrates

- **Right-sized architecture** — one Postgres instance, no Kafka/Spark/object storage. Data volume (~1 MB/month) doesn't justify them, and unjustified tooling is the failure mode this project explicitly avoids.
- **Idempotent, auditable pipelines** — append-only raw layer, dbt incremental merge for dedup, quarantine table for malformed records.
- **Production habits at portfolio scale** — retry/backoff, schema tests, dependency-ordered orchestration, reproducible environment.

## Business Problem

Unauthorized resellers undercut official pricing on marketplaces, eroding brand trust and margin for authorized channels. Manual cross-channel price checks don't scale and produce stale, inconsistent snapshots.

**The question this pipeline answers:** *Which SKUs and sellers on Shopee/TikTok are currently priced below Logitech's official reference price — and by how much?*

<details>
<summary><strong>Planned Power BI views (10)</strong></summary>
<br>

| # | View | Question it answers |
|---|---|---|
| 1 | Price Gap % | Distance from official reference price, per SKU per day |
| 2 | Anomaly Alert Table | SKUs priced >15% below reference — likely grey-market stock |
| 3 | Seller Compliance Ranking | Which sellers repeatedly violate MAP? |
| 4 | Price Volatility Index | Which SKUs swing most day-to-day? |
| 5 | Historical Price Trend | Price movement across three channels over sale cycles |
| 6 | Discount Depth Distribution | How aggressive is each channel's discounting? |
| 7 | Pipeline Health Tile | Last successful scrape per source; failure frequency |
| 8 | Stock Availability Tracker | Do suspicious sellers sell out unusually fast? |
| 9 | Cross-Channel Consistency | Same SKU, different price between TikTok and Shopee? |
| 10 | Weekly Executive Summary | Top 3 SKUs with the largest deviation this week |

</details>

## Architecture

![Architecture — scrape to Power BI](architecture.png)



## Tech Stack Rationale

| Tool | Why it's here | What breaks without it |
|---|---|---|
| **Playwright** | Marketplace pages render client-side JS | No usable HTML to parse |
| **Pandas / NumPy** | Structural validation at the ingestion layer | Malformed records reach the warehouse undetected |
| **Airflow** | Scrape → stage → transform must run in order; a failed step must not corrupt downstream data | Independent cron jobs give no dependency guarantee |
| **dbt** | Window functions, schema tests, incremental merge — with lineage | Ad hoc SQL: no lineage, no quality gate, full reprocessing every run |
| **PostgreSQL** | Sufficient relational store at this volume | N/A — no case for more at this scale |
| **Docker Compose** | Reproducible environment for reviewers | Manual setup replication required |
| **Power BI** | Consumption layer | N/A |

## Challenges & Solutions

| Challenge | Solution |
|---|---|
| Anti-bot / selector instability | Validated selectors manually against a single SKU **before** writing any DAG |
| Transient scrape failures | `tenacity` exponential backoff + randomized 3–8s delays |
| Re-runs must not duplicate rows | dbt incremental merge (`unique_key`) — no redundant "dedup DAG" |
| Malformed price fields after cast | Routed to `quarantine`, never silently into `mart` |
| Marketplace ToS | Rate-limited, respects `robots.txt`; cached HTML samples enable offline demo |

## Roadmap

<h2>02 — Roadmap</h2>

<div align="center">

<svg width="900" viewBox="0 0 900 420"
     xmlns="http://www.w3.org/2000/svg">

  <!-- ============================= -->
  <!-- HEADER -->
  <!-- ============================= -->

  <text x="20" y="35"
        font-family="Arial, sans-serif"
        font-size="11"
        font-weight="700"
        fill="#64748B"
        letter-spacing="2">
    PHASE
  </text>

  <!-- Week labels -->

  <g font-family="Arial, sans-serif"
     font-size="11"
     fill="#64748B"
     text-anchor="middle">

    <text x="300" y="35">01</text>
    <text x="370" y="35">02</text>
    <text x="440" y="35">03</text>
    <text x="510" y="35">04</text>
    <text x="580" y="35">05</text>
    <text x="650" y="35">06</text>
    <text x="720" y="35">07</text>
    <text x="790" y="35">08</text>

  </g>


  <!-- ============================= -->
  <!-- TIMELINE GRID -->
  <!-- ============================= -->

  <g stroke="#1E293B"
     stroke-width="1">

    <line x1="265" y1="55" x2="265" y2="340"/>
    <line x1="335" y1="55" x2="335" y2="340"/>
    <line x1="405" y1="55" x2="405" y2="340"/>
    <line x1="475" y1="55" x2="475" y2="340"/>
    <line x1="545" y1="55" x2="545" y2="340"/>
    <line x1="615" y1="55" x2="615" y2="340"/>
    <line x1="685" y1="55" x2="685" y2="340"/>
    <line x1="755" y1="55" x2="755" y2="340"/>
    <line x1="825" y1="55" x2="825" y2="340"/>

  </g>


  <!-- ============================= -->
  <!-- PHASE 01 — CRAWLER -->
  <!-- ============================= -->

  <text x="20" y="90"
        font-family="Arial, sans-serif"
        font-size="13"
        font-weight="700"
        fill="#E2E8F0">
    CRAWLER
  </text>

  <text x="20" y="108"
        font-family="Arial, sans-serif"
        font-size="10"
        fill="#64748B">
    Playwright · Raw ingestion
  </text>


  <!-- Timeline -->

  <line x1="300" y1="92"
        x2="405" y2="92"
        stroke="#38BDF8"
        stroke-width="3"/>

  <circle cx="300" cy="92"
          r="5"
          fill="#38BDF8"/>

  <circle cx="405" cy="92"
          r="5"
          fill="#38BDF8"/>


  <!-- ============================= -->
  <!-- PHASE 02 — DATABASE -->
  <!-- ============================= -->

  <text x="20" y="160"
        font-family="Arial, sans-serif"
        font-size="13"
        font-weight="700"
        fill="#E2E8F0">
    DATABASE
  </text>

  <text x="20" y="178"
        font-family="Arial, sans-serif"
        font-size="10"
        fill="#64748B">
    PostgreSQL · Docker
  </text>


  <line x1="440" y1="162"
        x2="545" y2="162"
        stroke="#475569"
        stroke-width="3"/>

  <circle cx="440" cy="162"
          r="5"
          fill="#475569"/>

  <circle cx="545" cy="162"
          r="5"
          fill="#475569"/>


  <!-- ============================= -->
  <!-- PHASE 03 — PIPELINE -->
  <!-- ============================= -->

  <text x="20" y="230"
        font-family="Arial, sans-serif"
        font-size="13"
        font-weight="700"
        fill="#E2E8F0">
    PIPELINE
  </text>

  <text x="20" y="248"
        font-family="Arial, sans-serif"
        font-size="10"
        fill="#64748B">
    dbt · Airflow
  </text>


  <line x1="580" y1="232"
        x2="685" y2="232"
        stroke="#475569"
        stroke-width="3"/>

  <circle cx="580" cy="232"
          r="5"
          fill="#475569"/>

  <circle cx="685" cy="232"
          r="5"
          fill="#475569"/>


  <!-- ============================= -->
  <!-- PHASE 04 — ANALYTICS -->
  <!-- ============================= -->

  <text x="20" y="300"
        font-family="Arial, sans-serif"
        font-size="13"
        font-weight="700"
        fill="#E2E8F0">
    ANALYTICS
  </text>

  <text x="20" y="318"
        font-family="Arial, sans-serif"
        font-size="10"
        fill="#64748B">
    Power BI · Polish
  </text>


  <line x1="720" y1="302"
        x2="825" y2="302"
        stroke="#475569"
        stroke-width="3"/>

  <circle cx="720" cy="302"
          r="5"
          fill="#475569"/>

  <circle cx="825" cy="302"
          r="5"
          fill="#475569"/>


  <!-- ============================= -->
  <!-- CURRENT MARKER -->
  <!-- ============================= -->

  <line x1="405" y1="55"
        x2="405" y2="340"
        stroke="#38BDF8"
        stroke-width="1"
        stroke-dasharray="4 5"
        opacity="0.55"/>

  <text x="405" y="365"
        text-anchor="middle"
        font-family="Arial, sans-serif"
        font-size="9"
        font-weight="700"
        fill="#38BDF8"
        letter-spacing="1.5">
    CURRENT
  </text>


  <!-- ============================= -->
  <!-- DELIVERY -->
  <!-- ============================= -->

  <line x1="825" y1="340"
        x2="825" y2="380"
        stroke="#38BDF8"
        stroke-width="1"/>

  <circle cx="825" cy="340"
          r="6"
          fill="#0F172A"
          stroke="#38BDF8"
          stroke-width="2"/>

  <text x="825" y="398"
        text-anchor="middle"
        font-family="Arial, sans-serif"
        font-size="10"
        font-weight="700"
        fill="#38BDF8"
        letter-spacing="1">
    MVP DELIVERY
  </text>

</svg>

</div>

## Setup

> Weeks 1–2 cover the crawler only. Postgres, Docker Compose, dbt, and Airflow arrive in weeks 3–6.

```bash
git clone https://github.com/wayneworkspace/Ecommerce_Price_Gap_Tracker.git
cd Ecommerce_Price_Gap_Tracker

pip install -e ".[crawler,dev]"   # crawler = patchright + tenacity, dev = pytest
patchright install chrome         # real Chrome, not bundled Chromium
cp .env.example .env
```

One required variable in `.env`:

| Variable | Purpose |
|---|---|
| `SHOPEE_USER_DATA_DIR` | Path to the Chrome persistent profile holding your logged-in Shopee session. Shopee walls off anonymous sessions — no session, no scrape. See `docs/decisions/0004`. |

Log in once, by hand (persists in the profile; repeat only when the session expires):

```bash
python scripts/shopee_login.py
```

Run the pipeline and tests:

```bash
price-tracker-shopee   # writes to data/raw/ and data/staging/; SKUs configured in config/skus.yaml
pytest                 # no network, browser, or .env needed
```

## Data Model (planned)

| Table | Contents |
|---|---|
| `raw_prices` | `sku_id`, `source`, `seller_id`, `product_name`, `price`, `url`, `scraped_at` |
| `staging_prices` | Cast + deduplicated |
| `mart_price_gap` | `sku_id`, `source`, `price`, `price_change_pct` (day-over-day via `LAG()`) |
