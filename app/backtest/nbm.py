"""NOAA National Blend of Models (NBM) station forecasts for the backtest.

Source: the NBS text bulletin in NOAA's open-data bucket (no account, public domain; NOAA asks for
attribution). One ~30 MB file per hourly cycle holds ~9,600 station blocks sorted by station id,
so we fetch only our stations' blocks with HTTP byte ranges, finding each by binary search (or at
once, at the offset it had in the previous file).

Per station block we keep the rows we need, by forecast hour:
  TXN  max (00Z columns) / min (12Z columns) temperature, F. Day D's max is at 00Z on D+1.
  XND  NBM's own standard deviation of TXN.
  TMP/TSD  3-hourly temperature and its standard deviation.

Cycles: 23Z the day before (for the 8pm `eve` decision) and 11Z on the day (8am `am`). Files are
published ~40-55 min after the cycle. Each file's Last-Modified is kept, and a file published
after the earliest decision time it serves is dropped, so there's no look-ahead.

Run: uv run python -m app.backtest.nbm --start 2025-03-01 --end 2026-11-21
"""

from __future__ import annotations

import argparse
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.backtest.data import CACHE, decision_times
from app.config import get_settings
from app.evidence.stations import Station, climate_day_utc, load_stations

BUCKET = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"
NBM_CACHE = CACHE / "nbm"
CYCLES = {"eve": 23, "am": 11}  # eve uses the 23Z run of the day before
ROWS = ("TXN", "XND", "TMP", "TSD")
PROBE = 4096  # every block is < 3.5 KB, so a probe this size always holds a block header
HEADER = re.compile(rb"\n ?([A-Z0-9]{3,8}) +NBM V[\d.]+ NBS GUIDANCE +(\d+)/(\d+)/(\d{4}) +(\d{2})00 UTC")


def key_for(cycle_day: date, hour: int) -> str:
    return f"blend.{cycle_day:%Y%m%d}/{hour:02d}/text/blend_nbstx.t{hour:02d}z"


class RangeReader:
    """Byte-range reads of one object, remembering its size and Last-Modified."""

    def __init__(self, client: httpx.Client, key: str):
        self.client, self.url = client, f"{BUCKET}/{key}"
        self.size: int | None = None
        self.last_modified: datetime | None = None
        self.requests = 0

    def read(self, start: int, length: int) -> tuple[bytes, int]:
        """Return (bytes, absolute offset of bytes[0]). A read from 0 gets a leading newline
        (offset -1) so the file's first header looks like every other one."""
        start = max(0, start)
        for attempt in range(4):
            try:
                r = self.client.get(self.url, headers={"Range": f"bytes={start}-{start + length - 1}"})
                self.requests += 1
                if r.status_code == 404:
                    raise FileNotFoundError(self.url)
                r.raise_for_status()
                break
            except httpx.TransportError:
                if attempt == 3:
                    raise
        self.size = int(r.headers["content-range"].rsplit("/", 1)[1])
        self.last_modified = parsedate_to_datetime(r.headers["last-modified"])
        return (b"\n" + r.content, -1) if start == 0 else (r.content, start)


def find_block(rd: RangeReader, sid: str, guess: int | None) -> tuple[bytes, int] | None:
    """Return (block bytes, byte offset of the block's newline) for `sid`, or None if absent.

    Offsets point at the newline before a block header, which is what HEADER matches.
    """
    if guess is not None:
        buf, base = rd.read(guess - 64, PROBE)
        for m in HEADER.finditer(buf):
            if m.group(1).decode() == sid:
                return _cut(buf, m.start()), base + m.start()
    if rd.size is None:
        rd.read(0, 1)
    lo, hi = 0, rd.size or 0
    while hi - lo > 2 * PROBE:  # invariant: the block's newline, if present, is in [lo, hi)
        mid = (lo + hi) // 2
        buf, base = rd.read(mid, PROBE)
        m = HEADER.search(buf)
        if m is None or m.group(1).decode() > sid:
            hi = base + (m.start() if m else len(buf))
            hi = max(hi, mid + 1)
        elif m.group(1).decode() == sid:
            buf, base = rd.read(base + m.start(), PROBE)
            return _cut(buf, 0), base
        else:
            lo = base + m.start() + 1
    buf, base = rd.read(lo, hi - lo + PROBE)
    for m in HEADER.finditer(buf):
        if m.group(1).decode() == sid:
            return _cut(buf, m.start()), base + m.start()
    return None


def _cut(buf: bytes, start: int) -> bytes:
    """The block starting at the newline at `start`, up to the next header (or buffer end)."""
    nxt = HEADER.search(buf, start + 10)
    return buf[start + 1: nxt.start() if nxt else len(buf)]


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
    ends = [mm.end() for mm in re.finditer(r"\d+", fhr_line[4:])]
    ends = [e + 4 for e in ends]
    out: dict = {"cycle": cycle.isoformat(), "fhr": [int(fhr_line[e - 3:e]) for e in ends]}
    for name in ROWS:
        ln = rows.get(name, "")
        vals = []
        for e in ends:
            cell = ln[e - 3:e].strip() if len(ln) >= e - 3 else ""
            try:
                vals.append(int(cell))
            except ValueError:
                vals.append(None)
        out[name] = vals
    return out


