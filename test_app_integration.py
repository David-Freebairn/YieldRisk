"""
Integration test for the updated dashboard_metrics.py:
  - Climate data floored at 1996 even if record goes back further
  - Fallow water/nitrogen window is fixed: fallow_start -> plant_date
  - In-crop rain / PTQ / yield outlook are gated: not_yet_applicable
    if today < plant_date
  - PTQ is now a CUMULATIVE SUM, not a mean
"""
import datetime as dt
import numpy as np
import pandas as pd

from core.soil_xml import read_soil_xml
from core.dashboard_metrics import (
    compute_fallow_water_and_n_gain,
    compute_in_crop_rain,
    compute_photothermal_index,
    compute_crop_expectation_from_projection,
    compute_yield_projection,
    MetricResult,
    HIST_FLOOR_YEAR,
)
from gauge_utils import make_gauge_bar_figure, make_detail_figure

rng = np.random.default_rng(2026)

# Climate record deliberately starts in 1985 to test the 1996 floor is
# actually being applied (years 1985-1995 should be excluded).
start = pd.Timestamp("1985-01-01")
end = pd.Timestamp("2026-06-17")
dates = pd.date_range(start, end, freq="D")
n = len(dates)
doy = dates.dayofyear.values

tmax = 27 + 7 * np.sin(2 * np.pi * (doy - 30) / 365.0) + rng.normal(0, 2.5, n)
tmin = tmax - 11 - rng.normal(0, 1.5, n)
tmean = (tmax + tmin) / 2
rain = np.where(rng.random(n) < 0.22, rng.exponential(9, n), 0.0)
radiation = 17 + 7 * np.sin(2 * np.pi * (doy - 30) / 365.0) + rng.normal(0, 1.8, n)
epan = np.clip(5 + 0.15 * (tmax - 20) + rng.normal(0, 0.6, n), 0.5, None)

climate_df = pd.DataFrame(
    {"rain": rain, "tmax": tmax, "tmin": tmin, "tmean": tmean, "radiation": radiation, "epan": epan},
    index=dates,
)
climate_df.index.name = "date"

profile = read_soil_xml("data/Deep_clay_loam.xml")
fallow_start_md, plant_md = (1, 1), (3, 1)
wue, threshold_water = 25.0, 120.0

print(f"HIST_FLOOR_YEAR = {HIST_FLOOR_YEAR}")
print(f"Climate record spans {dates[0].year}-{dates[-1].year} ({n} days)\n")

# ── Scenario A: today is AFTER plant date (1 Jun) ──────────────────────────
print("=== Scenario A: today = 1 Jun 2026 (after planting) ===")
today_after = dt.date(2026, 6, 1)
water_res, n_res = compute_fallow_water_and_n_gain(climate_df, profile, fallow_start_md, plant_md, today_after, sw_init_frac=0.05)
rain_res = compute_in_crop_rain(climate_df, plant_md, today_after)
ptq_res = compute_photothermal_index(climate_df, plant_md, today_after)
harvest_md = (11, 1)
yield_projection = compute_yield_projection(
    climate_df, plant_md, harvest_md, today_after, water_res.current_value or 0.0, threshold_water, wue
) if not rain_res.not_yet_applicable else None
yield_res = (
    compute_crop_expectation_from_projection(yield_projection)
    if yield_projection is not None
    else MetricResult("Crop yield outlook", "kg/ha", None, None, 0, {}, today_after.year, None, not_yet_applicable=True)
)

print(f"Water gain (fallow_start->plant only): value={water_res.current_value:.1f}mm pct={water_res.percentile} n_years={water_res.n_comparable_years}")
print(f"  -> years used: {sorted(water_res.series_by_year.keys())[:5]} ... (min year should be >= {HIST_FLOOR_YEAR})")
assert min(water_res.series_by_year.keys()) >= HIST_FLOOR_YEAR, "1996 floor violated for water!"
print(f"Nitrogen gain: value={n_res.current_value:.2f} pct={n_res.percentile} n_years={n_res.n_comparable_years}")
print(f"In-crop rain: value={rain_res.current_value:.1f}mm pct={rain_res.percentile} not_yet_applicable={rain_res.not_yet_applicable}")
assert min(rain_res.series_by_year.keys()) >= HIST_FLOOR_YEAR, "1996 floor violated for rain!"
print(f"PTQ (cumulative): value={ptq_res.current_value:.2f} pct={ptq_res.percentile} not_yet_applicable={ptq_res.not_yet_applicable}")
print(f"Yield outlook: value={yield_res.current_value:.1f}kg/ha pct={yield_res.percentile} not_yet_applicable={yield_res.not_yet_applicable}")
assert not rain_res.not_yet_applicable
assert not ptq_res.not_yet_applicable
assert not yield_res.not_yet_applicable

