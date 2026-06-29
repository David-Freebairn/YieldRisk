"""
fetch_sample_data.py
====================
Run this script ONCE locally when SILO is available to generate the
bundled sample dataset for Dalby Post Office (station 41023).

This file is committed to the repo so the fallback always works even
when SILO is down. It only needs to be re-run if the sample data needs
refreshing (e.g. to extend to a more recent year).

Usage:
    cd <repo root>
    python fetch_sample_data.py

Output:
    sample_data/dalby_sample.parquet   — real Dalby climate data 1996-today
    sample_data/dalby_station.json     — station metadata (id, name, lat, lon)
"""

import json
import sys
from pathlib import Path

# Make sure core/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.silo import fetch_station_met, search_stations

DALBY_STATION_ID = 41023
DALBY_NAME       = "DALBY POST OFFICE [QLD]"
DALBY_LAT        = -27.184
DALBY_LON        = 151.264
START_YEAR       = 1996

OUT_DIR = Path(__file__).resolve().parent / "sample_data"
OUT_DIR.mkdir(exist_ok=True)

print(f"Fetching Dalby (station {DALBY_STATION_ID}) climate data from {START_YEAR} onwards...")
print("This may take 15–60 seconds depending on SILO response time.")

df = fetch_station_met(
    station_id=DALBY_STATION_ID,
    start=f"{START_YEAR}-01-01",
    end=None,          # silo.py's _full_end() will use today
    lat=DALBY_LAT,
    lon=DALBY_LON,
)

# Trim to 1996 onwards (HIST_FLOOR_YEAR) in case fetch_station_met pulls earlier
df = df[df.index.year >= START_YEAR]

parquet_path = OUT_DIR / "dalby_sample.parquet"
df.to_parquet(parquet_path)
print(f"Saved {len(df):,} days ({df.index[0].date()} → {df.index[-1].date()}) "
      f"to {parquet_path}  ({parquet_path.stat().st_size // 1024} KB)")

# Save station metadata so the app knows what to show in the UI
meta = {
    "id":    DALBY_STATION_ID,
    "name":  DALBY_NAME,
    "label": f"{DALBY_NAME}  ({DALBY_LAT}, {DALBY_LON})",
    "lat":   DALBY_LAT,
    "lon":   DALBY_LON,
    "state": "QLD",
}
json_path = OUT_DIR / "dalby_station.json"
json_path.write_text(json.dumps(meta, indent=2))
print(f"Saved station metadata to {json_path}")
print("\nDone. Commit both files to the repo so the SILO-down fallback works.")
