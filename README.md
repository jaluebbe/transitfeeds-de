# transitfeeds-de

Tools for German public transport open data: download and reduce the nationwide
DELFI GTFS timetable to a region, log real-time feeds from the Mobilithek (GTFS-RT,
SIRI ET, service alerts) and DB APIs (OpenBoards), and map DB station numbers (EVA)
to the stop IDs (DHID) used by DELFI and GTFS.

It serves map projects like [HVVMap](https://github.com/jaluebbe/HVVMap); the
Hamburg settings live in `regions/hamburg.json` and `docker-compose.example.yml`,
other regions need their own.

## Layout

| Path | Purpose |
|---|---|
| `gtfs/fetch_delfi.py` | Download the newest DELFI GTFS feed (daily cron) and reduce it with `filter_gtfs.py` |
| `gtfs/filter_gtfs.py` | Reduce a GTFS feed to the agencies and lines of a region (streaming, the full feed is ~4 GB) |
| `regions/*.json` | Region settings: agencies, line names, stop prefix |
| `loggers/delfi_logger.py` | GTFS-RT trip updates of selected routes |
| `loggers/siri_logger.py` | SIRI ET journeys filtered by operator, line, category or nearby stops |
| `loggers/alerts_logger.py` | GTFS-RT service alerts as new/changed/gone events |
| `loggers/openboards_logger.py` | DB OpenBoards departures of a few stations (raw responses) |
| `stations/openstation_netex.py` | Download DB OpenStation NeTEx (all stations) as `stations.csv` |
| `stations/filter_stations.py` | Reduce it to the stations of a filtered GTFS, one row per EVA number |

## Setup

Copy `.env.example` to `.env` and fill in the feed addresses and keys. The
Mobilithek subscriptions need the client certificate as `certs/client.crt` and
`certs/client.key`. Subscription IDs and keys are personal and not part of the
repository.

```
docker compose -f docker-compose.example.yml up -d --build
```

Timetable, daily:

```
python gtfs/fetch_delfi.py --region regions/hamburg.json   # data/gtfs/hamburg_gtfs_YYYYMMDD.zip
```

Put `route_ids.txt` of the reduced feed into the DELFI logger's data directory
(`ROUTE_IDS`); DELFI route IDs change between exports.

Stations, occasionally (57 requests of the 7,500 per day):

```
python stations/openstation_netex.py openstation_out
python stations/filter_stations.py openstation_out/stations.csv stations_hamburg.csv \
    --gtfs-stops hamburg_gtfs_YYYYMMDD/stop_ids.txt --prefix de:02000
```

## Findings

- DELFI GTFS-RT trip IDs match the static DELFI export of the same week.
- For DB rail lines (S-Bahn, RE, RB) the static `trip_short_name` is the train
  number, zero-padded (`011546` = RE7 11546), the same number SIRI and OpenBoards
  report. For AKN the static number loses the leading 2 of six-digit numbers
  (`068157` for 268157); SIRI has the full one.
- Hamburg U-Bahn trips carry the Hochbahn train number in SIRI as `sbskop.NNNNNN`;
  replacement or swapped trains run with +7000 (hour + 70).
- Some stations have two EVA numbers (main line and S-Bahn, e.g. Hamburg Hbf
  8002549/8098549); OpenStation lists both.
- SIRI ET feeds change about every 5 minutes, the DELFI GTFS-RT feed about every minute.

## Attribution

Timetable and real-time data: DELFI e.V. (via Mobilithek). Station data and
departures: Deutsche Bahn (DB API Marketplace). Check the licence of each data
set before publishing derived data.

## License

MIT, see `LICENSE`.
