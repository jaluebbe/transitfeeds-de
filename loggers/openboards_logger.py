"""Log DB OpenBoards departures of a few stations as raw JSON.

Writes one JSON line per request to DATA_DIR/openboards_YYYYMMDD.jsonl.gz (UTC day):
{"ts": request time, "eva": station, "endpoint": "departures", "status": HTTP status, "body": response}.

Environment:
  DB_CLIENT_ID, DB_API_KEY   DB API Marketplace credentials
  DATA_DIR         output directory (default /data)
  INTERVAL         seconds between rounds over all stations (default 120)
  EVA_NUMBERS      comma-separated EVA numbers of the stations (required)
  ENDPOINTS        comma-separated, departures and/or arrivals (default departures)
  MAX_ENTRIES      maxEntriesPerTransportType (default 50)

Use --once for a single round.
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

BASE = os.environ.get(
    "OPENBOARDS_URL",
    "https://apis.deutschebahn.com/db-api-marketplace/apis/open-boards/v1",
)
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
INTERVAL = int(os.environ.get("INTERVAL", "120"))
EVA_NUMBERS = [e.strip() for e in os.environ.get("EVA_NUMBERS", "").split(",") if e.strip()]
ENDPOINTS = [e.strip() for e in os.environ.get("ENDPOINTS", "departures").split(",") if e.strip()]
MAX_ENTRIES = int(os.environ.get("MAX_ENTRIES", "50"))
HEADERS = {
    "DB-Client-Id": os.environ.get("DB_CLIENT_ID", ""),
    "DB-Api-Key": os.environ.get("DB_API_KEY", ""),
    "Accept": "application/json",
    "Content-Type": "application/json",
}

log = logging.getLogger("openboards_logger")
stop_requested = False


def query(session, endpoint, eva):
    body = {
        "stopPlaceOrStation": {"evaNumbers": [eva]},
        "timeWindow": {"timeStart": datetime.now().astimezone().isoformat(timespec="seconds")},
        "maxEntriesPerTransportType": MAX_ENTRIES,
        "languages": ["deu"],
    }
    r = session.post(f"{BASE}/{endpoint}", headers=HEADERS, json=body, timeout=30)
    try:
        payload = r.json()
    except ValueError:
        payload = r.text[:2000]
    return r.status_code, payload


def write(rec):
    day = datetime.fromtimestamp(rec["ts"], timezone.utc).strftime("%Y%m%d")
    with gzip.open(DATA_DIR / f"openboards_{day}.jsonl.gz", "at", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")


def run_round(session):
    failures = 0
    for endpoint in ENDPOINTS:
        for eva in EVA_NUMBERS:
            ts = int(time.time())
            try:
                status, payload = query(session, endpoint, eva)
            except requests.RequestException as exc:
                log.warning("%s %s failed: %s", endpoint, eva, exc)
                failures += 1
                continue
            write({"ts": ts, "eva": eva, "endpoint": endpoint, "status": status, "body": payload})
            n = len(payload.get(endpoint, [])) if isinstance(payload, dict) else 0
            if status != 200:
                failures += 1
                log.warning("%s %s: HTTP %s %s", endpoint, eva, status, str(payload)[:200])
            else:
                log.info("%s %s: %d entries", endpoint, eva, n)
            time.sleep(0.2)  # stay well below 10 calls/s
    return failures


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not HEADERS["DB-Client-Id"] or not HEADERS["DB-Api-Key"]:
        raise SystemExit("DB_CLIENT_ID and DB_API_KEY must be set")
    if not EVA_NUMBERS:
        raise SystemExit("EVA_NUMBERS must be set")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, lambda *_: globals().update(stop_requested=True))
    signal.signal(signal.SIGINT, lambda *_: globals().update(stop_requested=True))

    session = requests.Session()
    rounds_failed = 0
    while not stop_requested:
        started = time.monotonic()
        failed = run_round(session)
        rounds_failed = rounds_failed + 1 if failed == len(ENDPOINTS) * len(EVA_NUMBERS) else 0
        if args.once:
            break
        wait = min(INTERVAL * (2 ** min(rounds_failed, 3)), 900) if rounds_failed else INTERVAL
        deadline = started + wait
        while not stop_requested and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))


if __name__ == "__main__":
    main()
