from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.backtest import nbm
from app.evidence.stations import Station

BLOCK = (Path(__file__).parent / "fixtures" / "nbm_nbs_KNYC_2026030101.txt").read_bytes()
NYC = Station("CLINYC", "KNYC", "Central Park", 40.78, -73.97, "America/New_York", "")


def test_parse_block_reads_real_bulletin_columns() -> None:
    p = nbm.parse_block(BLOCK)
    assert p is not None
    assert p["cycle"] == "2026-03-01T01:00:00+00:00"
    assert p["fhr"][:3] == [5, 8, 11]
    # Hand-read from the bulletin: TXN 36/19/30/26/42 under FHR 23/35/47/59/71, XND 2/6/3/7/2.
    got = [(h, t, x) for h, t, x in zip(p["fhr"], p["TXN"], p["XND"]) if t is not None]
    assert got == [(23, 36, 2), (35, 19, 6), (47, 30, 3), (59, 26, 7), (71, 42, 2)]
    assert p["TMP"][:3] == [39, 37, 35] and p["TSD"][:3] == [4, 3, 3]


def test_header_regex_finds_blocks_with_and_without_leading_space() -> None:
    buf = b"\n" + BLOCK + b"\n" + BLOCK.replace(b" KNYC ", b"KZZZ  ", 1)
    assert [m.group(1) for m in nbm.HEADER.finditer(buf)] == [b"KNYC", b"KZZZ"]


def _cache(tmp_path: Path, name: str, published: str) -> None:
    parsed = nbm.parse_block(BLOCK)
    (tmp_path / f"{name}.json").write_text(json.dumps(
        {"last_modified": published, "requests": 1, "stations": {"KNYC": parsed}}), encoding="utf-8")


def test_features_take_next_00z_max_and_climate_day_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nbm, "NBM_CACHE", tmp_path)
    monkeypatch.setitem(nbm.CYCLES, "eve", 1)  # the fixture is a 01Z run; serve it as the eve cycle
    _cache(tmp_path, "2026030101", "2026-03-01T01:50:00+00:00")
    # eve for Mar 2 reads the run of the day before (Mar 1); day max is in the 00Z Mar 3 column.
    f = nbm.features({"CLINYC": NYC}, "eve", [date(2026, 3, 2)])["CLINYC"]["2026-03-02"]
    assert (f["txn"], f["xnd"]) == (30, 3)
    # Climate day Mar 2 = 05Z Mar 2 .. 05Z Mar 3 (EST). Highest 3-hourly TMP in it is 30, at 21Z Mar 2.
    assert f["tmax"] == 30


def test_features_drop_a_bulletin_published_after_the_decision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nbm, "NBM_CACHE", tmp_path)
    monkeypatch.setitem(nbm.CYCLES, "eve", 1)
    # eve decision for Mar 2 in NYC is 8pm EST Mar 1 = 01Z Mar 2. Published later than that: unusable.
    _cache(tmp_path, "2026030101", "2026-03-02T01:00:01+00:00")
    assert nbm.features({"CLINYC": NYC}, "eve", [date(2026, 3, 2)])["CLINYC"] == {}
    _cache(tmp_path, "2026030101", datetime(2026, 3, 2, 1, tzinfo=timezone.utc).isoformat())
    assert "2026-03-02" in nbm.features({"CLINYC": NYC}, "eve", [date(2026, 3, 2)])["CLINYC"]
