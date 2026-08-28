"""Paths, environment, and the SKU list -- everything not tied to one source.

Configuration shared by EVERY data source.

Deliberately holds nothing Shopee-specific: per-source constants live in
sources/<source>/settings.py, and the SKU list is data, so it lives in
config/skus.yaml.

Read top to bottom in the order the pipeline needs it:

    1. Project root      -> PROJECT_ROOT
    2. Environment       -> USER_DATA_DIR
    3. Data directories  -> RAW_DIR, STAGING_DIR, SKUS_FILE
    4. Read skus.yaml    -> load_skus()
    5. Flatten into the listings to scrape -> load_source_listings()

Step 5 is what the pipeline actually calls; the four above only pave the way.
"""
from datetime import datetime, timezone
from pathlib import Path
import logging
import os

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Project root -- every other path is derived from it
# ---------------------------------------------------------------------------

def find_project_root() -> Path:
    """Walk up until a directory contains pyproject.toml.

    Not parents[n]: that number depends on how deep this file sits, so any
    reshuffle of the tree breaks it -- and breaks it SILENTLY, with no
    exception: RAW_DIR.mkdir(parents=True) still succeeds, it just creates
    data/raw outside the repo. The crawler reports success while data/raw in
    the repo stays empty.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError(
        "Project root not found -- no pyproject.toml in any parent directory."
    )


PROJECT_ROOT = find_project_root()


# ---------------------------------------------------------------------------
# 2. Environment (.env) -- per-machine values, never committed
# ---------------------------------------------------------------------------

# Point at the file explicitly instead of letting load_dotenv() guess, so the
# scripts work no matter which directory you launch them from.
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

# Used by: scripts/shopee_login.py, sources/shopee/extract.py
# Persistent Chrome profile folder (keeps the login session across runs).
# Read from .env rather than hard-coded, because it is an absolute path that
# differs on every machine.
USER_DATA_DIR = os.getenv("SHOPEE_USER_DATA_DIR")

# Whether the browser runs without a visible window.
#
# Default False, i.e. a real visible Chrome, because headless Chrome is
# markedly easier to fingerprint -- and the history of Issues 1-3 is a history
# of being detected. Do not flip this default to "make it faster".
#
# It exists as a switch at all because Airflow in a container has no desktop
# session, so a visible window is not merely slower there, it is impossible.
# Set SHOPEE_HEADLESS=1 in that environment and accept the higher block risk.
SHOPEE_HEADLESS = os.getenv("SHOPEE_HEADLESS", "").strip().lower() in {
    "1", "true", "yes"}


def require_user_data_dir() -> str:
    """Return the Chrome profile path, or fail with a fix-it message.

    Checked right BEFORE a browser is actually needed, deliberately NOT at
    module level: transform.py and the whole test suite import this module
    without ever touching a browser. Raising at import time would stop pytest
    from even collecting on a machine with no .env.
    """
    if not USER_DATA_DIR:
        raise RuntimeError(
            "SHOPEE_USER_DATA_DIR is missing from .env -- "
            "see .env.example for how to declare it."
        )
    return USER_DATA_DIR


# ---------------------------------------------------------------------------
# 3. Data directories -- created up front so the layers below can just write
# ---------------------------------------------------------------------------

# Used by: extract.py (writes), transform.py (reads)
# Raw JSON exactly as the source returned it, unprocessed.
RAW_DIR = PROJECT_ROOT / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


def raw_dir_for(moment: datetime) -> Path:
    """The day's raw folder, created on demand: data/raw/2026-08-28/.

    Partitioned by day rather than flat, because the flat layout does not
    survive scale: 100 listings a day is 36,500 files a year in one directory.
    That is slow for every glob, unpleasant in any file manager, and it makes
    "drop everything older than a quarter" a per-file decision instead of a
    single rmtree.

    The day comes from the SCRAPE time passed in, never from the clock at write
    time -- same discipline as scraped_at in the record itself, so a file always
    sits in the folder for the day it describes.

    Readers do not need to know about this: find_latest_raw_file() searches
    recursively, so files written by the old flat layout are still found.
    """
    day = moment.astimezone(timezone.utc).strftime("%Y-%m-%d")
    path = RAW_DIR / day
    path.mkdir(parents=True, exist_ok=True)
    return path

# Used by: transform.py (writes)
# JSON already mapped to the shared schema (sku, item_id, seller_id, price...).
STAGING_DIR = PROJECT_ROOT / "data" / "staging"
STAGING_DIR.mkdir(parents=True, exist_ok=True)

# The SKUs to track -- data, not code (see config/skus.yaml)
SKUS_FILE = PROJECT_ROOT / "config" / "skus.yaml"


# ---------------------------------------------------------------------------
# 4. Read config/skus.yaml into Python data
# ---------------------------------------------------------------------------

def load_skus() -> list[dict]:
    """Read the whole SKU list from config/skus.yaml.

    Also checks the document shape. Writing the YAML as a mapping instead of a
    list is an easy typo to make; unchecked, the loops below walk over string
    keys and blow up with AttributeError: 'str' object has no attribute 'get'
    -- which says nothing about where the config file is wrong.
    """
    with SKUS_FILE.open(encoding="utf-8") as f:
        parsed = yaml.safe_load(f)

    if not isinstance(parsed, list):
        raise ValueError(
            f"{SKUS_FILE} must be a LIST of SKUs (each entry starting with '- sku:'), "
            f"but parsed as {type(parsed).__name__}."
        )
    for i, entry in enumerate(parsed):
        if not isinstance(entry, dict):
            raise ValueError(
                f"{SKUS_FILE}: entry #{i + 1} must be a key/value block, "
                f"but is {type(entry).__name__}: {entry!r}"
            )
    return parsed


def _require_listing_list(sku: str, source: str, listings) -> list[dict]:
    """Check that one SKU's listings for a source really are a list of blocks.

    The old schema gave each source a single dict; it must now be a LIST of
    listings, because the same product is sold by several sellers. Falling back
    to the old shape has to be reported here rather than letting the layer
    below iterate over the characters of a string and fail cryptically.
    """
    if not isinstance(listings, list):
        raise ValueError(
            f"{SKUS_FILE}: sources.{source} of SKU {sku!r} must be a listing list "
            f"(each listing starting with '- shop_id:'), but is {type(listings).__name__}."
        )

    for listing in listings:
        if not isinstance(listing, dict):
            raise ValueError(
                f"{SKUS_FILE}: a listing of SKU {sku!r} on {source!r} must be a "
                f"key/value block, but is {type(listing).__name__}: {listing!r}"
            )
    return listings


# ---------------------------------------------------------------------------
# 5. Flatten into the listings that are ready to scrape
# ---------------------------------------------------------------------------

def listing_label(listing_cfg: dict) -> str:
    """Name one listing in logs: "SKU/item_id".

    The SKU alone cannot tell two listings of the same product apart; the
    item_id alone reads as a bare number with no hint of which product it is.
    """
    return f"{listing_cfg.get('sku')}/{listing_cfg.get('item_id')}"


def _merge_sku_into_listing(entry: dict, listing: dict) -> dict:
    """One listing, carrying down the SKU-level fields the pipeline needs.

    Flattens TWO configuration levels into one dict:

      - SKU level     : sku, name, reference_price  (join key to the list price)
      - listing level : shop_id, item_id, url, is_official  (identity on the site)

    The listing is spread last so it wins on any key collision -- the specific
    config always overrides the shared one.
    """
    merged = {
        "sku": entry.get("sku"),
        "name": entry.get("name"),
        "reference_price": entry.get("reference_price"),
        **listing,
    }

    # Defaulting to False is fine, but it has to speak up: every
    # `WHERE is_official` filter reads NULL as not-official, so forgetting to
    # declare it inverts the business question.
    if merged.get("is_official") is None:
        logger.warning(
            "Listing %s has no is_official in %s -- treating it as NOT official; "
            "if this really is the official store, the price gap will be wrong",
            listing_label(merged), SKUS_FILE)
        merged["is_official"] = False

    return merged


def _warn_about_duplicate_listings(listings: list[dict]) -> None:
    """Warn when the same SKU/item_id appears twice.

    Copy-pasting a seller and forgetting to change item_id is an easy mistake
    with this YAML shape. The damage: the same page is scraped twice, and the
    failures dict (keyed by label) collapses both listings into one row, so the
    batch size is reported wrong.

    Only a warning, never a raise: the data is still usable, it just wastes a
    request.
    """
    seen: set[str] = set()
    for listing in listings:
        label = listing_label(listing)
        if label in seen:
            logger.warning(
                "Listing %s appears more than once in %s -- it will be scraped "
                "twice, check the item_id", label, SKUS_FILE)
        seen.add(label)


def load_source_listings(source: str) -> list[dict]:
    """Every listing of every SKU on one marketplace, ready to scrape.

    This is what the pipeline actually calls (extract.py, transform.py, main.py).

    Iterates over LISTINGS, not SKUs: each listing is a real request to the
    site, so a SKU with three sellers yields three rows.

    A SKU that does not declare this source is SKIPPED with a warning rather
    than raised on: adding TikTok for one SKU must not stop the others from
    being scraped on Shopee. But if NO SKU declares it, that is a config error
    and it raises -- returning an empty list would let the crawler run an empty
    batch and report success.
    """
    resolved: list[dict] = []

    for entry in load_skus():
        sku = entry.get("sku")
        listings = (entry.get("sources") or {}).get(source)

        if not listings:
            logger.warning(
                "SKU %r declares no listing for source %r in %s -- skipping",
                sku, source, SKUS_FILE)
            continue

        for listing in _require_listing_list(sku, source, listings):
            resolved.append(_merge_sku_into_listing(entry, listing))

    if not resolved:
        raise ValueError(
            f"No SKU in {SKUS_FILE} declares source {source!r} -- "
            f"nothing to scrape."
        )

    _warn_about_duplicate_listings(resolved)
    return resolved


def get_listings_for_sku(sku: str, source: str) -> list[dict]:
    """Every listing of ONE SKU on one marketplace.

    The single-SKU lookup, for debugging and manual runs -- the pipeline uses
    load_source_listings() above.

    Differs from it in two ways: it returns the RAW listings (no sku /
    reference_price / is_official merged in), and an unknown SKU raises
    KeyError instead of being skipped -- here the caller named one SKU on
    purpose.
    """
    for entry in load_skus():
        if entry.get("sku") == sku:
            listings = (entry.get("sources") or {}).get(source)
            if not listings:
                raise KeyError(
                    f"SKU {sku!r} declares no listing for source {source!r} in {SKUS_FILE}"
                )
            return _require_listing_list(sku, source, listings)
    raise KeyError(f"SKU {sku!r} not found in {SKUS_FILE}")
