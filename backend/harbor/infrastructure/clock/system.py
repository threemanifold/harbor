"""Wall-clock :class:`~harbor.domain.ports.clock.Clock` adapter.

Returns timezone-aware ``datetime`` values in UTC so events have a stable
ordering regardless of host configuration.
"""

from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    """Real-time clock; always returns UTC-aware ``datetime``."""

    def now(self) -> datetime:
        return datetime.now(UTC)
