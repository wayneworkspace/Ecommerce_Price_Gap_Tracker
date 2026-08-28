"""Scrape Shopee: drive a real browser, capture the price API, write raw JSON."""
from price_tracker.config import (
    RAW_DIR, SHOPEE_HEADLESS, raw_dir_for, require_user_data_dir,
    load_source_listings, listing_label)
from price_tracker.sources.shopee.settings import PDP_API_PATH, RAW_FILE_PREFIX
from price_tracker.common.retry import shopee_scrape_retry, is_final_attempt
from price_tracker.sources.shopee.payload import (
    find_item, describe_problem, format_timestamp)
from patchright.sync_api import sync_playwright, Error as PWError
from pathlib import Path
from datetime import datetime, timezone
import logging
import random
import time
import json


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s"
)
logger = logging.getLogger(__name__)

# Diagnostic evidence only, not worth a long wait: Playwright's default is 30s,
# and this block runs on ALL 3 retry attempts -> another 90s burned per failed
# fetch. Set on BOTH content() and screenshot(): capping only the screenshot
# leaves content() free to hang for 30s, which caps nothing in practice.
DEBUG_CAPTURE_TIMEOUT_MS = 10_000

GOTO_TIMEOUT_MS = 30_000
RESPONSE_TIMEOUT_MS = 40_000

# Random pause BETWEEN listings. The README (Challenges) has long promised a
# "randomized 3-8s delay between requests" while the code never had a single
# line of it -- with exactly one listing nobody could tell, but from the second
# listing on it is the difference between respecting the ToS and hammering the
# same endpoint back to back.
# The unit is LISTINGS, not SKUs: every listing is a real request, and two
# listings of the same SKU are still two knocks on Shopee's door.
# Randomised rather than fixed: perfectly even spacing between requests is the
# most recognisable signature of automation there is.
DELAY_BETWEEN_LISTINGS_MIN_S = 3.0
DELAY_BETWEEN_LISTINGS_MAX_S = 8.0

# How long debug evidence is kept before a later run deletes it.
#
# Evidence is only useful while you are still investigating the failure that
# produced it, and it is the bulkiest thing this pipeline writes: a full-page
# Shopee screenshot runs to several MB. Unbounded, a batch of 100 listings with
# a bad week fills gigabytes that nobody will ever open.
#
# A week is chosen to survive a weekend plus a couple of days -- long enough
# that a Monday investigation can still see Friday's failure.
DEBUG_EVIDENCE_MAX_AGE_DAYS = 7


class FetchFailedError(Exception):
    """One scrape attempt produced no usable JSON.

    Every "retryable" failure must be funnelled into this type, because it is
    the only one (together with PWError) that tenacity will retry -- see
    retry.py.
    """
    pass


class BatchIncompleteError(Exception):
    """The batch ran to the end, but some listings are missing.

    Carries BOTH the successful part and the broken part, so the caller can keep
    working with what it has before reporting red -- instead of losing the whole
    batch over one listing.

    `succeeded` is deliberately loosely typed: the scrape stage puts
    (raw path, listing config) pairs in it, while main() puts records in after
    packaging. Both only need one thing from it -- to be COUNTABLE -- so that
    the denominator in the message is the real batch size. Passing an empty list
    here would report "1/1 listings failed" when the truth is 1/5, and the log
    would read like a total wipeout.
    """

    def __init__(self, succeeded: list, failures: dict[str, str]):
        self.succeeded = succeeded
        self.failures = failures
        detail = "; ".join(f"{label}: {why}" for label, why in failures.items())
        super().__init__(
            f"{len(failures)}/{len(failures) + len(succeeded)} listings failed -- {detail}"
        )


def sleep_between_listings() -> None:
    """Pause a random 3-8 seconds before the next listing.

    Split out into its own function instead of calling time.sleep() inline, so
    tests can replace it without actually waiting.
    """
    seconds = random.uniform(DELAY_BETWEEN_LISTINGS_MIN_S, DELAY_BETWEEN_LISTINGS_MAX_S)
    logger.info("Waiting %.1fs before the next listing", seconds)
    time.sleep(seconds)


