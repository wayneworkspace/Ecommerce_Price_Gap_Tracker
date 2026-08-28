"""Turn a raw Shopee file into one record with a warehouse-ready schema."""
import json
import logging
from datetime import datetime
from pathlib import Path

from price_tracker.config import (
    RAW_DIR, STAGING_DIR, load_source_listings, listing_label)
from price_tracker.sources.shopee.settings import RAW_FILE_PREFIX
from price_tracker.sources.shopee.payload import (
    find_item_in_raw,
    describe_raw_problem,
    find_scraped_at,
    scraped_at_from_filename,
    format_timestamp,
)

logger = logging.getLogger(__name__)

# Shopee returns prices as integers pre-multiplied by 100_000
# (48_900_000_000 -> 489_000 VND). Named instead of sprinkling 100_000 through
# the code: getting this factor wrong breaks the entire mart layer with nothing
# raising an alarm, so it has to live in exactly one obvious place.
SHOPEE_PRICE_SCALE = 100_000


def find_latest_raw_file(item_id: str) -> Path:
    """Newest still-usable raw file for one listing.

    item_id is a REQUIRED parameter, deliberately without a default. The
    previous version globbed "shopee_raw_*.json", i.e. swept up every SKU and
    returned the single newest file -- harmless with one SKU, but from the
    second SKU on, N-1 SKUs are dropped SILENTLY: transform runs, raises
    nothing, and simply produces almost no data. Giving item_id a default is an
    invitation for that bug to come back.

    "Still usable" is the other half of the point. The old version took the file
    with the highest mtime outright, so a single poisoned file landing in
    data/raw/ became the chosen file forever, and every later transform run
    broke in the same spot. Broken once, broken always -- and the only cure was
    deleting the file by hand, assuming you guessed the cause.

    Now it walks newest to oldest and skips files it cannot read: one healthy
    scrape is enough to keep the pipeline moving. Every skipped file is logged
    with its name and the reason, so there is a trail to clean up.

    Searched recursively (rglob, not glob) because extract.py writes into
    per-day folders -- data/raw/2026-08-28/. Recursion is what lets both
    layouts coexist: the flat files scraped before that change are still found,
    so switching layouts did not orphan any history.
    """
    files = sorted(RAW_DIR.rglob(f"{RAW_FILE_PREFIX}_{item_id}_*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(
            f"No raw file for item_id={item_id} in {RAW_DIR} -- "
            f"run extract first.")

    skipped: list[str] = []
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        # UnicodeDecodeError has to be here: read_text(encoding="utf-8") raises
        # it BEFORE json.loads ever runs, and it is neither an OSError nor a
        # JSONDecodeError. extract.py writes with ensure_ascii=False, so the
        # files are full of multi-byte characters -- a Ctrl-C or a full disk
        # mid-write is enough to trigger it, and that would drop us right back
        # into the "broken once, broken always" trap.
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
        else:
            if find_item_in_raw(raw) is not None:
                if skipped:
                    # The warning still matters, but the consequence is far
                    # milder than it used to be: resolve_scraped_at() stamps the
                    # real SCRAPE time, so a record built from an old file
                    # carries the old date. Loaded into the warehouse it
                    # collides with the existing key and gets merged over,
                    # rather than posing as a fresh observation from today. In
                    # other words: today has NO data point -- and that is a
                    # truth worth seeing, instead of a flat price line that
                    # looks like a product whose price never moved.
                    logger.warning(
                        "Skipped %d broken raw file(s), falling back to an OLDER "
                        "scrape: %s. The record carries the old date, so today "
                        "counts as NOT scraped -- check whether we are being "
                        "blocked.",
                        len(skipped), path.name)
                return path
            reason = describe_raw_problem(raw)

        skipped.append(path.name)
        logger.warning("Skipping broken raw file %s -- %s", path.name, reason)

    raise FileNotFoundError(
        f"Found {len(files)} raw file(s) for item_id={item_id} in {RAW_DIR} but "
        f"none of them is usable. Skipped: {', '.join(skipped)}. "
        f"Run extract again for a fresh scrape."
    )


def parse_price(item: dict) -> float | None:
    """Convert Shopee's scaled integer to VND, or None if unusable.

    Uses `is None` and NOT `or`: `item.get("price") or ...` treats a price of 0
    as falsy and falls through to the fallback branch, destroying our ability to
    tell "genuinely free" apart from "Shopee returned no price". Those two cases
    must be handled differently downstream.

    Returns None rather than 0.0 when the price is missing, because 0.0 is a
    silent bug: down in the mart layer it looks like a valid price and produces
    price_change_pct = -100%. It does not raise either, because one broken SKU
    is not worth killing the whole run -- matching the "malformed price ->
    quarantine" direction stated in the README.
    """
    raw_price = item.get("price")
    if raw_price is None:
        raw_price = item.get("price_min")

    # Guard on TYPE, not just on None: Shopee has fields that return the price
    # as a string, and `"48900000000" / 100_000` raises a TypeError that escapes
    # straight out -- exactly the "one SKU kills the run" this function claims
    # to prevent. bool is excluded separately because in Python it subclasses
    # int (True / 100_000 = 1e-05, which looks entirely plausible).
    if isinstance(raw_price, bool) or not isinstance(raw_price, (int, float)):
        logger.warning(
            "SKU %s has an unusable price (price=%r, price_min=%r) -- returning price=None so the layer below can quarantine it",
            item.get("item_id"), item.get("price"), item.get("price_min"),
        )
        return None

    return raw_price / SHOPEE_PRICE_SCALE


def resolve_scraped_at(raw, raw_path: Path) -> str:
    """The time the page was scraped, never the time we ran.

    Telling those two moments apart is the whole point. find_latest_raw_file()
    may return an OLD scrape when the newest one is broken; if this function
    stamped datetime.now(), the resulting record would carry an OLD PRICE with
    TODAY'S TIMESTAMP. Run daily while Shopee blocks us for a week, and the mart
    layer receives a perfectly flat price series that looks entirely real --
    LAG() sees nothing unusual and nobody knows the data is fabricated.

    Even in the normal case this is the correct semantics: scraped_at is when we
    *scraped*, not when we *transformed*. Those only happen to be close together
    when main.py runs both in one go.

    Order of preference: the envelope first (accurate to the second, written by
    extract), then the filename (for files scraped by older code). If neither
    works it RAISES -- never silently falling back to now(), which is the very
    bug being fixed.
    """
    embedded = find_scraped_at(raw)
    if embedded is not None:
        return embedded

    from_name = scraped_at_from_filename(raw_path.name)
    if from_name is not None:
        return from_name

    raise ValueError(
        f"Cannot derive the scrape time for raw file {raw_path.name}: the "
        f"envelope has no 'scraped_at' and the filename carries no timestamp in "
        f"the 20260827T055522Z form. Guessing with the current clock is not an "
        f"option, because that produces a wrong row nobody ever notices."
    )


def build_record(raw_path: Path, listing_cfg: dict) -> dict:
    """Map a raw file plus its config into one record.

    listing_cfg is a REQUIRED parameter, deliberately without a default. A
    record has to carry TWO LAYERS of identity, and the upper one exists only in
    the config:

      - `sku`      -- the logical SKU ("G102-LIGHTSYNC"). This is the JOIN KEY
                      to reference_price in the mart layer. Many sellers list
                      the same product, each with a different item_id; without
                      this column the mart has no way back to the list price,
                      i.e. no price_gap_pct -- the entire point of the project.
      - `item_id`  -- the LISTING id on the marketplace. It used to be called
                      `sku_id`, which misnamed it: it was never a SKU, only the
                      id of one listing.
      - `source`   -- the marketplace. item_id is unique only WITHIN a
                      marketplace, so a natural key of
                      (sku, source, item_id, scraped_at) without source invites
                      a collision the moment TikTok lands in the same staging
                      directory.
      - `is_official` -- also from the config, absent from the Shopee payload.
                      Without it the mart cannot separate the official store's
                      price from anyone else's, which is the question we are
                      here to answer.

    Giving listing_cfg a default would let a caller forget to pass it and still
    run, producing records with no join key -- broken silently all the way down
    to the mart layer.
    """
    raw = json.loads(raw_path.read_text(encoding="utf-8"))

    # No longer indexing raw["data"]["data"]["item"] directly: on a poisoned
    # file that raises TypeError: 'NoneType' object is not subscriptable --
    # accurate, but it says nothing about which file is broken or why. Going
    # through find_item() makes the error point straight at the file to delete.
    item = find_item_in_raw(raw)
    if item is None:
        raise ValueError(
            f"Raw file {raw_path.name} is unusable -- {describe_raw_problem(raw)}"
        )

    return {
        # Layer 1 -- logical identity, from config/skus.yaml
        "sku": listing_cfg.get("sku"),
        "is_official": listing_cfg.get("is_official"),
        "source": "shopee",
        # Layer 2 -- identity on the marketplace.
        # item_id comes from the CONFIG and not from the payload, even though
        # the payload has it too. Two reasons: (1) if the payload lacks the
        # field, the record carries item_id=None and save_record names the file
        # shopee_record_None_<ts>.json -- two listings scraped in the same
        # second overwrite each other; (2) the payload returns an int while
        # skus.yaml and find_latest_raw_file() use str, and letting the types
        # drift means every future join against the config seed needs a cast
        # nobody documented.
        # extract.fetch_one_listing() already cross-checks the payload against
        # the config before writing the file, so taking it from the config is
        # safe.
        "item_id": listing_cfg.get("item_id"),
        "seller_id": item.get("shop_id"),
        "product_name": item.get("title"),
        "price": parse_price(item),
        "url": raw.get("url"),
        "scraped_at": resolve_scraped_at(raw, raw_path),
    }


def save_record(record: dict) -> Path:
    # The filename comes from the record's scraped_at, NOT from the wall clock.
    # Two reasons:
    #
    # 1. Idempotency -- re-running transform on the same raw file produces the
    #    same filename and overwrites instead of adding a copy. data/staging/
    #    will be loaded into the warehouse; every re-run producing a new file
    #    means manufacturing duplicate rows downstream, exactly what dbt's
    #    incremental unique_key exists to clean up.
    # 2. Traceability -- record_<ts>.json lines up directly with the
    #    raw_<ts>.json it came from, with no mtime archaeology needed.
    """Write the record to data/staging, named by scrape time."""
    ts = format_timestamp(datetime.fromisoformat(record["scraped_at"]))
    out_path = STAGING_DIR / f"shopee_record_{record['item_id']}_{ts}.json"
    out_path.write_text(json.dumps(
        record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved record: {out_path}")
    return out_path


if __name__ == "__main__":
    # Run transform standalone over the newest scrape of EVERY LISTING, not over
    # a single file -- otherwise a manual run reproduces exactly the "N-1
    # listings dropped" bug that find_latest_raw_file(item_id) just fixed.
    #
    # One try block per listing, for the same reason as in fetch_all_listings():
    # a listing with no raw file yet (blocked today) raises FileNotFoundError,
    # and without isolation it would take down the listings behind it that have
    # perfectly healthy files -- precisely the kind of data loss this whole file
    # is built to prevent.
    _failures = {}
    for _listing in load_source_listings("shopee"):
        _label = listing_label(_listing)
        try:
            _record = build_record(
                find_latest_raw_file(str(_listing["item_id"])), _listing)
            save_record(_record)
            print(json.dumps(_record, indent=2, ensure_ascii=False))
        except Exception as _exc:
            _failures[_label] = f"{type(_exc).__name__}: {_exc}"
            logger.warning("Could not package %s: %s", _label, _exc)

    if _failures:
        raise SystemExit(
            "Some listings could not be packaged: "
            + "; ".join(f"{k}: {v}" for k, v in _failures.items()))
