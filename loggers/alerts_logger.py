"""Log GTFS-RT service alerts: one line per new, changed or removed alert.

Writes DATA_DIR/alerts_events.jsonl with event "new", "changed" or "gone"; the last
known alerts are kept in DATA_DIR/alerts_state.json, so a restart does not repeat them.

Environment:
  ALERTS_URL       feed URL (required, e.g. the Mobilithek subscription URL)
  DELFI_CERT/KEY   client certificate and key (default /certs/client.crt, /certs/client.key)
  DATA_DIR         output directory (default /data)
  INTERVAL         seconds between polls (default 60)
  ALERT_PREFIXES   optional comma-separated prefixes of route, agency or stop ids;
                   only alerts touching one of them are kept (default: all)

Use --file FEED.pb --once to parse a saved feed instead of downloading.
"""
import argparse
import hashlib
import json
import logging
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from google.transit import gtfs_realtime_pb2

URL = os.environ.get("ALERTS_URL", "")
CERT = (
    os.environ.get("DELFI_CERT", "/certs/client.crt"),
    os.environ.get("DELFI_KEY", "/certs/client.key"),
)
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
INTERVAL = int(os.environ.get("INTERVAL", "60"))
PREFIXES = tuple(p.strip() for p in os.environ.get("ALERT_PREFIXES", "").split(",") if p.strip())
GONE_AFTER = 2  # polls an alert must be missing before it counts as gone

log = logging.getLogger("alerts_logger")
stop_requested = False


def text(translated):
    """German text if present, else the first translation."""
    items = list(translated.translation)
    return next((t.text for t in items if t.language == "de"), items[0].text if items else "")


def entity_fields(e):
    keys = ("agency_id", "route_id", "route_type", "stop_id")
    out = {k: getattr(e, k) for k in keys if getattr(e, k)}
    if e.HasField("trip") and e.trip.trip_id:
        out["trip_id"] = e.trip.trip_id
    return out


def alert_record(entity):
    a = entity.alert
    return {
        "id": entity.id,
        "cause": a.cause,
        "effect": a.effect,
        "periods": [[p.start or None, p.end or None] for p in a.active_period],
        "entities": [entity_fields(e) for e in a.informed_entity],
        "header": text(a.header_text),
        "desc": text(a.description_text),
        "url": text(a.url),
    }


def is_wanted(rec):
    if not PREFIXES:
        return True
    return any(v.startswith(PREFIXES) for e in rec["entities"] for k, v in e.items() if k != "route_type")


def digest(rec):
    return hashlib.sha1(json.dumps(rec, sort_keys=True).encode()).hexdigest()[:16]


def fetch(path):
    feed = gtfs_realtime_pb2.FeedMessage()
    if path:
        feed.ParseFromString(Path(path).read_bytes())
    else:
        r = requests.get(URL, cert=CERT, timeout=60)
        if r.status_code in (204, 304):
            return None
        r.raise_for_status()
        feed.ParseFromString(r.content)
    return feed


def load_state():
    f = DATA_DIR / "alerts_state.json"
    return json.loads(f.read_text()) if f.exists() else {}


def save_state(known):
    tmp = DATA_DIR / "alerts_state.json.tmp"
    tmp.write_text(json.dumps(known, separators=(",", ":")))
    tmp.replace(DATA_DIR / "alerts_state.json")


def run_once(path, state):
    feed = fetch(path)
    if feed is None or not feed.entity:
        return
    ts = feed.header.timestamp or int(time.time())
    if ts == state["last_ts"]:
        return
    state["last_ts"] = ts
    known = state["known"]  # id -> {"h": digest, "missing": polls, "rec": record}
    current = {}
    for entity in feed.entity:
        if entity.HasField("alert"):
            rec = alert_record(entity)
            if is_wanted(rec):
                current[rec["id"]] = rec
    events = []
    for alert_id, rec in current.items():
        h = digest(rec)
        old = known.get(alert_id)
        if old is None:
            events.append({"ts": ts, "event": "new", **rec})
        elif old["h"] != h:
            events.append({"ts": ts, "event": "changed", **rec})
        known[alert_id] = {"h": h, "missing": 0, "rec": rec}
    for alert_id in list(known):
        if alert_id in current:
            continue
        known[alert_id]["missing"] += 1
        if known[alert_id]["missing"] >= GONE_AFTER:
            rec = known.pop(alert_id)["rec"]
            events.append({"ts": ts, "event": "gone", "id": alert_id, "header": rec["header"]})
    if events:
        with open(DATA_DIR / "alerts_events.jsonl", "a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n")
    save_state(known)
    log.info("feed %s: %d alerts, %d events", datetime.fromtimestamp(ts, timezone.utc).isoformat(),
             len(current), len(events))


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
        raise SystemExit("ALERTS_URL must be set")
    state = {"last_ts": None, "known": load_state()}
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
        wait = min(INTERVAL * (2 ** min(failures, 3)), 300) if failures else INTERVAL
        deadline = started + wait
        while not stop_requested and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))


if __name__ == "__main__":
    main()
