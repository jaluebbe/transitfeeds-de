import csv
from datetime import date

from conftest import load

tn = load("numbers/train_numbers.py", "train_numbers")


def write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


def make_feed(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    write(src / "routes.txt", [
        ["route_id", "agency_id", "route_short_name", "route_type"],
        ["s7", "10375", "S7", "109"],
        ["sev", "10375", "S1EV", "3"],
        ["akn", "10833", "A1", "100"],
    ])  # fmt: skip
    write(src / "trips.txt", [
        ["route_id", "service_id", "trip_id", "trip_short_name"],
        ["s7", "mo", "a", "047027"],
        ["s7", "mo", "b", "047028"],
        ["s7", "sa", "c", "047029"],
        ["sev", "mo", "d", "191009"],
        ["akn", "mo", "e", "068157"],
    ])  # fmt: skip
    write(src / "stop_times.txt", [
        ["trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"],
        ["a", "de:02000:10950_G:1:1", "1", "23:50:00", "23:50:00"],
        ["a", "de:02000:10952:1:1", "2", "24:17:00", "24:17:00"],
        ["a", "de:02000:8000147:1:1", "3", "24:30:00", ""],
        ["b", "de:02000:8000147:1:1", "1", "23:58:00", "24:05:00"],
        ["b", "de:02000:10952:2:2", "2", "24:17:00", "24:17:00"],
        ["b", "de:02000:10950:2:2", "3", "24:20:00", "24:20:00"],
        ["c", "de:02000:10950:1:1", "1", "10:00:00", "10:00:00"],
        ["c", "de:02000:10952:1:1", "2", "10:03:00", "10:03:00"],
        ["d", "de:02000:1:1:1", "1", "10:00:00", "10:00:00"],
        ["d", "de:02000:2:1:1", "2", "10:10:00", "10:10:00"],
    ])  # fmt: skip
    write(src / "calendar.txt", [
        ["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
         "start_date", "end_date"],
        ["mo", "1", "0", "0", "0", "0", "0", "0", "20261101", "20261231"],
        ["sa", "0", "0", "0", "0", "0", "1", "0", "20261101", "20261231"],
    ])  # fmt: skip
    write(src / "calendar_dates.txt", [["service_id", "date", "exception_type"]])
    stations = tmp_path / "stations.csv"
    write(stations, [["eva", "dhid", "name", "ril", "eva_all"],
                     ["8000147", "de:02000:49950", "Hamburg-Harburg", "AHAR", "8000147;8098147"]])
    return tn.Feed(src), stations


def test_rail_trips_of_the_day_keyed_by_line_station_and_departure(tmp_path):
    feed, stations = make_feed(tmp_path)
    result = tn.train_numbers(feed, date(2026, 11, 23), {"10375"}, tn.eva_aliases(stations))
    assert result["trips"] == {"a": "47027", "b": "47028"}  # no bus, other day or other agency
    assert result["stops"] == {
        "S7|de:02000:10950|2026-11-23T23:50": [["47027", "de:02000:10952"]],
        "S7|de:02000:10952|2026-11-24T00:17": [["47027", "de:02000:49950"], ["47028", "de:02000:10950"]],
        "S7|de:02000:49950|2026-11-24T00:05": [["47028", "de:02000:10952"]],
    }