def extract_json_or_fail(response) -> dict:
    """Parse the response body as JSON, or raise a retryable error."""
    try:
        return response.json()
    except Exception as exc:
        raise FetchFailedError(
            f"Could not read JSON from response {response.url}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


def validate_payload_or_fail(payload: dict) -> dict:
    """Reject a 200-with-error payload before it reaches disk.

    Checks whether the payload is usable, RETURNS the item, raises
    FetchFailedError if not.

    This was a real hole in the previous version: extract_json_or_fail() only
    guarantees the body PARSES as JSON. But when blocked or throttled, Shopee
    returns HTTP 200 with perfectly valid JSON shaped like
    {"error": 1, "data": null} -- it parses fine, so it slipped through and was
    counted as a success. The knock-on damage:

      - tenacity does not retry, even though this is the most retry-worthy case
        of all (a temporary block);
      - the poisoned file is written into data/raw/ and becomes the newest one,
        so transform.py picks exactly it on EVERY later run -- broken once,
        broken forever.

    Calling this inside fetch_one_listing()'s try block is deliberate: the
    FetchFailedError lands in the existing except, so debug evidence is captured
    automatically (one look at the HTML tells you whether it was a login wall or
    a captcha) before it is re-raised for tenacity. And because it raises before
    the write, nothing reaches disk.
    """
    item = find_item(payload)
    if item is None:
        raise FetchFailedError(
            f"Shopee returned valid but unusable JSON -- {describe_problem(payload)}"
        )
    return item


def dump_debug_evidence(page, debug_dir: Path | None = None,
                        item_id: str | None = None) -> None:
    """Save HTML and a screenshot while the page is still alive.

    The filename includes item_id now that a batch covers several listings: the
    timestamp is only accurate to the second, so two listings failing within the
    same second would overwrite each other's evidence -- and this is the only
    thing that distinguishes a captcha from a login wall. Even without a
    collision, the filename should say which listing it belongs to.
    """
    if debug_dir is None:
        debug_dir = RAW_DIR.parent / "debug"

    stem = f"fail_{item_id}" if item_id else "fail"
    ts = format_timestamp(datetime.now(timezone.utc))

    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"{stem}_{ts}.html").write_text(
            page.content(timeout=DEBUG_CAPTURE_TIMEOUT_MS), encoding="utf-8")
        logger.info("Saved debug HTML -> %s", debug_dir / f"{stem}_{ts}.html")
    except Exception as exc:
        logger.warning("Could not save debug HTML (%s: %s)",
                       type(exc).__name__, exc)

    try:
        page.screenshot(path=str(debug_dir / f"{stem}_{ts}.png"), full_page=True,
                        timeout=DEBUG_CAPTURE_TIMEOUT_MS)
        logger.info("Saved debug screenshot -> %s", debug_dir / f"{stem}_{ts}.png")
    except Exception as exc:
        logger.warning("Could not take debug screenshot (%s: %s)",
                       type(exc).__name__, exc)


def prune_debug_evidence(debug_dir: Path | None = None,
                         max_age_days: int = DEBUG_EVIDENCE_MAX_AGE_DAYS) -> int:
    """Delete debug evidence older than max_age_days. Returns how many went.

    Housekeeping, so it never raises: failing to delete yesterday's screenshot
    is not a reason to abandon today's scrape.

    Only touches the two filename shapes dump_debug_evidence() writes
    (fail_*.html, fail_*.png). Deleting by age alone would make this function a
    loaded gun pointed at whatever else someone later puts in that folder.
    """
    if debug_dir is None:
        debug_dir = RAW_DIR.parent / "debug"
    if not debug_dir.is_dir():
        return 0

    cutoff = time.time() - max_age_days * 86_400
    removed = 0

    for pattern in ("fail_*.html", "fail_*.png"):
        for path in debug_dir.glob(pattern):
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
                path.unlink()
                removed += 1
            except OSError as exc:
                logger.warning("Could not prune debug file %s (%s: %s)",
                               path.name, type(exc).__name__, exc)

    if removed:
        logger.info("Pruned %d debug file(s) older than %d days from %s",
                    removed, max_age_days, debug_dir)
    return removed


