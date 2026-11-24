"""nbm-blend-v1: NOAA National Blend of Models, calibrated per station, mixed with the market price.

Chosen by the backtest (docs/BACKTEST.md): neither NBM nor our own model beats the market alone,
but a logistic mix of calibrated NBM and the market mid did, by a small margin, at the evening
decision. Per-station calibration and the mixing weights are fitted on history by
`python -m app.backtest.run --decision eve --export data/models/nbm_blend_v1.json` and read from
that file here; nothing is fitted live.

Each hour:
  fetch_nbm      downloads the newest NBS station bulletin (~30 MB, NOAA open-data bucket, no key)
                 once per cycle and stores our stations' blocks.
  run_nbm_forecasts  for each tradable event whose climate day hasn't started: NBM features ->
                 calibrated N(mu, sd) -> bucket probabilities -> logistic mix with each bucket's
                 market mid -> renormalised over the event. Events without a two-sided price on
                 every bucket are skipped, since the mix needs the market for every bucket.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.models import Blend, NbmEmos, bucket_probs
from app.config import Settings
from app.db.models import Forecast, WeatherForecastRaw
from app.evidence.stations import Station, climate_day_utc
from app.ingest.rules_parser import integer_range

MODEL_VERSION = "nbm-blend-v1"
SOURCE = "nbm_nbs"
BUCKET = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"
HEADER = re.compile(rb"\n ?([A-Z0-9]{3,8}) +NBM(?: V[\d.]+)? +NBS GUIDANCE +(\d+)/(\d+)/(\d{4}) +(\d{2})00 UTC")
ROWS = ("TXN", "XND", "TMP", "TSD")


def key_for(cycle: datetime) -> str:
    return f"blend.{cycle:%Y%m%d}/{cycle:%H}/text/blend_nbstx.t{cycle:%H}z"


def parse_block(block: bytes) -> dict | None:
    """Rows by forecast hour: {"cycle": iso, "fhr": [...], "TXN": [...], ...} (None = blank)."""
    lines = block.decode("ascii", "replace").splitlines()
    m = HEADER.search(b"\n" + lines[0].encode())
    if not m:
        return None
    mon, day, yr, hh = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
    cycle = datetime(yr, mon, day, hh, tzinfo=timezone.utc)
    rows = {ln[:4].strip(): ln for ln in lines[1:] if ln[:4].strip()}
    if "FHR" not in rows:
        return None
    fhr_line = rows["FHR"]
    ends = [mm.end() + 4 for mm in re.finditer(r"\d+", fhr_line[4:])]
    out: dict = {"cycle": cycle.isoformat(), "fhr": [int(fhr_line[e - 3:e]) for e in ends]}
    for name in ROWS:
        ln = rows.get(name, "")
        vals: list[int | None] = []
        for e in ends:
            try:
                vals.append(int(ln[e - 3:e].strip()))
            except ValueError:
                vals.append(None)
        out[name] = vals
    return out


def parse_bulletin(content: bytes, icaos: set[str]) -> dict[str, dict]:
    """Our stations' blocks from a whole bulletin."""
    buf = b"\n" + content
    heads = list(HEADER.finditer(buf))
    out = {}
    for m, nxt in zip(heads, heads[1:] + [None]):
        sid = m.group(1).decode()
        if sid in icaos:
            parsed = parse_block(buf[m.start() + 1: nxt.start() if nxt else len(buf)])
            if parsed:
                out[sid] = parsed
    return out


def station_features(blk: dict, d: date, st: Station) -> dict | None:
    """txn/xnd: NBM's daytime max for day d (00Z column of d+1) and its SD.
    tmax/tsd: highest 3-hourly TMP inside the climate day (midnight-midnight local standard time,
    which can differ from NBM's daytime max on days a front passes) and the TSD at that hour."""
    cycle = datetime.fromisoformat(blk["cycle"])
    valid = [cycle + timedelta(hours=h) for h in blk["fhr"]]
    max_at = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(days=1)
    i = next((k for k, v in enumerate(valid) if v == max_at), None)
    if i is None or blk["TXN"][i] is None or blk["XND"][i] is None:
        return None
    a, b = climate_day_utc(d, st.timezone)
    tmps = [(blk["TMP"][k], blk["TSD"][k]) for k, v in enumerate(valid) if a <= v <= b and blk["TMP"][k] is not None]
    tmax, tsd = max(tmps) if tmps else (blk["TXN"][i], blk["XND"][i])
    return {"txn": blk["TXN"][i], "xnd": blk["XND"][i], "tmax": tmax, "tsd": tsd if tsd is not None else blk["XND"][i]}


# ---------------------------------------------------------------- fetch

@dataclass
class NbmFetch:
    cycle: str | None = None
    stations: int = 0
    skipped: str | None = None
    calls: int = 0
    errors: list[str] = field(default_factory=list)


def _stored_cycle(session: Session) -> str | None:
    params = session.scalars(select(WeatherForecastRaw.params).where(WeatherForecastRaw.source == SOURCE)
                             .order_by(WeatherForecastRaw.fetched_at.desc()).limit(1)).first()
    return (params or {}).get("key")


