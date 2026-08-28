"""Entry point: scrape every configured listing, then build one record each."""
import json
import logging

from price_tracker.config import load_source_listings, listing_label
from price_tracker.sources.shopee.extract import (
    fetch_all_listings, BatchIncompleteError)
from price_tracker.sources.shopee.transform import build_record, save_record

logger = logging.getLogger(__name__)

# Above this share of failed listings the batch reports red.
#
# "Any failure is red" was the right rule at one listing and the wrong one at a
# hundred: at that size a few failures every day are ordinary, so a red run
# every single morning teaches everyone to ignore the colour -- and the day the
# scrape truly breaks, that lesson has already been learned.
#
# 20% is a starting point, not a measurement. It says "losing a fifth of the
# catalogue is an incident, losing a handful is Tuesday". Revisit it once there
# is a few weeks of real failure data to look at.
#
# Note what this does NOT change: every failure is still counted, logged and
# printed. The threshold only governs the exit code.
MAX_FAILURE_RATE = 0.2


def batch_failed(records: list, failures: dict, threshold: float = MAX_FAILURE_RATE) -> bool:
    """Whether this batch is bad enough to report red.

    Split out from main() so the rule can be tested without running a scrape,
    and so the reasoning sits in one readable place.

    Two cases the plain ratio gets wrong on its own:
      - nothing configured at all -> not red here; load_source_listings() has
        already raised for that, and 0/0 is not a failure rate.
      - nothing succeeded -> always red, whatever the threshold is set to. A
        totally empty harvest is an incident even if someone sets the threshold
        to 1.0.
    """
    total = len(records) + len(failures)
    if total == 0:
        return False
    if not records:
        return True
    return len(failures) / total > threshold


def run_batch(listing_configs: list[dict] | None = None) -> tuple[list[dict], dict[str, str]]:
    """Scrape and package a batch; return records plus per-listing failures.

    It does not raise here but hands both halves back to the caller: main()
    still has to print a summary before reporting red. Raising straight away
    would mean printing nothing at exactly the moment -- a failed batch -- when
    there is most to look at.

    Packaging failures are collected into the same `failures` dict as scraping
    failures, under the SAME listing_label(). From the "does this listing have
    data today" point of view the two are the same thing; and if the two stages
    named the same listing differently (one "SKU/item_id", the other a raw
    filename), no later reconciliation or alerting per listing would be possible.
    """
    if listing_configs is None:
        listing_configs = load_source_listings("shopee")

    failures: dict[str, str] = {}
    try:
        fetched = fetch_all_listings(listing_configs)
    except BatchIncompleteError as exc:
        # The batch did run the whole list, it is just missing a few listings.
        # Take what was scraped and keep going instead of dropping everything.
        fetched = exc.succeeded
        failures.update(exc.failures)

    records: list[dict] = []
    for raw_path, listing_cfg in fetched:
        label = listing_label(listing_cfg)
        try:
            record = build_record(raw_path, listing_cfg)
            save_record(record)
            records.append(record)
        except Exception as exc:
            failures[label] = f"{type(exc).__name__}: {exc}"
            logger.warning("Could not package %s (%s): %s",
                           label, raw_path.name, exc)

    return records, failures


def main():
    """Run one batch, print a summary, exit red if any listing failed."""
    listing_configs = load_source_listings("shopee")
    records, failures = run_batch(listing_configs)

    total = len(records) + len(failures)
    rate = len(failures) / total if total else 0.0

    print("=== Batch summary ===")
    print(f"Listings configured : {len(listing_configs)}")
    print(f"Succeeded           : {len(records)}")
    print(f"Failed              : {len(failures)} ({rate:.0%}, red above {MAX_FAILURE_RATE:.0%})")

    for record in records:
        official = "official store" if record.get("is_official") else "other seller"
        print(f"  OK   {record['sku']}/{record['item_id']} ({official}) "
              f"-- {record['price']} -- {record['scraped_at']}")
    for label, why in failures.items():
        print(f"  FAIL {label} -- {why}")

    if records:
        print("=== Last record ===")
        print(json.dumps(records[-1], indent=2, ensure_ascii=False))

    # The summary is printed first, then we report red. Raising makes Airflow
    # mark the task failed.
    #
    # Failures below the threshold are still WARNED about, never swallowed: a
    # green run that lost listings has to leave a trace somewhere, or the
    # threshold turns from "tolerate noise" into "hide losses".
    #
    # Passing `records` rather than an empty list: BatchIncompleteError uses
    # len(succeeded) + len(failures) as the denominator, so an empty list would
    # print "1/1 listings failed" when the truth is 1/5 -- the log would read
    # like a total wipeout.
    if batch_failed(records, failures):
        raise BatchIncompleteError(records, failures)
    if failures:
        logger.warning(
            "%d/%d listings failed (%.0f%%), under the %.0f%% threshold -- "
            "reporting green, but these listings have no data today: %s",
            len(failures), total, rate * 100, MAX_FAILURE_RATE * 100,
            ", ".join(failures))


if __name__ == "__main__":
    main()
