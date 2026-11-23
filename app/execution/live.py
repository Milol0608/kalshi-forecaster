"""Live executor. Locked by default.

Construction runs the full gate check, so no code path can hold a LiveExecutor
without having passed it. Order placement itself is built in milestone 7.
"""

from __future__ import annotations

from datetime import datetime

from app.config import Settings, assert_live_allowed


class LiveExecutor:
    def __init__(self, settings: Settings, now: datetime | None = None) -> None:
        assert_live_allowed(settings, now)
        self.settings = settings

    def place_order(self, *args: object, **kwargs: object) -> None:
        # Re-check on every order: the gate file can expire while the process runs.
        assert_live_allowed(self.settings)
        raise NotImplementedError("Live order placement is not built yet (milestone 7).")