def download_file(client: httpx.Client, cycle_day: date, hour: int, icaos: list[str],
                  offsets: dict[str, int], lock: threading.Lock) -> dict | None:
    path = NBM_CACHE / f"{cycle_day:%Y%m%d}{hour:02d}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    rd = RangeReader(client, key_for(cycle_day, hour))
    stations: dict[str, dict] = {}
    try:
        for sid in icaos:
            with lock:
                guess = offsets.get(sid)
            found = find_block(rd, sid, guess)
            if found is None:
                continue
            block, off = found
            with lock:
                offsets[sid] = off
            parsed = parse_block(block)
            if parsed:
                stations[sid] = parsed
    except FileNotFoundError:
        data = {"missing": True}
        path.write_text(json.dumps(data), encoding="utf-8")
        return data
    data = {"last_modified": rd.last_modified.isoformat() if rd.last_modified else None,
            "requests": rd.requests, "stations": stations}
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def features(stations: dict[str, Station], decision: str, days: list[date]) -> dict[str, dict[str, dict]]:
    """{cli_code: {day_iso: {"txn", "xnd", "tmax", "tsd"}}} from the cycle that serves `decision`.

    txn/xnd: NBM's daytime max for the day (00Z column of the next day) and its SD.
    tmax/tsd: highest 3-hourly TMP inside the climate day (midnight-midnight local standard
    time, which can differ from NBM's daytime max on front days) and the TSD at that hour.
    A bulletin published after the decision time is skipped (no look-ahead).
    """
    out: dict[str, dict[str, dict]] = {c: {} for c in stations}
    files: dict[str, dict | None] = {}
    for d in days:
        cycle_day = d - timedelta(days=1) if decision == "eve" else d
        name = f"{cycle_day:%Y%m%d}{CYCLES[decision]:02d}"
        if name not in files:
            f = NBM_CACHE / f"{name}.json"
            files[name] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
        data = files[name]
        if not data or data.get("missing") or not data.get("last_modified"):
            continue
        published = datetime.fromisoformat(data["last_modified"])
        for c, st in stations.items():
            blk = data["stations"].get(st.icao)
            if not blk or published > decision_times(d, st)[decision]:
                continue
            cycle = datetime.fromisoformat(blk["cycle"])
            valid = [cycle + timedelta(hours=h) for h in blk["fhr"]]
            max_at = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(days=1)
            i = next((k for k, v in enumerate(valid) if v == max_at), None)
            if i is None or blk["TXN"][i] is None or blk["XND"][i] is None:
                continue
            a, b = climate_day_utc(d, st.timezone)
            tmps = [(blk["TMP"][k], blk["TSD"][k]) for k, v in enumerate(valid)
                    if a <= v <= b and blk["TMP"][k] is not None]
            tmax, tsd = max(tmps) if tmps else (blk["TXN"][i], blk["XND"][i])
            out[c][d.isoformat()] = {"txn": blk["TXN"][i], "xnd": blk["XND"][i],
                                     "tmax": tmax, "tsd": tsd if tsd is not None else blk["XND"][i]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-03-01")
    ap.add_argument("--end", default=(date.today() - timedelta(days=2)).isoformat())
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    NBM_CACHE.mkdir(parents=True, exist_ok=True)
    icaos = sorted({s.icao for s in load_stations(get_settings().stations_file).values()})
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    jobs = []
    d = start
    while d <= end:
        jobs += [(d - timedelta(days=1), CYCLES["eve"]), (d, CYCLES["am"])]
        d += timedelta(days=1)
    jobs = sorted(set(jobs))
    print(f"{len(jobs)} bulletins x {len(icaos)} stations, {args.workers} workers")
    offsets: dict[str, int] = {}
    lock = threading.Lock()
    done = reqs = missing = 0
    with httpx.Client(timeout=30, limits=httpx.Limits(max_connections=args.workers * 2)) as client:
        # Prime offsets from the first file so the rest mostly hit on the first probe.
        download_file(client, *jobs[0], icaos, offsets, lock)
        with ThreadPoolExecutor(args.workers) as pool:
            futs = {pool.submit(download_file, client, cd, h, icaos, offsets, lock): (cd, h) for cd, h in jobs[1:]}
            for f in as_completed(futs):
                data = f.result()
                done += 1
                reqs += (data or {}).get("requests", 0)
                missing += 1 if (data or {}).get("missing") else 0
                if done % 100 == 0:
                    print(f"  {done}/{len(jobs) - 1} files, {reqs} requests, {missing} missing", flush=True)
    print(f"done: {done + 1} files, {missing} missing")


if __name__ == "__main__":
    main()
