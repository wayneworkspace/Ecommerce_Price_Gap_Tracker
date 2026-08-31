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

<br>

`~1 MB / month` · `3 Channels` · `8 Weeks` · `MAP Monitoring`

</div>

---

## What This Demonstrates

| ARCHITECTURE | RELIABILITY | ENGINEERING |
|---|---|---|
| Right-sized architecture | Idempotent ELT | Production habits |
| PostgreSQL at ~1 MB/month | Append-only raw layer | Retry / backoff |
| No unnecessary Kafka/Spark/object storage | Incremental merge | Schema tests |
| Cost-conscious design | Quarantine layer | Dependency ordering |

> **Design principle:** use the smallest architecture that solves the problem reliably.
> Data volume does not justify Kafka, Spark, or object storage at this scale.

---

## Business Problem

Unauthorized resellers undercut official pricing on marketplaces, eroding brand trust and margin for authorized channels.

Manual cross-channel price checks don't scale and produce stale, inconsistent snapshots.

> **Core question**
>
> Which SKUs and sellers on Shopee/TikTok are currently priced below Logitech's official reference price — and by how much?

The pipeline turns those snapshots into a repeatable, auditable ELT workflow that can surface pricing gaps over time.

---

<details>
<summary><strong>Planned Power BI Views (10)</strong></summary>

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

---

## Architecture

![Architecture — scrape to Power BI](architecture.png)

<p align="center">

`COLLECT` → `STORE` → `TRANSFORM` → `ORCHESTRATE` → `ANALYZE`

</p>

The architecture is intentionally small: one PostgreSQL instance, browser-based ingestion where required, dbt for transformation and testing, Airflow for dependency-ordered execution, and Power BI as the consumption layer.

---

## Pipeline Flow

<pre>
MARKETPLACE
     │
     ▼
 PLAYWRIGHT
   CRAWLER
     │
     ▼
   RAW DATA
 append-only
     │
     ▼
 POSTGRESQL
   STORAGE
     │
     ▼
    dbt
 TRANSFORM
     │
     ▼
  AIRFLOW
 ORCHESTRATE
     │
     ▼
PRICE GAP MART
     │
     ▼
 POWER BI
  ANALYZE
</pre>

### Processing stages

| Stage | Responsibility |
|---|---|
| **Collect** | Scrape official and marketplace prices |
| **Raw** | Preserve source observations as append-only records |
| **Validate** | Check structure and route malformed records to quarantine |
| **Stage** | Cast fields and remove duplicate observations |
| **Transform** | Calculate price gaps and day-over-day changes |
| **Orchestrate** | Run scrape → stage → transform in dependency order |
| **Analyze** | Surface pricing violations and trends in Power BI |

---

## Why These Tools?

| Tool | Why it's here | What breaks without it |
|---|---|---|
| **Playwright** | Marketplace pages render client-side JS | No usable HTML to parse |
| **Pandas / NumPy** | Structural validation at the ingestion layer | Malformed records reach the warehouse undetected |
| **Airflow** | Scrape → stage → transform must run in order; a failed step must not corrupt downstream data | Independent cron jobs give no dependency guarantee |
| **dbt** | Window functions, schema tests, incremental merge — with lineage | Ad hoc SQL: no lineage, no quality gate, full reprocessing every run |
| **PostgreSQL** | Sufficient relational store at this volume | N/A — no case for more at this scale |
| **Docker Compose** | Reproducible environment for reviewers | Manual setup replication required |
| **Power BI** | Consumption layer | N/A |

> **Architecture decision:** Kafka, Spark, and object storage are deliberately excluded.
>
> At approximately 1 MB/month, introducing distributed infrastructure would add operational complexity without solving an actual scaling problem.

---

## Challenges & Solutions

| Challenge | Solution | Outcome |
|---|---|---|
| Anti-bot / selector instability | Validated selectors manually against a single SKU **before** writing any DAG | More predictable scraping |
| Transient scrape failures | `tenacity` exponential backoff + randomized 3–8s delays | Retry-safe ingestion |
| Re-runs must not duplicate rows | dbt incremental merge (`unique_key`) — no redundant "dedup DAG" | Idempotent pipeline |
| Malformed price fields after cast | Routed to `quarantine`, never silently into `mart` | Clean analytical layer |
| Marketplace ToS | Rate-limited, respects `robots.txt`; cached HTML samples enable offline demo | Controlled and reproducible demo |

---

## 02 — Roadmap

<pre>
                         01       02       03       04       05       06       07       08
                         │        │        │        │        │        │        │        │

CRAWLER                  ●━━━━━━━━●
                         Playwright · Raw ingestion
                         └─ IN PROGRESS

DATABASE                          ●━━━━━━━━●
                                  PostgreSQL · Docker
                                  └─ PLANNED

PIPELINE                                    ●━━━━━━━━●
                                            dbt · Airflow
                                            └─ PLANNED

ANALYTICS                                              ●━━━━━━━━●
                                                        Power BI · Polish
                                                        └─ PLANNED


                         ────────────────────────────────────────────────────────────────
                                                                  ◆ MVP DELIVERY
</pre>

### Roadmap milestones

| Phase | Weeks | Deliverable |
|---|---:|---|
| **Crawler** | 1–2 | Validated Playwright crawler + raw price ingestion |
| **Database** | 3–4 | Reproducible PostgreSQL + Docker environment |
| **Pipeline** | 5–6 | dbt transformations + Airflow orchestration |
| **Analytics** | 7–8 | Power BI dashboards + final polish |

---

## Setup

> Weeks 1–2 cover the crawler only. Postgres, Docker Compose, dbt, and Airflow arrive in weeks 3–6.

```bash
git clone https://github.com/wayneworkspace/Ecommerce_Price_Gap_Tracker.git
cd Ecommerce_Price_Gap_Tracker

pip install -e ".[crawler,dev]"   # crawler = patchright + tenacity, dev = pytest
patchright install chrome         # real Chrome, not bundled Chromium
cp .env.example .env