"""Log trip updates of selected routes from a GTFS-RT feed (e.g. DELFI via Mobilithek).

Writes one JSON line per feed snapshot to DATA_DIR/trips_YYYYMMDD.jsonl.gz (UTC day)
and one line per added/cancelled trip or trip with skipped stops to DATA_DIR/events.jsonl.

Environment:
  DELFI_URL        feed URL (required, e.g. the Mobilithek subscription URL)
  DELFI_CERT/KEY   client certificate and key (default /certs/client.crt, /certs/client.key)
  DATA_DIR         output directory (default /data)
  INTERVAL         seconds between polls (default 30)
  ROUTE_PREFIXES   comma-separated route_id prefixes to keep, e.g. de:hvv:U,de:hvv:S (default none)
  ROUTE_IDS        optional file with one route_id per line (default DATA_DIR/route_ids.txt),
                   e.g. from gtfs/filter_gtfs.py; these routes are kept as well

Use --file FEED.pb --once to parse a saved feed instead of downloading.
"""
import argparse
import gzip
import json
import logging
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from google.transit import gtfs_realtime_pb2

URL = os.environ.get("DELFI_URL", "")
CERT = (
    os.environ.get("DELFI_CERT", "/certs/client.crt"),
    os.environ.get("DELFI_KEY", "/certs/client.key"),
)
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
INTERVAL = int(os.environ.get("INTERVAL", "30"))
ROUTE_PREFIXES = tuple(p.strip() for p in os.environ.get("ROUTE_PREFIXES", "").split(",") if p.strip())
ROUTE_IDS_FILE = Path(os.environ.get("ROUTE_IDS", str(DATA_DIR / "route_ids.txt")))

log = logging.getLogger("delfi_logger")
stop_requested = False


def fetch(path=None):
    feed = gtfs_realtime_pb2.FeedMessage()
    if path:
        feed.ParseFromString(Path(path).read_bytes())
    else:
        r = requests.get(URL, cert=CERT, timeout=60)
        r.raise_for_status()
        feed.ParseFromString(r.content)
    return feed


def stop_row(stu):
    """[stop_sequence, stop_id, arrival_delay, departure_time, departure_delay, stop_rel]"""
    arr = stu.arrival.delay if stu.HasField("arrival") and stu.arrival.HasField("delay") else None
    dep_time = dep_delay = None
    if stu.HasField("departure"):
        if stu.departure.HasField("time"):
            dep_time = stu.departure.time
        if stu.departure.HasField("delay"):
            dep_delay = stu.departure.delay
    return [stu.stop_sequence, stu.stop_id, arr, dep_time, dep_delay, stu.schedule_relationship]


def trip_record(tu):
    t = tu.trip
    rec = {
        "id": t.trip_id,
        "route": t.route_id,
        "date": t.start_date,
        "start": t.start_time,
        "dir": t.direction_id,
        "rel": t.schedule_relationship,
        "stops": [stop_row(s) for s in tu.stop_time_update],
    }
    if tu.HasField("vehicle"):
        rec["veh"] = [tu.vehicle.id, tu.vehicle.label]
    return rec


def load_route_ids():
    if not ROUTE_IDS_FILE.exists():
        log.warning("%s not found, filtering by route prefixes only", ROUTE_IDS_FILE)
        return set()
    ids = {line.strip() for line in ROUTE_IDS_FILE.read_text().splitlines() if line.strip()}
    log.info("loaded %d route ids", len(ids))
    return ids


def is_wanted(tu, route_ids):
    route = tu.trip.route_id
    return route.startswith(ROUTE_PREFIXES) or route in route_ids


def extract(feed, route_ids):
    return [
        trip_record(e.trip_update)
        for e in feed.entity
        if e.HasField("trip_update") and is_wanted(e.trip_update, route_ids)
    ]


def write_snapshot(feed_ts, trips):
    day = datetime.fromtimestamp(feed_ts, timezone.utc).strftime("%Y%m%d")
    line = json.dumps({"ts": feed_ts, "fetched": int(time.time()), "trips": trips},
                      separators=(",", ":"))
    # Each append is a separate gzip member; gzip readers concatenate them.
    with gzip.open(DATA_DIR / f"trips_{day}.jsonl.gz", "at", encoding="utf-8") as f:
        f.write(line + "\n")


def write_events(feed_ts, trips, seen):
    with open(DATA_DIR / "events.jsonl", "a", encoding="utf-8") as f:
        for t in trips:
            stops = t["stops"]
            skipped = [s for s in stops if s[5] == 1]
            if t["rel"] == 0 and not skipped:
                continue
            # Log again only when the trip's state changes
            key = (t["rel"], len(skipped), skipped[0][0] if skipped else None)
            if seen.get(t["id"]) == key:
                continue
            seen[t["id"]] = key
            f.write(json.dumps({
                "ts": feed_ts, "id": t["id"], "route": t["route"], "rel": t["rel"],
                "date": t["date"], "start": t["start"], "dir": t["dir"],
                "n_stops": len(stops),
                "first_stop": stops[0][1] if stops else None,
                "last_stop": stops[-1][1] if stops else None,
                "skipped": [[s[0], s[1]] for s in skipped],
            }, separators=(",", ":")) + "\n")


def run_once(path, state):
    feed = fetch(path)
    ts = feed.header.timestamp
    if ts == state["last_ts"]:
        return
    state["last_ts"] = ts
    trips = extract(feed, state["route_ids"])
    write_snapshot(ts, trips)
    write_events(ts, trips, state["seen"])
    log.info("feed %s: %d trips", datetime.fromtimestamp(ts, timezone.utc).isoformat(), len(trips))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--file", help="parse a local .pb file instead of downloading")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, lambda *_: globals().update(stop_requested=True))
    signal.signal(signal.SIGINT, lambda *_: globals().update(stop_requested=True))

    if not args.file and not URL:
        raise SystemExit("DELFI_URL must be set")
    state = {"last_ts": None, "seen": {}, "route_ids": load_route_ids()}
    if not ROUTE_PREFIXES and not state["route_ids"]:
        log.warning("no ROUTE_PREFIXES and no route ids: nothing will be kept")
    failures = 0
    while not stop_requested:
        started = time.monotonic()
        try:
            run_once(args.file, state)
            failures = 0
        except (requests.RequestException, OSError, ValueError) as exc:
            failures += 1
            log.warning("poll failed (%d): %s", failures, exc)
        if args.once or args.file:
            break
        # Back off up to 5 minutes on repeated failures
        wait = min(INTERVAL * (2 ** min(failures, 3)), 300) if failures else INTERVAL
        deadline = started + wait
        while not stop_requested and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))


if __name__ == "__main__":
    main()
