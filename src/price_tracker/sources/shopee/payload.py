"""What a usable Shopee payload looks like, and what a raw filename carries.

The raw-file contract: the shape of a Shopee payload, and what the filename
carries.

Kept separate because two places need this knowledge without depending on each
other: extract.py (blocking bad data before it reaches disk) and transform.py
(skipping files that are already bad). Putting it in either one would force a
cross-import -- and transform.py deliberately must not drag in patchright,
which is why there is a separate `crawler` extra.

The real shape, taken from a file in data/raw/:

    {"bff_meta": {...}, "error": null, "error_msg": null,
     "data": {"item": {...}, "account": {...}, ...}}

extract.py wraps it in an envelope before writing:

    {"data": <the payload above>, "url": ..., "scraped_at": "2026-08-27T05:55:22Z"}
"""
import re
from datetime import datetime, timezone

# The timestamp in a raw FILENAME: shopee_raw_<item_id>_20260827T055522Z.json
# extract.py uses it to name files, transform.py to read the scrape time back
# for files whose envelope has no scraped_at. Both sides must share this one
# constant: any drift and files are written in one format, read in another.
RAW_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_RAW_TIMESTAMP_PATTERN = re.compile(r"(\d{8}T\d{6}Z)")


def format_timestamp(moment: datetime) -> str:
    """Format a UTC timestamp for a raw filename.

    Stamps the time used to name a file. Always normalised to UTC first."""
    return moment.astimezone(timezone.utc).strftime(RAW_TIMESTAMP_FORMAT)


def find_scraped_at(raw) -> str | None:
    """Read scraped_at from the envelope, or None if unusable.

    Verifies the value actually parses rather than only checking "is a non-empty
    string": garbage is still a string, and it would flow straight into the
    record and on into the warehouse. Returning None on garbage falls through to
    the next source (the filename) -- a hand-edited or partly corrupted envelope
    usually still has an intact filename.

    Returns a normalised value so every record shares one format, whether the
    envelope wrote 'Z' or '+00:00'.
    """
    if not isinstance(raw, dict):
        return None
    value = raw.get("scraped_at")
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Missing tzinfo is treated as UTC: extract.py always writes an offset, so a
    # file without one is unusual -- but guessing UTC is still safer than
    # guessing the clock of whichever machine runs transform, which may sit in a
    # different timezone than the one that scraped.
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def scraped_at_from_filename(name: str) -> str | None:
    """Recover the scrape time from a filename.

    Returns None if the name does not follow the convention.

    Used for files scraped before the envelope carried scraped_at -- data/raw/
    holds real files of that kind, and treating them as broken would throw away
    perfectly good data.

    Searched by regex rather than sliced by position: the filename contains
    several `_` separators, and positional slicing would silently match the
    wrong part the moment the naming convention changes.
    """
    match = _RAW_TIMESTAMP_PATTERN.search(name)
    if match is None:
        return None
    try:
        moment = datetime.strptime(match.group(1), RAW_TIMESTAMP_FORMAT)
    except ValueError:
        return None
    return moment.replace(tzinfo=timezone.utc).isoformat()


def find_item(payload) -> dict | None:
    """Return the item block, or None if Shopee refused us.

    Returns None instead of raising: the two callers need to react differently
    -- extract.py turns it into a FetchFailedError so tenacity retries, while
    find_latest_raw_file() just skips that file and moves on.
    """
    if not isinstance(payload, dict):
        return None

    # Shopee does NOT return HTTP 4xx/5xx when it blocks or throttles -- it
    # returns 200 with valid JSON whose "error" is non-null. So the check has to
    # look at the `error` value, not at the HTTP status or at whether the JSON
    # parses.
    #
    # Truthiness rather than `is not None`: error=0 means NO error, same as
    # null. Only a value other than 0/null is a real error.
    if payload.get("error"):
        return None

    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    item = data.get("item")
    # An empty item is as useless as a missing one, so `{}` is rejected too.
    if not isinstance(item, dict) or not item:
        return None

    return item


def describe_problem(payload) -> str:
    """Say in one phrase why a payload is unusable.

    A short description of where the payload is broken, for error messages and
    logs.

    Quotes Shopee's own error/error_msg verbatim -- swallowing those two values
    throws away the best clue for telling a block apart from a transient hiccup.
    """
    if not isinstance(payload, dict):
        return f"payload is not a dict but a {type(payload).__name__}"
    if payload.get("error"):
        return (f"Shopee reported an error: error={payload.get('error')!r}, "
                f"error_msg={payload.get('error_msg')!r}")
    if not isinstance(payload.get("data"), dict):
        return f"payload['data'] is unusable: {payload.get('data')!r}"
    return "payload['data']['item'] is missing or empty"


def find_item_in_raw(raw) -> dict | None:
    """Return the item block from a raw file, either envelope shape.

    Reads the item out of a raw file's CONTENT -- accepting both file shapes.

    extract.py currently writes the envelope {"data": <payload>, "url": ...},
    but files scraped before the envelope existed are bare payloads. data/raw/
    holds real files of both kinds. Both contain usable data, so treating the
    old shape as "broken" and skipping it would throw away good data.
    """
    if isinstance(raw, dict) and "data" in raw:
        item = find_item(raw.get("data"))
        if item is not None:
            return item
    return find_item(raw)


def describe_raw_problem(raw) -> str:
    """Say in one phrase why a raw file is unusable.

    Tells the two shapes apart by the "url" key: only the envelope has one.
    Without that distinction, a bare payload would be described one level too
    deep and reported as "item missing" when the real problem is that Shopee
    returned an error.
    """
    if not isinstance(raw, dict):
        return f"file content is not a dict but a {type(raw).__name__}"
    if "url" in raw and "data" in raw:
        return describe_problem(raw.get("data"))
    return describe_problem(raw)
