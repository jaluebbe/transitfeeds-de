"""Download the newest DELFI GTFS feed and reduce it to a region.

DELFI_GTFS_URL (environment or ./.env) holds the download address with {date}
(YYYYMMDD). The newest feed not stored yet is reduced with filter_gtfs.py and
saved as <prefix>_gtfs_YYYYMMDD.zip. Meant for a daily cron job:

  17 6 * * *  cd /path/to/transitfeeds-de && python gtfs/fetch_delfi.py --region regions/hamburg.json
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

FILTER = Path(__file__).with_name("filter_gtfs.py")
CHUNK = 1 << 20


def env_url() -> str:
    """DELFI_GTFS_URL from the environment, else from ./.env."""
    url = os.environ.get("DELFI_GTFS_URL")
    env = Path(".env")
    if not url and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "DELFI_GTFS_URL":
                url = value.strip().strip("\"'")
    if not url or "{date}" not in url:
        sys.exit("DELFI_GTFS_URL with {date} is not set")
    return url


def exists(url: str) -> bool:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=30):
            return True
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return False
        raise


def download(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as r, open(target, "wb") as f:
        while chunk := r.read(CHUNK):
            f.write(chunk)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--region", type=Path, required=True, help="region JSON for filter_gtfs.py")
    ap.add_argument("--out", type=Path, default=Path("data/gtfs"))
    ap.add_argument("--prefix", help="file name prefix (default: region file name)")
    ap.add_argument("--days", type=int, default=8, help="days to look back")
    args = ap.parse_args()
    template = env_url()
    prefix = args.prefix or args.region.stem
    args.out.mkdir(parents=True, exist_ok=True)

    today = date.today()
    for back in range(-1, args.days):
        day = (today - timedelta(days=back)).strftime("%Y%m%d")
        target = args.out / f"{prefix}_gtfs_{day}.zip"
        if target.exists():
            print(f"{target.name}: already stored")
            return
        url = template.format(date=day)
        if not exists(url):
            continue
        with tempfile.TemporaryDirectory() as tmp:
            full = Path(tmp) / "gtfs.zip"
            download(url, full)
            part = Path(tmp) / "part"
            subprocess.run(
                [sys.executable, str(FILTER), str(full), str(part), "--region", str(args.region)],
                check=True,
            )
            archive = shutil.make_archive(str(Path(tmp) / target.stem), "zip", part)
            shutil.move(archive, target)
        print(f"{target.name}: stored")
        return
    print("no new feed")


if __name__ == "__main__":
    main()
