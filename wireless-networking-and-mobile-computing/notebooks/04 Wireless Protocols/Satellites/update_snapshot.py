"""
update_snapshot - staff script: refreshes the orbit snapshot in tle/ from CelesTrak.

Students never run this. CelesTrak blocks addresses that download the same data repeatedly,
so a class must not fetch it live; staff refresh the snapshot once a year, shortly before the
assignment opens, and commit the new files.

    python update_snapshot.py
"""
import time
import urllib.request
from pathlib import Path

GROUPS = ["gps-ops", "galileo", "glo-ops", "beidou", "starlink", "oneweb", "iridium-NEXT", "geo", "stations"]
URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP={}&FORMAT=tle"
DEST = Path(__file__).with_name("tle")


def main():
    DEST.mkdir(exist_ok=True)
    for group in GROUPS:
        req = urllib.request.Request(URL.format(group), headers={"User-Agent": "ETH WNMC course snapshot"})
        text = urllib.request.urlopen(req, timeout=120).read().decode("utf-8")
        n = sum(1 for line in text.splitlines() if line.startswith("1 "))
        if n == 0:
            raise SystemExit(f"{group}: no orbits received (blocked or renamed?); the old file is kept")
        (DEST / f"{group}.tle").write_text(text, encoding="utf-8", newline="\n")
        print(f"{group:14s}{n:7d} satellites")
        time.sleep(2)


if __name__ == "__main__":
    main()