@shopee_scrape_retry(PWError, FetchFailedError)
def fetch_one_listing(browser, listing_cfg: dict) -> Path:
    """Scrape a single listing on an already-open browser.

    The unit is a listing, not a SKU: one SKU can be sold by many sellers, each
    with its own item_id and its own page -- so every listing is a real request
    to Shopee.

    The browser is passed in rather than opened here: the whole batch shares one
    launch_persistent_context(), because that call locks USER_DATA_DIR and
    opening/closing it repeatedly invites lock contention -- and the history of
    Issues 1-3 shows that profile trouble means captcha trouble.

    The retry decorator sits HERE and not on fetch_all_listings(): a listing
    with a transient hiccup deserves a retry of itself only, not a Chrome
    restart and a re-scrape of the listings that already succeeded.
    """
    # Required fields are checked HERE and not in the config layer: one broken
    # line in skus.yaml should only kill its own listing. Raising in the config
    # layer kills the whole batch before the browser even opens.
    #
    # ValueError is deliberately NOT in tenacity's retry list (PWError,
    # FetchFailedError): a missing url is still missing on the third attempt.
    missing = [k for k in ("item_id", "url") if not listing_cfg.get(k)]
    if missing:
        raise ValueError(
            f"Listing {listing_cfg!r} is missing required fields: {', '.join(missing)} "
            f"-- fix it in config/skus.yaml"
        )

    item_id = str(listing_cfg["item_id"])
    product_url = listing_cfg["url"]
    label = listing_label(listing_cfg)

    page = None
    try:
        page = browser.new_page()
        page.bring_to_front()
        page.on("console", lambda msg: logger.warning(
            "CONSOLE[%s]: %s", msg.type, msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: logger.warning(
            "PAGE ERROR: %s", exc))

        logger.info("Starting scrape of %s", label)

        with page.expect_response(
            lambda r: PDP_API_PATH in r.url and item_id in r.url,
            timeout=RESPONSE_TIMEOUT_MS,
        ) as response_info:
            page.goto(product_url, wait_until="domcontentloaded",
                      timeout=GOTO_TIMEOUT_MS)

        response = response_info.value
        logger.info("Captured API response: %s", response.url)

        data = extract_json_or_fail(response)

        # Considered and dropped: restoring the content-type == application/json
        # guard the previous version had. It does not catch any extra case -- a
        # non-JSON body already raises in extract_json_or_fail(), and
        # misshapen JSON is caught by validate_payload_or_fail(). It could only
        # ever block a response that has an odd content-type AND parses as JSON
        # AND has the right shape -- i.e. data that is perfectly usable. A layer
        # that blocks nothing extra only makes the code longer.
        item = validate_payload_or_fail(data)

        # Cross-check the payload's item_id against the configured one. The
        # response filter only does STRING MATCHING on the URL, so in principle
        # another response whose id contains ours as a substring could slip
        # through. The damage is very hard to trace: a file named
        # shopee_raw_<our_id>_*.json holding a different product, whose record
        # then travels down to the mart with the wrong seller and the wrong
        # price. Cheap to check, expensive to discover later.
        actual_item_id = item.get("item_id")
        if actual_item_id is not None and str(actual_item_id) != item_id:
            raise FetchFailedError(
                f"Captured the wrong response: configured item_id={item_id} but "
                f"the payload returned item_id={actual_item_id}"
            )

    except (PWError, FetchFailedError) as exc:
        logger.warning("This attempt failed (%s): %s", label, exc)
        # Evidence only on the LAST attempt. Capturing on all three costs up to
        # 20s per attempt (content + screenshot, each capped at
        # DEBUG_CAPTURE_TIMEOUT_MS) and writes three near-identical copies of
        # the same failure. At one listing that was invisible; at a hundred it
        # is the difference between a 25-minute batch and a two-hour one, and
        # between megabytes and gigabytes on disk.
        #
        # The first two attempts lose nothing: if the listing recovers on
        # attempt 2 there was nothing to investigate, and if it does not, the
        # final attempt captures the same wall.
        if page is not None and is_final_attempt(fetch_one_listing):
            dump_debug_evidence(page, item_id=item_id)

        if isinstance(exc, FetchFailedError):
            raise
        raise FetchFailedError(
            f"Could not capture an API response containing item_id={item_id} "
            f"(goto {GOTO_TIMEOUT_MS}ms / expect_response {RESPONSE_TIMEOUT_MS}ms): {exc}"
        ) from exc

    finally:
        # Close the PAGE, not the browser: the browser belongs to the whole
        # batch and is owned and cleaned up by fetch_all_listings(). Leaving the
        # page open means every listing (and every retry) leaves a live tab
        # behind, eating RAM until the batch ends.
        if page is not None:
            try:
                page.close()
            except Exception as exc:
                logger.warning("Failed to close page (%s: %s)",
                               type(exc).__name__, exc)

    # ONE single call to now(), used for both the filename and the scraped_at
    # field. Calling it twice gives two values milliseconds apart -- small, but
    # it breaks exactly the invariant transform relies on: the filename and the
    # envelope must name the same moment, because transform reads the envelope
    # first and the filename second.
    scraped_at = datetime.now(timezone.utc)
    out_path = raw_dir_for(scraped_at) / \
        f"{RAW_FILE_PREFIX}_{item_id}_{format_timestamp(scraped_at)}.json"

    # scraped_at goes inside the file, not just in its name: filenames get
    # changed by copies and backups, while the content carries the scrape time
    # wherever it travels.
    out_path.write_text(
        json.dumps({"data": data, "url": product_url,
                    "scraped_at": scraped_at.isoformat()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("Saved raw -> %s", out_path)
    return out_path


def fetch_all_listings(
    listing_configs: list[dict] | None = None,
) -> list[tuple[Path, dict]]:
    """Scrape every listing in one browser session.

    Returns (raw file path, listing config) pairs rather than paths alone: the
    packaging stage needs `sku` and `is_official` back from the config, and
    neither is present in the payload Shopee returns. Returning only Paths would
    force the caller to map filenames back to configs -- fragile and pointless.

    Three decisions worth stating, so a later reader knows they were choices and
    not accidents:

    1. The browser is opened once for the whole batch (see fetch_one_listing).

    2. One failed listing does NOT stop the batch. Shopee blocks per product
       page rather than per account, so abandoning the rest because the first
       listing failed is throwing away data that was still there for the taking.

    3. But the batch still RAISES at the end if any listing failed -- after
       everything has been attempted. Keep what you got, but Airflow has to see
       red: a batch that silently reports green while missing listings turns
       into a data hole that only surfaces on a dashboard weeks later. This
       threshold can be loosened later (e.g. red only above X% failures) once we
       know how Shopee actually behaves -- there is not enough data to pick that
       threshold yet, so the strictest one wins.
    """
    if listing_configs is None:
        listing_configs = load_source_listings("shopee")

    user_data_dir = require_user_data_dir()
    fetched: list[tuple[Path, dict]] = []
    failures: dict[str, str] = {}

    # Housekeeping before the batch, not after: a run that dies halfway still
    # gets its old evidence cleared, and today's fresh evidence is never at
    # risk of being pruned by its own run.
    prune_debug_evidence()

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir,
            channel="chrome",
            headless=SHOPEE_HEADLESS,
        )
        try:
            for index, listing_cfg in enumerate(listing_configs):
                # Pause BETWEEN listings, never before the first one: waiting
                # before doing anything at all only makes every run slower
                # without spacing out a single request.
                if index > 0:
                    sleep_between_listings()

                label = listing_label(listing_cfg)
                try:
                    fetched.append(
                        (fetch_one_listing(browser, listing_cfg), listing_cfg))
                # Catching broadly here is deliberate: the point of this block
                # is to ISOLATE one failing listing. A config error (a missing
                # url key) should also kill only that listing, not the batch.
                # Exception rather than BaseException, so Ctrl-C still stops
                # everything immediately.
                except Exception as exc:
                    failures[label] = f"{type(exc).__name__}: {exc}"
                    logger.warning("Skipping listing %s after exhausting retries: %s",
                                   label, exc)
        finally:
            try:
                browser.close()
            except Exception as exc:
                logger.warning("Failed to close browser (%s: %s)",
                               type(exc).__name__, exc)

    logger.info("Batch done: %d listings ok, %d listings failed",
                len(fetched), len(failures))

    if failures:
        raise BatchIncompleteError(fetched, failures)

    return fetched


if __name__ == "__main__":
    fetch_all_listings()
