"""
Test for this round's changes:
  - percentile_to_descriptor band mapping
  - compute_yield_projection: 10/50/90%ile band + actual + projected
  - make_yield_projection_figure renders without error
  - gauge bar text no longer shows raw percentile number
  - detail chart tooltips no longer show redundant year in the date
"""
import datetime as dt
import numpy as np
import pandas as pd

from core.soil_xml import read_soil_xml
from core.dashboard_metrics import (
    compute_fallow_water_and_n_gain,
    compute_in_crop_rain,
    compute_crop_expectation_from_projection,
    compute_yield_projection,
)
from gauge_utils import (
    percentile_to_descriptor,
    make_gauge_bar_figure,
    make_detail_figure,
    make_yield_projection_figure,
)

# ── 1. Descriptor mapping ───────────────────────────────────────────────
print("=== percentile_to_descriptor ===")
test_cases = [(0, "low"), (24.9, "low"), (25, "low"), (25.1, "below average"),
              (45, "below average"), (45.1, "average"), (55, "average"),
              (55.1, "above average"), (75, "above average"), (75.1, "high"), (100, "high")]
for pct, expected in test_cases:
    actual = percentile_to_descriptor(pct)
    status = "OK" if actual == expected else f"FAIL (expected {expected})"
    print(f"  pct={pct:>6} -> {actual:<16} {status}")
    assert actual == expected, f"Mismatch at pct={pct}"
assert percentile_to_descriptor(None) is None
print("All descriptor mappings correct.\n")

# ── 2. Gauge bar text no longer shows raw percentile ───────────────────
rng = np.random.default_rng(2026)
dates = pd.date_range("1996-01-01", "2026-06-17", freq="D")
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

profile = read_soil_xml("data/Deep_clay_loam.xml")
plant_md, harvest_md = (3, 1), (11, 1)
today = dt.date(2026, 6, 1)

rain_res = compute_in_crop_rain(climate_df, plant_md, today)
fig = make_gauge_bar_figure(rain_res, "#dbeeff", "#0b3d6b")
annotation_text = fig.layout.annotations[0].text
print("=== Gauge bar annotation text ===")
print(" ", annotation_text)
assert "pct" not in annotation_text.lower(), "Raw percentile text leaked into gauge bar!"
assert "yrs)" not in annotation_text, "Raw year-count leaked into gauge bar (should be descriptor only)!"
print("Confirmed: no raw percentile/year-count in gauge bar text.\n")

# ── 3. Detail chart tooltip — no redundant year in date portion ────────
detail_fig = make_detail_figure(rain_res)
hover_template = detail_fig.data[-1].hovertemplate
print("=== Detail chart hover template ===")
print(" ", hover_template)
assert "%Y" not in hover_template, "Year format code still present in date portion of tooltip!"
print("Confirmed: tooltip date format has no redundant year.\n")

# ── 4. Yield projection ─────────────────────────────────────────────────
print("=== Yield projection (10-90%ile plume) ===")
water_res, _ = compute_fallow_water_and_n_gain(climate_df, profile, (1, 1), plant_md, today, sw_init_frac=0.05)
yp = compute_yield_projection(
    climate_df, plant_md, harvest_md, today,
    soil_water_at_planting_mm=water_res.current_value or 0.0,
    threshold_water_mm=120.0, wue_kg_ha_per_mm=25.0,
)
yield_res = compute_crop_expectation_from_projection(yp)
assert yield_res.current_value == yp.projected.iloc[-1], (
    "Yield gauge should report this season's projected value at harvest, not the conditional median"
)
print(f"Yield gauge value ({yield_res.current_value:.0f}) confirmed to equal this season's projected value at harvest ({yp.projected.iloc[-1]:.0f})")
print(f"n_comparable_years = {yp.n_comparable_years}")
print(f"Full date range: {yp.dates[0].date()} -> {yp.dates[-1].date()} ({len(yp.dates)} days)")
assert yp.p10 is not None and yp.p50 is not None and yp.p90 is not None
assert (yp.p90.values >= yp.p10.values).all(), "p90 should be >= p10 everywhere!"
print(f"p10 final: {yp.p10.iloc[-1]:.0f}, p50 final: {yp.p50.iloc[-1]:.0f}, p90 final: {yp.p90.iloc[-1]:.0f}")
assert yp.actual is not None
print(f"Actual trajectory: {yp.actual.index[0].date()} -> {yp.actual.index[-1].date()}, last value = {yp.actual.iloc[-1]:.0f}")
assert yp.projected is not None
print(f"Projected trajectory: {yp.projected.index[0].date()} -> {yp.projected.index[-1].date()}, last value = {yp.projected.iloc[-1]:.0f}")
# Projected should start at (approximately) the actual's last value
assert abs(yp.projected.iloc[0] - yp.actual.iloc[-1]) < 1e-3, "Projected should start exactly where actual leaves off!"
# Projected should be monotonically non-decreasing (yield outlook can't drop as rain accumulates)
assert (np.diff(yp.projected.values) >= -1e-6).all(), "Projected yield should be non-decreasing!"
print("Confirmed: projected continuation starts exactly at today's actual value and is non-decreasing.\n")

