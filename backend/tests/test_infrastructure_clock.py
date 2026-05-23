from datetime import UTC, datetime, timedelta

from harbor.infrastructure.clock.system import SystemClock


def test_now_returns_utc_aware_datetime() -> None:
    clock = SystemClock()
    ts = clock.now()
    assert isinstance(ts, datetime)
    assert ts.tzinfo is not None
    assert ts.utcoffset() == timedelta(0)


def test_now_is_monotonic_across_calls() -> None:
    clock = SystemClock()
    first = clock.now()
    second = clock.now()
    assert second >= first


def test_now_is_close_to_reference_utc() -> None:
    clock = SystemClock()
    sampled = clock.now()
    reference = datetime.now(UTC)
    # Sanity check the wall-clock alignment to within a generous window.
    assert abs((reference - sampled).total_seconds()) < 5.0
