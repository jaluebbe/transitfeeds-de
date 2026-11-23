"""Reduce a GTFS feed (e.g. DELFI, all of Germany) to a region, streaming.

Usage:
  python gtfs/filter_gtfs.py GTFS_DIR_OR_ZIP OUT_DIR --region regions/hamburg.json
  python gtfs/filter_gtfs.py GTFS_DIR_OR_ZIP OUT_DIR --agencies 15141,10375 [--lines RE7,RB81 --line-stop-prefix de:02000:]

Keeps all routes of the given agencies and, by short name, the given lines if one of
their trips calls at a stop starting with the line stop prefix (line names like RE1
exist in several regions). Replacement buses running under a rail agency
(route_type 3) are kept with it. Writes the filtered GTFS tables plus route_ids.txt
and stop_ids.txt (one ID per line) for the loggers.

Region file (JSON): {"agencies": [...], "lines": [...], "line_stop_prefix": "de:02000:"}
"""

import argparse
import csv
import json
import sys
import zipfile
from contextlib import contextmanager
from io import TextIOWrapper
from pathlib import Path


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("src", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--region", type=Path, help="JSON file with agencies, lines, line_stop_prefix")
    ap.add_argument("--agencies", help="comma-separated agency_ids")
    ap.add_argument("--lines", help="comma-separated route_short_names")
    ap.add_argument("--line-stop-prefix", help="stop_id prefix a kept line must call at")
    a = ap.parse_args(argv)
    region = json.loads(a.region.read_text(encoding="utf-8")) if a.region else {}
    a.agencies = set(a.agencies.split(",")) if a.agencies else set(region.get("agencies", []))
    a.lines = set(a.lines.split(",")) if a.lines else set(region.get("lines", []))
    a.line_stop_prefix = a.line_stop_prefix or region.get("line_stop_prefix", "")
    if not a.agencies and not a.lines:
        ap.error("no agencies or lines given")
    return a


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

    def has(self, name):
        if self.src.is_dir():
            return (self.src / name).exists()
        with zipfile.ZipFile(self.src) as z:
            return name in z.namelist()


def filter_file(feed, out_dir, name, keep, collect=None):
    """Copy rows of `name` that satisfy keep(row); collect(row) is called for kept rows."""
    if not feed.has(name):
        print(f"{name}: not found, skipped", file=sys.stderr)
        return
    kept = total = 0
    with feed.open(name) as f, open(out_dir / name, "w", newline="", encoding="utf-8") as g:
        reader = csv.DictReader(f)
        writer = csv.DictWriter(g, fieldnames=reader.fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in reader:
            total += 1
            if keep(row):
                writer.writerow(row)
                kept += 1
                if collect:
                    collect(row)
            if total % 5_000_000 == 0:
                print(f"  {name}: {total:,} rows read, {kept:,} kept", file=sys.stderr)
    print(f"{name}: {kept:,} of {total:,} rows", file=sys.stderr)


def line_routes(feed, lines, stop_prefix):
    """Routes named in `lines` with a trip calling at a stop starting with stop_prefix."""
    candidates = set()
    with feed.open("routes.txt") as f:
        for r in csv.DictReader(f):
            if r["route_short_name"] in lines:
                candidates.add(r["route_id"])
    if not candidates:
        return set()
    trip_route = {}
    with feed.open("trips.txt") as f:
        for r in csv.DictReader(f):
            if r["route_id"] in candidates:
                trip_route[r["trip_id"]] = r["route_id"]
    found = set()
    with feed.open("stop_times.txt") as f:
        reader = csv.reader(f)
        header = next(reader)
        i_trip, i_stop = header.index("trip_id"), header.index("stop_id")
        for row in reader:
            route = trip_route.get(row[i_trip])
            if route and route not in found and row[i_stop].startswith(stop_prefix):
                found.add(route)
    print(f"line routes in the region: {len(found)} of {len(candidates)}", file=sys.stderr)
    return found


def main(argv=None):
    a = parse_args(argv)
    feed = Feed(a.src)
    out = a.out_dir
    out.mkdir(parents=True, exist_ok=True)
    extra = line_routes(feed, a.lines, a.line_stop_prefix) if a.lines else set()

    routes, agencies, trips, services, shapes, stop_ids = set(), set(), set(), set(), set(), set()
    filter_file(
        feed, out, "routes.txt",
        lambda r: r["agency_id"] in a.agencies or r["route_id"] in extra,
        lambda r: (routes.add(r["route_id"]), agencies.add(r["agency_id"])),
    )  # fmt: skip
    filter_file(
        feed, out, "trips.txt",
        lambda r: r["route_id"] in routes,
        lambda r: (trips.add(r["trip_id"]), services.add(r["service_id"]), shapes.add(r.get("shape_id", ""))),
    )  # fmt: skip
    filter_file(feed, out, "stop_times.txt", lambda r: r["trip_id"] in trips, lambda r: stop_ids.add(r["stop_id"]))

    parents = set()
    if feed.has("stops.txt"):
        with feed.open("stops.txt") as f:
            for r in csv.DictReader(f):
                if r["stop_id"] in stop_ids and r.get("parent_station"):
                    parents.add(r["parent_station"])
    filter_file(feed, out, "stops.txt", lambda r: r["stop_id"] in stop_ids or r["stop_id"] in parents)

    (out / "route_ids.txt").write_text("\n".join(sorted(routes)) + "\n", encoding="utf-8")
    (out / "stop_ids.txt").write_text("\n".join(sorted(stop_ids)) + "\n", encoding="utf-8")
    filter_file(feed, out, "agency.txt", lambda r: r["agency_id"] in agencies)
    filter_file(feed, out, "calendar.txt", lambda r: r["service_id"] in services)
    filter_file(feed, out, "calendar_dates.txt", lambda r: r["service_id"] in services)
    filter_file(feed, out, "shapes.txt", lambda r: r["shape_id"] in shapes)
    filter_file(feed, out, "frequencies.txt", lambda r: r["trip_id"] in trips)
    print(f"done: {len(routes)} routes, {len(trips):,} trips, {len(stop_ids):,} stops -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