def fetch_nbm(session: Session, http: httpx.Client, stations: list[Station], as_of: datetime,
              run_id: int | None = None, lookback_hours: int = 4) -> NbmFetch:
    """Store our stations' blocks from the newest published NBS bulletin, once per cycle."""
    rep = NbmFetch()
    top = as_of.replace(minute=0, second=0, microsecond=0)
    for h in range(lookback_hours + 1):
        cycle = top - timedelta(hours=h)
        key = key_for(cycle)
        try:
            r = http.head(f"{BUCKET}/{key}")
            rep.calls += 1
        except httpx.HTTPError as e:
            rep.errors.append(f"{key}: {type(e).__name__}")
            continue
        if r.status_code != 200:
            continue
        rep.cycle = key
        if _stored_cycle(session) == key:
            rep.skipped = "already stored"
            return rep
        try:
            g = http.get(f"{BUCKET}/{key}")
            rep.calls += 1
            g.raise_for_status()
        except httpx.HTTPError as e:
            rep.errors.append(f"{key}: {type(e).__name__}")
            return rep
        published = parsedate_to_datetime(g.headers["last-modified"]).isoformat() if "last-modified" in g.headers else None
        blocks = parse_bulletin(g.content, {s.icao for s in stations})
        for s in stations:
            if s.icao in blocks:
                session.add(WeatherForecastRaw(run_id=run_id, source=SOURCE, station=s.code, fetched_at=as_of,
                                               params={"key": key, "last_modified": published}, response=blocks[s.icao]))
                rep.stations += 1
        session.flush()
        return rep
    rep.skipped = f"no bulletin in the last {lookback_hours} h"
    return rep


# ---------------------------------------------------------------- forecast

@dataclass
class Params:
    stations: dict[str, NbmEmos]
    blend: Blend
    meta: dict[str, Any]


def load_params(path: Path) -> Params:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Params({c: NbmEmos(np.array(p)) for c, p in data["nbm_emos"].items()},
                  Blend(np.array(data["nbm_blend"])), data.get("meta", {}))


def _latest_block(session: Session, code: str, as_of: datetime) -> WeatherForecastRaw | None:
    return session.scalars(select(WeatherForecastRaw).where(
        WeatherForecastRaw.source == SOURCE, WeatherForecastRaw.station == code, WeatherForecastRaw.fetched_at <= as_of)
        .order_by(WeatherForecastRaw.fetched_at.desc()).limit(1)).first()


def event_probabilities(params: Params, code: str, feat: dict, ranges: list[tuple[float, float]],
                        mids: list[float]) -> tuple[list[float], list[float], float, float]:
    """(blended, nbm-only) bucket probabilities, plus the calibrated mean and SD."""
    mu, sd = params.stations[code].predict(*(np.array([float(feat[k])]) for k in ("txn", "tmax", "xnd")))
    p_nbm = bucket_probs(float(mu[0]), float(sd[0]), ranges)
    p = params.blend.predict(p_nbm, np.array(mids))
    p = p / p.sum()
    return [float(x) for x in p], [float(x) for x in p_nbm], float(mu[0]), float(sd[0])


def run_nbm_forecasts(session: Session, stations: dict[str, Station], settings: Settings, as_of: datetime,
                      run_id: int | None = None):
    from app.forecast.weather_model import EventSkip, ForecastRunResult, _latest_snapshot, _tradable_events

    result = ForecastRunResult()
    if not settings.nbm_params_file.is_file():
        result.skipped.append(EventSkip("*", f"{settings.nbm_params_file} missing; run the backtest export"))
        return result
    params = load_params(settings.nbm_params_file)
    max_age = timedelta(hours=settings.nbm_max_age_hours)
    for event_ticker, pairs in sorted(_tradable_events(session).items()):
        def skip(reason: str) -> None:
            result.skipped.append(EventSkip(event_ticker, reason))

        if any(p.status != "ok" or not p.event_check_ok for _, p in pairs):
            skip("parse needs review or event buckets don't partition")
            continue
        station = stations.get(pairs[0][1].station_id or "")
        target = pairs[0][1].resolution_date
        if station is None or target is None:
            skip("unknown station or date")
            continue
        if as_of >= climate_day_utc(target, station.timezone)[0]:
            skip("climate day already started")
            continue
        if station.code not in params.stations:
            skip(f"no calibration for {station.code}")
            continue
        raw = _latest_block(session, station.code, as_of)
        if raw is None or as_of - raw.fetched_at > max_age:
            skip("no NBM bulletin fresh enough")
            continue
        feat = station_features(raw.response, target, station)
        if feat is None:
            skip("NBM bulletin doesn't cover this day's max")
            continue
        pairs = sorted(pairs, key=lambda mp: integer_range(mp[1]))
        ranges = [integer_range(p) for _, p in pairs]
        snaps = [_latest_snapshot(session, m.ticker, as_of) for m, _ in pairs]
        if any(s is None or s.yes_bid is None or s.yes_ask is None or s.yes_ask <= s.yes_bid for s in snaps):
            skip("a bucket has no two-sided market price to mix with")
            continue
        mids = [float(s.yes_bid + s.yes_ask) / 2 for s in snaps]  # type: ignore[union-attr,operator]
        probs, p_nbm, mu, sd = event_probabilities(params, station.code, feat, ranges, mids)
        inputs = {"model_version": MODEL_VERSION, "features": feat, "ranges": ranges, "mids": mids,
                  "params": params.meta.get("fitted_at")}
        inputs_hash = hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()
        details = {"station": station.code, "target_date": target.isoformat(), "nbm_key": raw.params.get("key"),
                   "features": feat, "mu": round(mu, 2), "sd": round(sd, 2)}
        for (market, _), p, pn, s, mid in zip(pairs, probs, p_nbm, snaps, mids):
            f = Forecast(run_id=run_id, ticker=market.ticker, event_ticker=event_ticker, decided_at=as_of,
                         model_version=MODEL_VERSION, inputs_hash=inputs_hash, probability=p,
                         market_snapshot_id=s.id, yes_bid=s.yes_bid, yes_ask=s.yes_ask, n_members=0,
                         details={**details, "p_nbm": round(pn, 4), "mid": mid})
            session.add(f)
            result.forecasts.append(f)
    session.flush()
    return result
