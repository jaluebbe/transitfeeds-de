import csv

from conftest import load

filter_stations = load("stations/filter_stations.py", "filter_stations")


def test_stations_of_the_network_one_row_per_eva(tmp_path):
    src = tmp_path / "stations.csv"
    with open(src, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "EVA", "RIL"])
        w.writerow(["dhid:de:02000:10950:EdB", "Hamburg Hbf", "8002549;8098549", "AH"])
        w.writerow(["dhid:de:01002:49079:EdB", "Kiel Hbf", "8000199", "AK"])
        w.writerow(["dhid:de:05315:1:EdB", "Köln Hbf", "8000207", "KK"])
        w.writerow(["dhid:de:02000:42950:EdB", "Heimfeld", "8006749", "AHFS"])
    stops = tmp_path / "stop_ids.txt"
    stops.write_text("de:02000:10950:6:2549013\nde:01002:49079:1:1\n")
    dst = tmp_path / "out.csv"
    filter_stations.main([str(src), str(dst), "--gtfs-stops", str(stops), "--prefix", "de:02000"])
    rows = list(csv.DictReader(open(dst)))
    assert [(r["eva"], r["dhid"]) for r in rows] == [
        ("8000199", "de:01002:49079"),
        ("8002549", "de:02000:10950"),
        ("8098549", "de:02000:10950"),
        ("8006749", "de:02000:42950"),
    ]
