"""Build data/stations.json: settlement station code -> verified coordinates and forecast URL.

For each CLI code named in parsed market rules (e.g. CLIMDW):
  1. Guess the ICAO id as K + last three letters (CLIMDW -> KMDW).
  2. Confirm with IEM: that station's archived NWS climate reports must carry the SAME
     product code (…-CLIMDW). If not, the guess is wrong and the station is left out.
  3. Take coordinates and time zone from the NWS station record (api.weather.gov).
  4. Look up the NWS gridpoint forecast URL for those coordinates.

Run: uv run python -m scripts.build_stations
Review the diff of data/stations.json before committing it.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import ParsedRule
from app.db.session import get_engine

OUT = Path("data/stations.json")


def main() -> int:
    settings = get_settings()
    with Session(get_engine()) as s:
        codes = sorted(set(s.scalars(select(ParsedRule.station_id).where(ParsedRule.status == "ok"))))
    nws = httpx.Client(
        base_url="https://api.weather.gov",
        headers={"User-Agent": settings.nws_user_agent, "Accept": "application/geo+json"},
        timeout=30,
    )
    iem = httpx.Client(timeout=60)
    stations: dict[str, dict[str, object]] = {}
    failures: list[str] = []

    for code in codes:
        icao = "K" + code.removeprefix("CLI")
        cli = iem.get(
            "https://mesonet.agron.iastate.edu/json/cli.py", params={"station": icao, "year": settings_year()}
        ).json()["results"]
        products = {r.get("product", "").rsplit("-", 1)[-1] for r in cli}
        if code not in products:
            failures.append(f"{code}: IEM reports for {icao} carry {sorted(products)[:3]}, not {code}")
            continue
        st = nws.get(f"/stations/{icao}").json()
        lon, lat = st["geometry"]["coordinates"]
        pts = nws.get(f"/points/{lat:.4f},{lon:.4f}").json()["properties"]
        stations[code] = {
            "icao": icao,
            "name": st["properties"]["name"],
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "elevation_m": st["properties"]["elevation"]["value"],
            "timezone": st["properties"]["timeZone"],
            "nws_forecast_url": pts["forecast"],
        }
        print(f"{code} -> {icao}  {stations[code]['name']}  ({lat:.3f}, {lon:.3f})  {stations[code]['timezone']}")
        time.sleep(0.3)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(stations, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nwrote {len(stations)} stations to {OUT}")
    for f in failures:
        print("NOT MAPPED:", f)
    return 1 if failures else 0


def settings_year() -> int:
    from datetime import date

    return date.today().year


if __name__ == "__main__":
    sys.exit(main())
