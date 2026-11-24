from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.models import Blend, NbmEmos
from app.db.models import WeatherForecastRaw
from app.evidence.stations import Station
from app.forecast import nbm_blend
from app.forecast.nbm_blend import Params, event_probabilities, fetch_nbm, load_params, parse_bulletin

BLOCK = (Path(__file__).parent / "fixtures" / "nbm_nbs_KNYC_2026030101.txt").read_bytes()
NYC = Station("CLINYC", "KNYC", "Central Park", 40.78, -73.97, "America/New_York", "")
OTHER = BLOCK.replace(b" KNYC ", b" KAAA ", 1)
BULLETIN = b"1\n" + OTHER + b"\n" + BLOCK
INF = float("inf")


def test_parse_bulletin_keeps_only_our_stations() -> None:
    got = parse_bulletin(BULLETIN, {"KNYC"})
    assert list(got) == ["KNYC"] and got["KNYC"]["cycle"] == "2026-03-01T01:00:00+00:00"


def _transport(calls: list[str]) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(f"{req.method} {req.url.path}")
        if "/blend.20260301/01/" not in req.url.path:  # only the 01Z run is published yet
            return httpx.Response(404)
        return httpx.Response(200, content=BULLETIN if req.method == "GET" else b"",
                              headers={"last-modified": "Sun, 01 Mar 2026 01:48:00 GMT"})
    return httpx.MockTransport(handler)


def test_fetch_takes_newest_published_cycle_once(db_session: Session) -> None:
    calls: list[str] = []
    as_of = datetime(2026, 3, 1, 2, 30, tzinfo=timezone.utc)  # 02Z not out yet, 01Z is
    with httpx.Client(transport=_transport(calls)) as http:
        r = fetch_nbm(db_session, http, [NYC], as_of)
        assert (r.cycle, r.stations, r.skipped) == ("blend.20260301/01/text/blend_nbstx.t01z", 1, None)
        again = fetch_nbm(db_session, http, [NYC], as_of)
    assert again.skipped == "already stored" and again.stations == 0
    assert sum(c.startswith("GET") for c in calls) == 1  # the 30 MB file is downloaded once per cycle
    raw = db_session.scalars(select(WeatherForecastRaw).where(WeatherForecastRaw.source == "nbm_nbs")).one()
    assert raw.station == "CLINYC" and raw.params["last_modified"].startswith("2026-03-01T01:48")


def test_event_probabilities_sum_to_one_and_lean_on_the_market() -> None:
    # Identity-ish calibration: mu = txn, sd = 2. Blend weights like the fitted ones (market ~1, model ~0.2).
    params = Params({"CLINYC": NbmEmos(np.array([0.0, 1.0, 0.0, np.log(2.0), 0.0]))},
                    Blend(np.array([0.0, 0.2, 1.0])), {})
    feat = {"txn": 30, "xnd": 2, "tmax": 30, "tsd": 2}
    ranges = [(-INF, 27), (28, 29), (30, 31), (32, 33), (34, INF)]
    mids = [0.05, 0.20, 0.50, 0.20, 0.05]
    p, p_nbm, mu, sd = event_probabilities(params, "CLINYC", feat, ranges, mids)
    assert abs(sum(p) - 1) < 1e-9 and abs(sum(p_nbm) - 1) < 1e-9
    assert (mu, round(sd, 6)) == (30.0, 2.0)
    # With the market weighted ~5x the model, each bucket stays near its market mid.
    assert all(abs(a - m) < 0.12 for a, m in zip(p, mids))


def test_exported_parameters_load_and_cover_every_station() -> None:
    path = Path("data/models/nbm_blend_v1.json")
    params = load_params(path)
    stations = json.loads(Path("data/stations.json").read_text(encoding="utf-8"))
    assert set(params.stations) == set(stations)
    assert params.meta["decision"] == "eve" and len(params.blend.params) == 3


def test_bulletins_without_a_version_in_the_header_parse_too() -> None:
    # From 2026-11-03 the header reads "NBM  NBS GUIDANCE" (no "V4.3"); missing it lost 19 days once.
    new = BLOCK.replace(b"NBM V4.3 NBS GUIDANCE", b"NBM  NBS GUIDANCE", 1)
    got = parse_bulletin(b"1\n" + new, {"KNYC"})
    assert got["KNYC"]["TXN"][got["KNYC"]["fhr"].index(23)] == 36
