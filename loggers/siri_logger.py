"""Log SIRI ET (estimated timetable) journeys of one feed, filtered by operator, line or category.

Writes one JSON line per feed update to DATA_DIR/siri[_NAME]_YYYYMMDD.jsonl.gz (UTC day)
and one line per cancelled/extra journey or cancelled call to DATA_DIR/siri[_NAME]_events.jsonl.
A journey is kept if it matches any of the filters below.

Environment:
  SIRI_URL         feed URL (required, e.g. the Mobilithek subscription URL)
  DELFI_CERT/KEY   client certificate and key (default /certs/client.crt, /certs/client.key)
  DATA_DIR         output directory (default /data)
  INTERVAL         seconds between polls (default 30)
  SIRI_NAME        file name infix, e.g. vbn (default: none)
  SIRI_OPERATORS   comma-separated OperatorRef values to keep, e.g. 0S (default none)
  SIRI_LINE_PREFIXES  comma-separated LineRef prefixes to keep, e.g. de:hvv:A (default none)
  SIRI_CATEGORIES  comma-separated ProductCategoryRef values to keep, e.g. U-Bahn,Fähre (default none)
  SIRI_LINES       comma-separated PublishedLineName values to keep, e.g. RE7,RB81 (default none)
  SIRI_NEAR_CATEGORIES  categories kept when calling at a stop of a journey kept
                   by SIRI_OPERATORS, e.g. RE,RB (default none)
  SIRI_NEAR_STOPS  further stops for SIRI_NEAR_CATEGORIES, e.g. main-line EVA numbers
                   where the S-Bahn has its own (default none)

Use --file FEED.xml --once to parse a saved feed instead of downloading.
"""
import argparse
import gzip
import io
import json
import logging
import os
import signal
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

URL = os.environ.get("SIRI_URL", "")
CERT = (
    os.environ.get("DELFI_CERT", "/certs/client.crt"),
    os.environ.get("DELFI_KEY", "/certs/client.key"),
)
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
INTERVAL = int(os.environ.get("INTERVAL", "30"))
def _env_list(name, default=""):
    return tuple(v.strip() for v in os.environ.get(name, default).split(",") if v.strip())


NAME = os.environ.get("SIRI_NAME", "").strip()
PREFIX = f"siri_{NAME}" if NAME else "siri"
OPERATORS = set(_env_list("SIRI_OPERATORS"))
LINE_PREFIXES = _env_list("SIRI_LINE_PREFIXES")
CATEGORIES = set(_env_list("SIRI_CATEGORIES"))
LINES = set(_env_list("SIRI_LINES"))
NEAR_CATEGORIES = set(_env_list("SIRI_NEAR_CATEGORIES"))
NEAR_STOPS = set(_env_list("SIRI_NEAR_STOPS"))

log = logging.getLogger("siri_logger")
stop_requested = False


def local(tag):
    return tag.rsplit("}", 1)[-1]


def to_epoch(text):
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()) if text else None


def parse_call(el, recorded):
    """[stop, recorded, aimed_arr, actual_arr, aimed_dep, actual_dep, platform, cancelled], times as epoch seconds"""
    d = {local(c.tag): (c.text or "") for c in el}
    return [
        d.get("StopPointRef"),
        int(recorded),
        to_epoch(d.get("AimedArrivalTime")),
        to_epoch(d.get("ActualArrivalTime") or d.get("ExpectedArrivalTime")),
        to_epoch(d.get("AimedDepartureTime")),
        to_epoch(d.get("ActualDepartureTime") or d.get("ExpectedDepartureTime")),
        d.get("DeparturePlatformName") or d.get("ArrivalPlatformName"),
        int(d.get("Cancellation") == "true"),
    ]


def parse_journey(el):
    d, calls, framed = {}, [], {}
    for c in el:
        name = local(c.tag)
        if name in ("RecordedCalls", "EstimatedCalls"):
            calls += [parse_call(x, name == "RecordedCalls") for x in c]
        elif name == "FramedVehicleJourneyRef":
            framed = {local(x.tag): x.text for x in c}
        else:
            d[name] = c.text or ""
    return {
        "id": framed.get("DatedVehicleJourneyRef"),
        "date": framed.get("DataFrameRef"),
        "line": d.get("PublishedLineName") or d.get("LineRef"),
        "line_ref": d.get("LineRef"),
        "cat": d.get("ProductCategoryRef"),
        "op": d.get("OperatorRef"),
        "origin": d.get("OriginRef"),
        "dest": d.get("DestinationRef"),
        "dir": d.get("DirectionName"),
        "cancel": int(d.get("Cancellation") == "true"),
        "extra": int(d.get("ExtraJourney") == "true"),
        "calls": calls,
    }


