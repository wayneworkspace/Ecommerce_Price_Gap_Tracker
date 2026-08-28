"""Tests for common/retry.py."""

import pytest

from price_tracker.common.retry import (
    MAX_ATTEMPTS, is_final_attempt, shopee_scrape_retry)


class _Boom(Exception):
    pass


def test_is_final_attempt_is_true_only_on_the_last_attempt(monkeypatch):
    """The whole point: expensive work runs once per batch of retries, not once
    per attempt.

    This test exists because the first implementation read
    `fn.retry.statistics` and was wrong in the most dangerous way -- it returned
    True on EVERY attempt, so the caller kept doing the expensive thing three
    times while looking correct."""
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda _s: None)
    seen = []

    @shopee_scrape_retry(_Boom)
    def always_fails():
        seen.append(is_final_attempt(always_fails))
        raise _Boom("nope")

    with pytest.raises(_Boom):
        always_fails()

    assert seen == [False] * (MAX_ATTEMPTS - 1) + [True]


def test_is_final_attempt_reports_true_for_a_function_it_cannot_read():
    """Fails toward True: an unreadable attempt count must not silently disable
    the evidence capture it guards. Losing the screenshot is worse than taking
    one too many."""
    def not_wrapped():
        pass

    assert is_final_attempt(not_wrapped) is True


def test_shopee_scrape_retry_rejects_being_called_with_no_exceptions():
    """Calling it with no arguments must fail LOUDLY and EARLY.

    tenacity accepts retry_if_exception_type(()) without complaint, so the
    decorator looks attached but never retries anything. A silent failure like
    that only surfaces in production, at the moment a retry was most needed."""
    with pytest.raises(TypeError):
        shopee_scrape_retry()
