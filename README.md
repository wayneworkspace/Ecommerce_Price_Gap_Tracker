# Ecommerce Price Gap Tracker

**Automated ELT pipeline for MAP-compliance monitoring across Vietnamese e-commerce channels**

Scrapes Logitech SKU prices from the official store, Shopee, and TikTok Shop, then flags resellers pricing below the official reference.

![Status](https://img.shields.io/badge/Status-In%20Progress-yellow)


`~1 MB / month` · `3 Channels` · `8 Weeks` · `MAP Monitoring`

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

## Planned Power BI Views


|     # | View                          | Question it answers                                      |
| ----: | ----------------------------- | -------------------------------------------------------- |
| **1** | **Price Gap %**               | Core metric của toàn bộ project — phải có                |
| **2** | **Seller Compliance Ranking** | Thể hiện được góc nhìn business + seller behavior        |
| **3** | **Historical Price Trend**    | Cho thấy bạn xử lý time-series và historical data        |
| **4** | **Pipeline Health Tile**      | Rất tốt để thể hiện tư duy Data Engineering / monitoring |
| **5** | **Weekly Executive Summary**  | Cho thấy bạn biết biến data thành insight cho business   |


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

Marketplace → Ingestion → Storage → Orchestration → Transformation  → Mart → BI


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

## Why These Languages & Tools?

### Tools
| Tool | Why it's here | What breaks without it |
|---|---|---|
| **Airflow** | Scrape → stage → transform must run in order; a failed step must not corrupt downstream data | Independent cron jobs give no dependency guarantee |
| **dbt** | Window functions, schema tests, incremental merge — with lineage | Ad hoc SQL: no lineage, no quality gate, full reprocessing every run |
| **PostgreSQL** | Sufficient relational store at this volume | N/A — no case for more at this scale |
| **Docker Compose** | Reproducible environment for reviewers | Manual setup replication required |
| **Power BI** | Consumption layer | N/A |

### Languages
| Tool | Why it's here | What breaks without it |
|---|---|---|
| **Playwright** | Marketplace pages render client-side JS | No usable HTML to parse |
| **Pandas / NumPy** | Structural validation at the ingestion layer | Malformed records reach the warehouse undetected |
| **Pathlib** |  |  |
| **Datetime** |  |  |
| **Json** |  |  |
| **Logging** |  |  |

At approximately 1 MB/month, introducing distributed infrastructure would add operational complexity without solving an actual scaling problem.

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

## 02 — Project Status

|  # | Component                  | Status         |
| -: | -------------------------- | -------------- |
| 01 | Playwright crawler         | Implemented  |
| 02 | Raw ingestion & validation | Implemented  |
| 03 | PostgreSQL storage         | In progress |
| 04 | dbt transformations        | In progress |
| 05 | Airflow orchestration      | In progress |
| 06 | Power BI dashboard         | Planned      |


---

## Setup

> Weeks 1–2 cover the crawler only. Postgres, Docker Compose, dbt, and Airflow arrive in weeks 3–6.

```bash
git clone https://github.com/wayneworkspace/Ecommerce_Price_Gap_Tracker.git
cd Ecommerce_Price_Gap_Tracker

pip install -e ".[crawler,dev]"   # crawler = patchright + tenacity, dev = pytest
patchright install chrome         # real Chrome, not bundled Chromium
cp .env.example .env
