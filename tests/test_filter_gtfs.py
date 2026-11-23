import csv

from conftest import load

filter_gtfs = load("gtfs/filter_gtfs.py", "filter_gtfs")


def write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerows(rows)


def feed(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    write(src / "agency.txt", [["agency_id", "agency_name"], ["A", "U-Bahn"], ["B", "DB"], ["C", "Other"]])
    write(src / "routes.txt", [
        ["route_id", "agency_id", "route_short_name", "route_type"],
        ["u1", "A", "U1", "1"],
        ["re7-hh", "B", "RE7", "100"],
        ["re7-other", "B", "RE7", "100"],
        ["bus", "C", "5", "3"],
    ])  # fmt: skip
    write(src / "trips.txt", [
        ["route_id", "service_id", "trip_id", "shape_id"],
        ["u1", "s1", "t1", "sh1"],
        ["re7-hh", "s1", "t2", ""],
        ["re7-other", "s2", "t3", ""],
        ["bus", "s2", "t4", ""],
    ])  # fmt: skip
    write(src / "stop_times.txt", [
        ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
        ["t1", "08:00:00", "08:00:00", "de:02000:1:1:1", "1"],
        ["t2", "09:00:00", "09:00:00", "de:01002:9:1:1", "1"],
        ["t2", "10:00:00", "10:00:00", "de:02000:10950:6:1", "2"],
        ["t3", "09:00:00", "09:00:00", "de:05315:1:1:1", "1"],
        ["t4", "09:00:00", "09:00:00", "de:02000:2:1:1", "1"],
    ])  # fmt: skip
    write(src / "stops.txt", [["stop_id", "stop_name", "parent_station"], ["de:02000:1:1:1", "X", "de:02000:1"],
                              ["de:02000:1", "X", ""], ["de:05315:1:1:1", "Y", ""]])
    write(src / "calendar.txt", [["service_id", "monday"], ["s1", "1"], ["s2", "1"]])
    return src


def test_keeps_agencies_and_lines_calling_in_the_region(tmp_path):
    src, out = feed(tmp_path), tmp_path / "out"
    filter_gtfs.main([str(src), str(out), "--agencies", "A", "--lines", "RE7", "--line-stop-prefix", "de:02000:"])
    assert (out / "route_ids.txt").read_text().split() == ["re7-hh", "u1"]
    trips = [r["trip_id"] for r in csv.DictReader(open(out / "trips.txt"))]
    assert trips == ["t1", "t2"]
    stops = [r["stop_id"] for r in csv.DictReader(open(out / "stops.txt"))]
    assert stops == ["de:02000:1:1:1", "de:02000:1"]  # parent station kept


def test_region_file(tmp_path):
    src, out = feed(tmp_path), tmp_path / "out"
    region = tmp_path / "r.json"
    region.write_text('{"agencies": ["C"], "lines": [], "line_stop_prefix": ""}')
    filter_gtfs.main([str(src), str(out), "--region", str(region)])
    assert (out / "route_ids.txt").read_text().split() == ["bus"]