fig_yield = make_yield_projection_figure(yp)
assert fig_yield is not None
print(f"Yield plume figure built successfully with {len(fig_yield.data)} traces.")

# Legend label fix: the orange "projected" line shows YIELD, not rainfall —
# it was previously mislabeled "Projected (median rainfall)" which is
# confusing since the line's actual values are kg/ha, not mm.
trace_names = [t.name for t in fig_yield.data if t.name]
assert not any("median rainfall" in (n or "").lower() for n in trace_names), (
    "Legend should not mislabel the projected yield line as rainfall"
)
print("Confirmed: legend no longer mislabels the projected yield line as 'median rainfall'.")

# ── 5. Conditional (narrowing) inner plume ──────────────────────────────
print("\n=== Conditional inner plume (narrows toward harvest) ===")
assert yp.cond_p10 is not None and yp.cond_p90 is not None, "Conditional plume should be present!"
assert (yp.cond_p90.values >= yp.cond_p10.values).all(), "cond_p90 should be >= cond_p10 everywhere!"

# Conditional band should START pinched at today (both bounds equal the
# actual value at today, since there's zero elapsed uncertainty at the
# pinch point) and widen out as harvest approaches.
today_value = yp.actual.iloc[-1]
print(f"Conditional band at today: p10={yp.cond_p10.iloc[0]:.0f}, p90={yp.cond_p90.iloc[0]:.0f}, actual={today_value:.0f}")
assert abs(yp.cond_p10.iloc[0] - today_value) < 1e-3, "Conditional p10 should start exactly at today's actual value!"
assert abs(yp.cond_p90.iloc[0] - today_value) < 1e-3, "Conditional p90 should start exactly at today's actual value!"

spread_at_today = yp.cond_p90.iloc[0] - yp.cond_p10.iloc[0]
spread_at_harvest = yp.cond_p90.iloc[-1] - yp.cond_p10.iloc[-1]
print(f"Conditional spread at today: {spread_at_today:.1f}, at harvest: {spread_at_harvest:.1f}")
assert spread_at_today < 1e-3, "Conditional spread should be ~0 at today (pinch point)!"
assert spread_at_harvest > spread_at_today, "Conditional spread should widen toward harvest!"

outer_spread_at_harvest = yp.p90.iloc[-1] - yp.p10.iloc[-1]
print(f"Outer (unconditional) spread at harvest: {outer_spread_at_harvest:.1f}")
print(f"Conditional band is narrower than outer band at harvest: {spread_at_harvest < outer_spread_at_harvest}")

# ── 6. Regression test: bare Timestamp objects must not leak into marker
# traces (caused 'TypeError: Type is not JSON serializable: Timestamp'
# under kaleido's stricter orjson-based serialization path, even though
# it didn't reproduce under every kaleido version) ─────────────────────
print("\n=== Regression: today/maturity markers must use JSON-safe x values ===")
fig_dict = fig_yield.to_dict()
marker_traces = [t for t in fig_dict["data"] if t.get("mode") == "markers+text"]
assert len(marker_traces) == 2, f"Expected 2 marker traces (today, maturity), found {len(marker_traces)}"
for t in marker_traces:
    x_val = t["x"][0]
    assert isinstance(x_val, str), (
        f"Marker x-value must be a plain string (not pandas.Timestamp or similar) "
        f"to survive kaleido's stricter JSON serialization — got {type(x_val)}: {x_val!r}"
    )
    print(f"  Marker '{t.get('text', ['?'])[0]}' x-value is a plain string: {x_val!r}")
print("Confirmed: no bare Timestamp objects in marker trace x-values.")

print("\nAll tests passed.")
