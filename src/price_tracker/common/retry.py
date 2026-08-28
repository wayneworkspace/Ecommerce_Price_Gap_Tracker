"""Shared retry policy: three attempts, exponential backoff."""
import logging

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)

# How many times a retryable call is attempted in total (the first try included).
# Named rather than inlined because callers need to reason about "am I on the
# last attempt?" -- see is_final_attempt().
MAX_ATTEMPTS = 3


def is_final_attempt(retried_fn) -> bool:
    """True when the call running right now is the last one tenacity will make.

    Lets a decorated function do expensive work only once per batch of retries
    instead of once per attempt -- capturing debug evidence, for example.

    Reads `.statistics`, NOT `.retry.statistics`. tenacity copies the Retrying
    object for every call (so that recursive or concurrent calls to the same
    wrapped function do not share state) and hangs the live counters off the
    wrapper as `.statistics`. `.retry` is the original template, whose
    statistics dict stays empty forever -- reading it silently reports attempt 0
    on every attempt, which is exactly the sort of always-wrong answer this
    function must not give. There is a test pinning this down.

    Fails toward True: if the attempt number cannot be read (the function is not
    actually wrapped, or tenacity changes its internals), assume this is the
    last attempt. Capturing evidence one time too many costs a screenshot;
    capturing it zero times costs the only clue that distinguishes a captcha
    from a login wall.
    """
    try:
        attempt = retried_fn.statistics["attempt_number"]
    except (AttributeError, KeyError, TypeError):
        return True
    return attempt >= MAX_ATTEMPTS


def shopee_scrape_retry(*retryable_exceptions):
    """Build a retry decorator for the exception types a caller cares about.

    A decorator factory: each function passes in the exception types that ITS
    OWN code can fail with (different functions fail for different reasons),
    while the shared policy -- how many attempts, how long to wait -- is reused
    verbatim instead of copying tenacity boilerplate around.

    Usage:
        @shopee_scrape_retry(PWError, FetchFailedError)
        def fetch_one_listing(browser, listing_cfg):
            ...
    """
    if not retryable_exceptions:
        # tenacity accepts retry_if_exception_type(()) without complaint: the
        # decorator looks attached but never retries anything. Failing loudly
        # and early here beats discovering it in production at the exact moment
        # a retry was needed.
        raise TypeError(
            "shopee_scrape_retry() needs at least one exception type to retry on, "
            "e.g. @shopee_scrape_retry(PWError, FetchFailedError)."
        )

    return retry(
        reraise=True,
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=wait_exponential(multiplier=2, min=3, max=30),
        retry=retry_if_exception_type(retryable_exceptions),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
