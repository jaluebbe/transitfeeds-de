"""Train numbers of one service day from a (filtered) GTFS feed, for lookup by line, stop and time.

Usage:
  python numbers/train_numbers.py GTFS_DIR_OR_ZIP --region regions/hamburg.json --date 2026-11-23 [--out data/numbers]

For the agencies in the region's "train_number_agencies" (rail route types only),
trip_short_name is the train number (zero-padded, e.g. 011546 = 11546). Writes
train_numbers_YYYYMMDD.json:

  {"date": "2026-11-23",
   "stops": {"RE7|de:02000:10950|2026-11-23T10:05": [["11546", "de:02000:10951"]], ...},
   "trips": {"<trip_id>": "11546", ...}}

Stop keys use the station part of the stop ID (de:<AGS>:<number>, stop groups
"_G" and, with --stations, EVA-named stations merged) and the planned
local departure, so overnight trips get the next day's date; the last stop has
none. Each entry is [train number, next station]: trains of the same line leaving
a station in the same minute (opposite directions, coupled trains) share a key,
and the next station tells them apart.
"""

import argparse
import csv
import json
import sys
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from io import TextIOWrapper
from pathlib import Path

RAIL_TYPES = {"2", "100", "101", "102", "103", "106", "109"}
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class Feed:
    def __init__(self, src: Path):
        self.src = src

    @contextmanager
    def open(self, name):
        if self.src.is_dir():
            with open(self.src / name, newline="", encoding="utf-8-sig") as f:
                yield f
        else:
            with zipfile.ZipFile(self.src) as z, z.open(name) as raw:
                yield TextIOWrapper(raw, newline="", encoding="utf-8-sig")

    def rows(self, name):
        with self.open(name) as f:
            yield from csv.DictReader(f)


def active_services(feed: Feed, day: date) -> set:
    d, weekday = day.strftime("%Y%m%d"), WEEKDAYS[day.weekday()]
    active = set()
    try:
        for c in feed.rows("calendar.txt"):
            if c["start_date"] <= d <= c["end_date"] and c[weekday] == "1":
                active.add(c["service_id"])
    except KeyError:
        pass  # feed without calendar.txt
    for c in feed.rows("calendar_dates.txt"):
        if c["date"] == d:
            (active.add if c["exception_type"] == "1" else active.discard)(c["service_id"])
    return active


def station_of(stop_id: str, aliases: dict | None = None) -> str:
    """de:<AGS>:<number> of a stop; "_G" (stop group) dropped, aliases applied."""
    station = ":".join(stop_id.split(":")[:3]).removesuffix("_G")
    return (aliases or {}).get(station, station)


def eva_aliases(path: Path) -> dict:
    """Stations named by an EVA number (de:02000:8000147) -> the station's DHID
    in OpenStation (de:02000:49950), from filter_stations.py output."""
    aliases = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ags = ":".join(r["dhid"].split(":")[:2])
            alias = f"{ags}:{r['eva']}"
            if alias != r["dhid"]:
                aliases[alias] = r["dhid"]
    return aliases


def clock(day: date, gtfs_time: str) -> str:
    h, m, _ = (int(x) for x in gtfs_time.split(":"))
    at = datetime(day.year, day.month, day.day) + timedelta(hours=h, minutes=m)
    return at.strftime("%Y-%m-%dT%H:%M")


def train_numbers(feed: Feed, day: date, agencies: set, aliases: dict | None = None) -> dict:
    routes = {
        r["route_id"]: r["route_short_name"]
        for r in feed.rows("routes.txt")
        if r["agency_id"] in agencies and r["route_type"] in RAIL_TYPES
    }
    services = active_services(feed, day)
    trips = {}
    for t in feed.rows("trips.txt"):
        number = (t.get("trip_short_name") or "").lstrip("0")
        if t["route_id"] in routes and t["service_id"] in services and number.isdigit():
            trips[t["trip_id"]] = (routes[t["route_id"]], number)

    calls = {}
    for s in feed.rows("stop_times.txt"):
        if s["trip_id"] in trips and s["stop_id"].startswith("de:"):
            t = s["departure_time"] or s["arrival_time"]
            station = station_of(s["stop_id"], aliases)
            calls.setdefault(s["trip_id"], []).append((int(s["stop_sequence"]), station, t))
    stops = {}
    for trip_id, rows in calls.items():
        line, number = trips[trip_id]
        rows.sort()
        for (_, station, t), (_, following, _) in zip(rows, rows[1:]):
            if t:
                stops.setdefault(f"{line}|{station}|{clock(day, t)}", []).append([number, following])
    return {
        "date": day.isoformat(),
        "stops": {k: sorted(v, key=lambda x: int(x[0])) for k, v in sorted(stops.items())},
        "trips": {k: v[1] for k, v in sorted(trips.items())},
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("src", type=Path)
    ap.add_argument("--region", type=Path, required=True)
    ap.add_argument("--date", type=date.fromisoformat, default=date.today())
    ap.add_argument("--out", type=Path, default=Path("data/numbers"))
    ap.add_argument("--stations", type=Path, help="filter_stations.py output, to merge stations named by EVA number")
    a = ap.parse_args(argv)
    region = json.loads(a.region.read_text(encoding="utf-8"))
    agencies = set(region.get("train_number_agencies", []))
    if not agencies:
        sys.exit("region has no train_number_agencies")
    aliases = eva_aliases(a.stations) if a.stations else None
    result = train_numbers(Feed(a.src), a.date, agencies, aliases)
    a.out.mkdir(parents=True, exist_ok=True)
    target = a.out / f"train_numbers_{a.date:%Y%m%d}.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    tmp.replace(target)
    print(f"{len(result['trips'])} trips, {len(result['stops'])} stop keys -> {target}")


if __name__ == "__main__":
    main()
