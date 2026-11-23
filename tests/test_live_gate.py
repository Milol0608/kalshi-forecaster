"""Safety test (spec Section 8): the live executor refuses to start unless all three gate conditions hold."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import LIVE_CONFIRMATION_PHRASE, LiveTradingLocked, Mode, Settings, check_live_gate
from app.execution.live import LiveExecutor

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def write_gate(path: Path, passed_at: datetime | str, passed: bool = True) -> Path:
    stamp = passed_at.isoformat() if isinstance(passed_at, datetime) else passed_at
    path.write_text(json.dumps({"passed": passed, "passed_at": stamp}), encoding="utf-8")
    return path


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "mode": Mode.LIVE,
        "live_trading_confirmed": LIVE_CONFIRMATION_PHRASE,
        "gate_file": write_gate(tmp_path / "gate1_passed.json", NOW - timedelta(days=1)),
    }
    base.update(overrides)
    # _env_file=None so a developer's local .env can't change test results.
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def test_all_conditions_met_unlocks(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    assert check_live_gate(settings, NOW) == []
    LiveExecutor(settings, NOW)


def test_default_settings_are_shadow_and_locked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for var in ("MODE", "LIVE_TRADING_CONFIRMED", "GATE_FILE"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.mode is Mode.SHADOW
    with pytest.raises(LiveTradingLocked):
        LiveExecutor(settings, NOW)


@pytest.mark.parametrize("mode", [Mode.SHADOW, Mode.DEMO])
def test_wrong_mode_locks(tmp_path: Path, mode: Mode) -> None:
    with pytest.raises(LiveTradingLocked, match="MODE"):
        LiveExecutor(make_settings(tmp_path, mode=mode), NOW)


@pytest.mark.parametrize("phrase", ["", "yes", "YES-I-UNDERSTAND-REAL-MONEY", " yes-i-understand-real-money"])
def test_wrong_confirmation_locks(tmp_path: Path, phrase: str) -> None:
    with pytest.raises(LiveTradingLocked, match="LIVE_TRADING_CONFIRMED"):
        LiveExecutor(make_settings(tmp_path, live_trading_confirmed=phrase), NOW)


def test_missing_gate_file_locks(tmp_path: Path) -> None:
    with pytest.raises(LiveTradingLocked, match="does not exist"):
        LiveExecutor(make_settings(tmp_path, gate_file=tmp_path / "nope.json"), NOW)


def test_stale_gate_file_locks(tmp_path: Path) -> None:
    gate = write_gate(tmp_path / "g.json", NOW - timedelta(days=30, seconds=1))
    with pytest.raises(LiveTradingLocked, match="older than 30 days"):
        LiveExecutor(make_settings(tmp_path, gate_file=gate), NOW)


def test_gate_file_just_inside_window_unlocks(tmp_path: Path) -> None:
    gate = write_gate(tmp_path / "g.json", NOW - timedelta(days=29, hours=23))
    LiveExecutor(make_settings(tmp_path, gate_file=gate), NOW)


@pytest.mark.parametrize(
    "content, expected",
    [
        ("not json", "unreadable"),
        ('{"passed": true}', "unreadable"),
        ('{"passed": false, "passed_at": "2026-11-21T00:00:00+00:00"}', "passed=true"),
        ('{"passed": "yes", "passed_at": "2026-11-21T00:00:00+00:00"}', "passed=true"),
        ('{"passed": true, "passed_at": "2026-11-21T00:00:00"}', "no timezone"),
        ('{"passed": true, "passed_at": "2027-01-01T00:00:00+00:00"}', "future"),
    ],
)
def test_bad_gate_file_locks(tmp_path: Path, content: str, expected: str) -> None:
    gate = tmp_path / "g.json"
    gate.write_text(content, encoding="utf-8")
    with pytest.raises(LiveTradingLocked, match=expected):
        LiveExecutor(make_settings(tmp_path, gate_file=gate), NOW)


def test_fresh_mtime_does_not_rescue_stale_gate(tmp_path: Path) -> None:
    """Age is read from passed_at, so touching or copying an old file doesn't make it fresh."""
    gate = write_gate(tmp_path / "g.json", NOW - timedelta(days=90))
    gate.touch()
    with pytest.raises(LiveTradingLocked, match="older than"):
        LiveExecutor(make_settings(tmp_path, gate_file=gate), NOW)


def test_all_failures_reported_together(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path, mode=Mode.SHADOW, live_trading_confirmed="", gate_file=tmp_path / "missing.json"
    )
    assert len(check_live_gate(settings, NOW)) == 3


def test_place_order_rechecks_gate(tmp_path: Path) -> None:
    """The gate expires while the process runs: place_order must re-check against real time."""
    passed_at = datetime.now(timezone.utc) - timedelta(days=31)
    gate = write_gate(tmp_path / "g.json", passed_at)
    settings = make_settings(tmp_path, gate_file=gate)
    # Constructed one day after the pass, when the gate was fresh; by real time it has expired.
    executor = LiveExecutor(settings, passed_at + timedelta(days=1))
    with pytest.raises(LiveTradingLocked, match="older than"):
        executor.place_order()
