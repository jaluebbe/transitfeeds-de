"""Download DB OpenStation NeTEx and write a station table (EVA, DHID, name, ...).

Usage:
  DB_CLIENT_ID=... DB_API_KEY=... python stations/openstation_netex.py OUT_DIR
  python stations/openstation_netex.py OUT_DIR --file netex.xml

Follows the paging links (about 57 pages), writes stations.csv and keeps the
first page as netex_000.xml (all with --keep).
"""
import argparse
import csv
import io
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

API = "https://apis.deutschebahn.com/db-api-marketplace/apis/open-station/v1"
URL = API + "/netex"
MAX_PAGES = 100


def local(tag):
    return tag.rsplit("}", 1)[-1]


def stations(data):
    """One dict per StopPlace from its own keyList and name; several EVA
    numbers (main line, S-Bahn) are joined with ";"."""
    for _, el in ET.iterparse(io.BytesIO(data), events=("end",)):
        if local(el.tag) != "StopPlace":
            continue
        rec = {"id": el.get("id"), "name": None}
        codes = {}
        for c in el:
            name = local(c.tag)
            if name == "Name":
                rec["name"] = (c.text or "").strip()
            elif name == "keyList":
                for kv in c:
                    d = {local(x.tag): (x.text or "").strip() for x in kv}
                    if d.get("Key"):
                        codes.setdefault(d["Key"], []).append(d.get("Value") or "")
            elif name == "ParentSiteRef":
                rec["parent"] = c.get("ref")
        for key, values in codes.items():
            rec[key] = ";".join(values)
        yield rec
        el.clear()


def next_link(headers):
    m = re.search(r'<([^>]+)>\s*;\s*rel="?next"?', headers.get("Link", ""))
    if not m:
        return None
    link = m.group(1)
    return link if link.startswith("http") else API + link


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("out_dir")
    ap.add_argument("--file")
    ap.add_argument("--param", action="append", default=[], help="query parameter key=value")
    ap.add_argument("--keep", action="store_true", help="save every page, not only the first")
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    pages = []
    if a.file:
        pages.append(list(stations(Path(a.file).read_bytes())))
    else:
        headers = {
            "DB-Client-Id": os.environ["DB_CLIENT_ID"],
            "DB-Api-Key": os.environ["DB_API_KEY"],
            "Accept": "application/xml",
        }
        params = dict(p.split("=", 1) for p in a.param)
        url = URL
        for i in range(MAX_PAGES):
            r = requests.get(url, headers=headers, params=params if i == 0 else None, timeout=120)
            print(f"page {i}: HTTP {r.status_code}, {len(r.content)} bytes,"
                  f" remaining {r.headers.get('X-RateLimit-Remaining')}")
            r.raise_for_status()
            if i == 0 or a.keep:
                (out / f"netex_{i:03d}.xml").write_bytes(r.content)
            pages.append(list(stations(r.content)))
            url = next_link(r.headers)
            if not url:
                break

    rows = [s for page in pages for s in page]
    keys = ["id", "name"] + sorted({k for r in rows for k in r} - {"id", "name"})
    with open(out / "stations.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} StopPlaces -> {out / 'stations.csv'}; columns: {keys}")
    if rows:
        print("first:", rows[0])


if __name__ == "__main__":
    sys.exit(main())