def is_wanted(head):
    return (
        head.get("OperatorRef") in OPERATORS
        or (head.get("LineRef") or "").startswith(LINE_PREFIXES or ("\0",))
        or head.get("ProductCategoryRef") in CATEGORIES
        or head.get("PublishedLineName") in LINES
    )


def parse(data):
    """(response timestamp, wanted journeys)"""
    ts, journeys, near = None, [], []
    for _, el in ET.iterparse(io.BytesIO(data), events=("end",)):
        name = local(el.tag)
        if name == "ResponseTimestamp" and ts is None:
            ts = to_epoch(el.text)
        elif name == "EstimatedVehicleJourney":
            head = {local(c.tag): c.text for c in el if local(c.tag) in ("OperatorRef", "LineRef", "ProductCategoryRef", "PublishedLineName")}
            if is_wanted(head):
                journeys.append(parse_journey(el))
            elif head.get("ProductCategoryRef") in NEAR_CATEGORIES:
                near.append(parse_journey(el))
            el.clear()
    if near:
        stops = NEAR_STOPS | {c[0] for j in journeys if j["op"] in OPERATORS for c in j["calls"]}
        journeys += [j for j in near if any(c[0] in stops for c in j["calls"])]
    return ts, journeys


def fetch(path, state=None):
    if path:
        return Path(path).read_bytes()
    headers = {"If-Modified-Since": state["modified"]} if state and state.get("modified") else {}
    r = requests.get(URL, cert=CERT, headers=headers, timeout=120)
    if r.status_code in (204, 304):
        return None
    r.raise_for_status()
    if state is not None:
        state["modified"] = r.headers.get("Last-Modified")
    data = r.content
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def write_snapshot(ts, journeys):
    day = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%d")
    line = json.dumps({"ts": ts, "fetched": int(time.time()), "journeys": journeys}, separators=(",", ":"))
    with gzip.open(DATA_DIR / f"{PREFIX}_{day}.jsonl.gz", "at", encoding="utf-8") as f:
        f.write(line + "\n")


def write_events(ts, journeys, seen):
    with open(DATA_DIR / f"{PREFIX}_events.jsonl", "a", encoding="utf-8") as f:
        for j in journeys:
            cancelled = [c[0] for c in j["calls"] if c[7]]
            if not (j["cancel"] or j["extra"] or cancelled):
                continue
            key = (j["cancel"], j["extra"], len(cancelled))
            k = (j["date"], j["id"])
            if seen.get(k) == key:
                continue
            seen[k] = key
            f.write(json.dumps({
                "ts": ts, "id": j["id"], "date": j["date"], "line": j["line"], "dir": j["dir"],
                "cancel": j["cancel"], "extra": j["extra"], "cancelled_stops": cancelled,
                "n_calls": len(j["calls"]),
            }, separators=(",", ":")) + "\n")


def run_once(path, state):
    data = fetch(path, state)
    if data is None:
        return
    ts, journeys = parse(data)
    if ts is None or ts == state["last_ts"]:
        return
    state["last_ts"] = ts
    write_snapshot(ts, journeys)
    write_events(ts, journeys, state["seen"])
    log.info("feed %s: %d journeys", datetime.fromtimestamp(ts, timezone.utc).isoformat(), len(journeys))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--file", help="parse a local .xml file instead of downloading")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, lambda *_: globals().update(stop_requested=True))
    signal.signal(signal.SIGINT, lambda *_: globals().update(stop_requested=True))

    if not args.file and not URL:
        raise SystemExit("SIRI_URL must be set")
    if not (OPERATORS or LINE_PREFIXES or CATEGORIES or LINES):
        log.warning("no SIRI_OPERATORS, SIRI_LINE_PREFIXES, SIRI_CATEGORIES or SIRI_LINES: nothing will be kept")
    state = {"last_ts": None, "seen": {}, "modified": None}
    failures = 0
    while not stop_requested:
        started = time.monotonic()
        try:
            run_once(args.file, state)
            failures = 0
        except (requests.RequestException, OSError, ValueError, ET.ParseError) as exc:
            failures += 1
            log.warning("poll failed (%d): %s", failures, exc)
        if args.once or args.file:
            break
        wait = min(INTERVAL * (2 ** min(failures, 3)), 300) if failures else INTERVAL
        deadline = started + wait
        while not stop_requested and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))


if __name__ == "__main__":
    main()
