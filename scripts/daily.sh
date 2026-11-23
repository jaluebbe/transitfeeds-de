#!/usr/bin/env bash
# Daily: fetch the newest DELFI timetable, refresh the station table and route IDs,
# write the train numbers of today and tomorrow.
#
# Settings (environment):
#   DATA            output base directory (required)
#   REGION          region file (default regions/hamburg.json)
#   STATIONS_CSV    OpenStation table from stations/openstation_netex.py (optional)
#   STATION_PREFIX  DHID prefix always kept in the station table (optional, e.g. de:02000)
#   ROUTE_IDS_COPY  where to copy route_ids.txt of a new timetable (optional)
#   ON_NEW_ROUTES   command run after copying new route IDs (optional)
set -euo pipefail
cd "$(dirname "$0")/.."

: "${DATA:?DATA must be set}"
REGION=${REGION:-regions/hamburg.json}
name=$(basename "$REGION" .json)
gtfs="$DATA/gtfs"
current="$gtfs/current"
mkdir -p "$gtfs" "$current" "$DATA/numbers"

python3 gtfs/fetch_delfi.py --region "$REGION" --out "$gtfs" || echo "fetch failed, using the last timetable"

zip=$(ls -1 "$gtfs"/"${name}"_gtfs_*.zip 2>/dev/null | tail -1)
if [ -z "$zip" ]; then
    echo "no timetable in $gtfs" >&2
    exit 1
fi

if [ "$(cat "$current/source" 2>/dev/null)" != "$zip" ]; then
    unzip -o -j -q "$zip" stop_ids.txt route_ids.txt -d "$current"
    echo "$zip" > "$current/source"
    echo "new timetable: $zip"
    if [ -n "${ROUTE_IDS_COPY:-}" ]; then
        cp "$current/route_ids.txt" "$ROUTE_IDS_COPY"
        if [ -n "${ON_NEW_ROUTES:-}" ]; then
            sh -c "$ON_NEW_ROUTES"
        fi
    fi
fi

stations_args=()
if [ -n "${STATIONS_CSV:-}" ] && [ -f "$STATIONS_CSV" ]; then
    prefix_args=()
    [ -n "${STATION_PREFIX:-}" ] && prefix_args=(--prefix "$STATION_PREFIX")
    python3 stations/filter_stations.py "$STATIONS_CSV" "$gtfs/stations_${name}.csv" \
        --gtfs-stops "$current/stop_ids.txt" "${prefix_args[@]}"
    stations_args=(--stations "$gtfs/stations_${name}.csv")
fi

for day in "$(date +%F)" "$(date -d tomorrow +%F)"; do
    python3 numbers/train_numbers.py "$zip" --region "$REGION" --date "$day" \
        --out "$DATA/numbers" "${stations_args[@]}"
done
