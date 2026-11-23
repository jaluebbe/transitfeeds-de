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
| `numbers/train_numbers.py` | Train numbers of one day from the timetable, by line, station and departure |
| `scripts/daily.sh` | Daily run of the above |

## Setup

Copy `.env.example` to `.env` and fill in the feed addresses and keys. The
Mobilithek subscriptions need the client certificate as `certs/client.crt` and
`certs/client.key`. Subscription IDs and keys are personal and not part of the
repository.

```
docker compose -f docker-compose.example.yml up -d --build
```

Daily, from cron (`scripts/daily.sh`): fetch the newest timetable, refresh the
station table and `route_ids.txt`, write the train numbers of today and tomorrow
(S-Bahn and regional trains; U-Bahn numbers come from GTI or SIRI, AKN numbers
from SIRI):

```
17 6 * * * cd /path/to/transitfeeds-de && DATA=/path/to/data STATIONS_CSV=/path/to/openstation/stations.csv STATION_PREFIX=de:02000 ROUTE_IDS_COPY=/path/to/data/delfi/route_ids.txt ON_NEW_ROUTES="docker compose -f /path/to/docker-compose.yml restart delfi-logger" scripts/daily.sh >> /path/to/data/daily.log 2>&1
```

`DELFI_GTFS_URL` goes into `.env` in the repository directory. The station
table comes from OpenStation, occasionally (57 of the 7,500 requests per day):

```
python stations/openstation_netex.py /path/to/openstation
```

Output: `gtfs/<region>_gtfs_YYYYMMDD.zip`, `gtfs/current/` (stop and route IDs
of the newest timetable), `gtfs/stations_<region>.csv` and
`numbers/train_numbers_YYYYMMDD.json` below `DATA`.

Each key `LINE|de:<AGS>:<station>|YYYY-MM-DDTHH:MM` (planned local departure)
holds `[number, next station]` pairs: trains of one line leaving a station in
the same minute (opposite directions, coupled trains) share a key and differ in
the next station. `--stations` merges stations the timetable names by EVA number
(`de:02000:8000147`) into their DHID (`de:02000:49950`). Checked on 23.11.2026
against OpenBoards: 3511 departures found with the right number, 10 with another
one, 57 not found.

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
