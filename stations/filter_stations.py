"""Reduce the OpenStation table (openstation_netex.py) to the stations of a network, one row per EVA number.

Usage:
  python stations/filter_stations.py stations.csv stations_region.csv --gtfs-stops OUT_DIR/stop_ids.txt [--prefix de:02000]

A station is kept if a stop of the filtered GTFS (stop_ids.txt or stops.txt from
gtfs/filter_gtfs.py) belongs to it (same de:<AGS>:<number>), or if its DHID starts
with one of the --prefix values (useful where GTFS stops use another DHID).

Output columns: eva, dhid (as in DELFI/GTFS, e.g. de:02000:10950), name, ril, eva_all.
"""

import argparse
import csv


def dhid(station_id):
    return station_id.removeprefix("dhid:").removesuffix(":EdB")


def station_of(stop_id):
    return ":".join(stop_id.split(":")[:3])


def gtfs_stations(path):
    with open(path, encoding="utf-8-sig") as f:
        first = f.readline()
        f.seek(0)
        if first.startswith("stop_id"):
            ids = [r["stop_id"] for r in csv.DictReader(f)]
        else:
            ids = [line.strip() for line in f if line.strip()]
    return {station_of(s) for s in ids if s.startswith("de:")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--gtfs-stops")
    ap.add_argument("--prefix", action="append", default=[])
    a = ap.parse_args(argv)
    if not a.gtfs_stops and not a.prefix:
        ap.error("give --gtfs-stops and/or --prefix")

    stations = gtfs_stations(a.gtfs_stops) if a.gtfs_stops else set()
    prefixes = tuple(a.prefix)
    rows = []
    with open(a.src, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = dhid(r["id"])
            if not ((prefixes and d.startswith(prefixes)) or station_of(d) in stations):
                continue
            evas = [e for e in (r.get("EVA") or "").split(";") if e]
            for e in evas:
                rows.append({"eva": e, "dhid": d, "name": r["name"], "ril": r.get("RIL", ""),
                             "eva_all": ";".join(evas)})
    rows.sort(key=lambda r: (r["dhid"], r["eva"]))
    with open(a.dst, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["eva", "dhid", "name", "ril", "eva_all"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} EVA numbers of {len({r['dhid'] for r in rows})} stations -> {a.dst}")


if __name__ == "__main__":
    main()