# Yield gauge must report THIS SEASON'S OWN PROJECTED VALUE AT HARVEST
# (yield_projection.projected's last value, matching the orange line's
# "maturity" endpoint on the detail chart), not today's actual cumulative
# yield outlook to date — these should differ substantially mid-season,
# since in-crop rain hasn't fully accumulated yet.
assert yield_projection.projected is not None, "Projected series should exist mid-season"
expected_at_harvest = float(yield_projection.projected.iloc[-1])
assert abs(yield_res.current_value - expected_at_harvest) < 1e-6, (
    f"Yield gauge value {yield_res.current_value} should equal this season's projected "
    f"value at harvest {expected_at_harvest}, not today's actual value"
)
print(f"  -> Confirmed: yield gauge value ({yield_res.current_value:.1f}) matches this season's projected value at harvest, not today's actual cumulative value")

# Check PTQ really is cumulative (increasing), not a bounded mean
ptq_current_series = ptq_res.series_by_year[ptq_res.current_year]
assert ptq_current_series.iloc[-1] > ptq_current_series.iloc[0], "PTQ should grow (cumulative sum)"
assert ptq_current_series.iloc[-1] > 5, f"PTQ cumulative sum should be large (>5), got {ptq_current_series.iloc[-1]}"
print(f"  -> PTQ series confirmed cumulative: starts at {ptq_current_series.iloc[0]:.2f}, ends at {ptq_current_series.iloc[-1]:.2f}")

print("\n=== Scenario B: today = 15 Feb 2026 (BEFORE planting, fallow still in progress) ===")
today_before = dt.date(2026, 2, 15)
water_res_b, n_res_b = compute_fallow_water_and_n_gain(climate_df, profile, fallow_start_md, plant_md, today_before, sw_init_frac=0.05)
rain_res_b = compute_in_crop_rain(climate_df, plant_md, today_before)
ptq_res_b = compute_photothermal_index(climate_df, plant_md, today_before)
yield_projection_b = compute_yield_projection(
    climate_df, plant_md, harvest_md, today_before, water_res_b.current_value or 0.0, threshold_water, wue
) if not rain_res_b.not_yet_applicable else None
yield_res_b = (
    compute_crop_expectation_from_projection(yield_projection_b)
    if yield_projection_b is not None
    else MetricResult("Crop yield outlook", "kg/ha", None, None, 0, {}, today_before.year, None, not_yet_applicable=True)
)

print(f"Water gain (fallow in progress, start->today since before plant): value={water_res_b.current_value}")
print(f"In-crop rain: not_yet_applicable={rain_res_b.not_yet_applicable} (should be True)")
print(f"PTQ: not_yet_applicable={ptq_res_b.not_yet_applicable} (should be True)")
print(f"Yield outlook: not_yet_applicable={yield_res_b.not_yet_applicable} (should be True)")
assert rain_res_b.not_yet_applicable, "in_crop_rain should be gated before plant date!"
assert ptq_res_b.not_yet_applicable, "PTQ should be gated before plant date!"
assert yield_res_b.not_yet_applicable, "yield outlook should be gated before plant date!"

# Gauge + detail figures must handle not_yet_applicable cleanly
fig_gauge = make_gauge_bar_figure(rain_res_b, "#dbeeff", "#0b3d6b")
fig_detail = make_detail_figure(rain_res_b)
assert fig_gauge is not None and fig_detail is not None
print("  -> not_yet_applicable gauge + detail figures built without error")

# Detail chart must use real dates, not day-offsets
detail_fig_water = make_detail_figure(water_res)
x_vals = detail_fig_water.data[-1].x  # current season trace
assert isinstance(x_vals[0], (pd.Timestamp, np.datetime64)) or hasattr(x_vals[0], "year"), f"x-axis should be real dates, got {type(x_vals[0])}"
print(f"\nDetail chart x-axis confirmed to use real dates: first value = {x_vals[0]}")

print("\nAll scenarios passed.")
