# Yieldrisk

A dashboard for following soil water and nitrogen gains during fallow,
and crop prospects through the season — built on the same SILO climate
data and soil/water-balance engines as RiskAware.
Wired to **real RiskAware logic** — real SILO climate
data, the real PERFECT water balance engine, and a real nitrogen
mineralisation model — not dummy/simulated data.

## What's real here

- **Site search** — `core/silo.py`, unmodified copy from RiskAware.
  Searches SILO stations, fetches full climate record (rain, tmax,
  tmin, tmean, radiation, epan), disk-cached for 24h.
- **Soil selection** — `core/soil_xml.py` (extended) reads the 12
  HowLeaky `.soil` XML files in `data/`. Extended to also parse
  `OrganicCarbon`, `CarbonNitrogenRatio`, and
  `NitrateMineralisationCoefficient` (needed for the nitrogen model;
  the original RiskAware reader didn't pull these through since
  Howwet only needed water, not nitrogen).
- **Fallow water gain** — `core/waterbalance.py`, unmodified copy of
  the PERFECT engine (SCS curve number runoff, infiltration/drainage
  cascade, Ritchie two-stage soil evaporation, transpiration, deep
  drainage, MUSLE erosion).
- **Fallow nitrogen gain** — `core/nitrogen.py`, ported from DHM
  Environmental Software Engineering's `A4_HowWetN_Engine.cs`
  (`CalculateN()` method), with permission, per your confirmation as
  a DHM client/licensee. See the module docstring for the full change
  description required by the original license terms. Daily
  mineralisation rate = min(moisture factor, temperature factor) ×
  soil's mineralisation coefficient × potential mineralisable N pool
  (from organic carbon ÷ C:N ratio). Operates on layer-1 soil water
  only, exactly as the original.
- **In-crop rain** — cumulative rainfall from plant date to today,
  using the same calendar-aligned historical-year alignment technique
  as `1_Season.py`'s `build_series` (generalised in
  `core/season_metrics.py` to anchor on arbitrary plant/harvest dates
  rather than "months back from today").
- **Photothermal index (PTQ)** — `core/crop_metrics.py`:
  `PTQ = solar radiation (MJ/m²/day) / mean temperature (°C)`,
  averaged over the in-crop period to date.
- **Crop yield outlook** — `core/crop_metrics.py`, French & Schultz
  style: `(soil water at planting + in-crop rain to date − threshold
  water) × WUE`. Soil water at planting is taken from the fallow water
  gain result on the day before planting starts (current
  implementation: from the fallow-period water balance ending at
  "today", which is a simplification worth revisiting — see Known
  limitations).

## How percentiles work

For every metric, every historical year (from 1996 onwards — see below)
that has a comparable-length window is run through the **same calculation
engine** as the current year (not just a percentile of raw rainfall) —
e.g. fallow water gain percentile compares this year's PERFECT-simulated
PASW gain against what PERFECT would have simulated in each historical
year, given the same soil and the same fallow start date. This means the
percentile reflects model-driven outcomes, not just climate inputs.

If fewer than 3 comparable historical years exist for a given window,
the gauge shows a flat grey bar with an explanatory message instead of
a marker, rather than presenting a misleading percentile.

## Window rules (updated)

- **Historical comparison floor**: all percentile comparisons use 1996
  onwards only, even if the station's SILO record goes back further.
  This is hard-coded as `HIST_FLOOR_YEAR` in `core/dashboard_metrics.py`.
- **Fallow water gain / fallow nitrogen gain**: window is FIXED at
  fallow start → plant date. It does not extend past planting even if
  "today" is later in the season — once the crop is in the ground, this
  metric stops moving and reflects what happened during the fallow only.
  If "today" is still before the plant date, the current season's window
  runs fallow start → today (fallow still in progress), while historical
  comparison years always use their full fallow-start → plant-date window.
- **In-crop rain / photothermal quotient / yield outlook**: these are
  gated off entirely (not_yet_applicable=True, shown as a grey "not yet
  relevant" bar) until today reaches the plant date — they have no
  meaning before the crop exists.
- **Photothermal quotient is now a CUMULATIVE SUM** (running total of
  daily PTQ from plant date to today), not a running mean. Unit:
  "Cum MJ/m²/°C".
- **Detail charts use real calendar dates on the x-axis** (the current
  season's own dates), with every historical year's trajectory
  positionally re-projected onto those same dates so they overlay
  correctly. Tooltips show the date (day/month only, no year — the year
  is shown via the series label instead), and the value rounded to 0
  decimal places with the metric's unit (mm / kg/ha / Cum MJ/m²/°C as
  appropriate).

## Gauge bar + chart display (latest round)

- Gauge bar text no longer shows the raw percentile number or year
  count — it shows a plain-language band descriptor instead:
  0-25% → "low", 25-45% → "below average", 45-55% → "average",
  55-75% → "above average", >75% → "high" (see
  `percentile_to_descriptor` in `gauge_utils.py`).
- Detail charts no longer repeat a title that duplicates the section
  header already shown above the gauge bar.
- **Yield outlook detail chart** is now a dedicated visualisation
  (`make_yield_projection_figure`, fed by `compute_yield_projection`)
  rather than the generic detail chart:
  - A shaded 10th-90th percentile band spanning the FULL plant date →
    harvest date window (the "outer" band), built from every historical
    year's (≥1996) rainfall-to-yield trajectory using the same
    soil-water-at-planting, threshold water, and WUE inputs as the
    current season (isolating rainfall variability as the source of
    spread).
  - A 50th percentile (median) line across the same full window.
  - The current season's **actual** trajectory (red) from plant date to
    today, using real rainfall.
  - A **projected** continuation (orange) from today to harvest: starts
    exactly at today's actual cumulative value, then advances using the
    historical MEDIAN year's day-to-day rainfall increments (not its
    absolute level) for each remaining day, converted to yield outlook
    at each step.
  - A **conditional (inner) 10th-90th percentile band**, today → harvest,
    nested inside the outer band and visually darker. Unlike the outer
    band (which only conditions on the planting date), this one
    conditions on what has actually happened so far this season: for
    each historical year, its rainfall INCREMENTS from that year's own
    equivalent "today" position onward are added on top of THIS
    season's actual cumulative rain at today. The result is pinched to
    zero spread exactly at today (confirmed in
    `test_header_and_yield_changes.py`) and widens toward harvest, but
    stays narrower than the outer band throughout, since it's
    conditioning on strictly more information.
  - "today" and "maturity" point markers, matching the supplied mockup.

## UI / cosmetic changes (latest round)

- Title changed to "Season tracker" with a subheading describing what
  it does, matching the v3 mockup.
- Added an **Information** button below the title/subheading that
  toggles a short static blurb explaining the tool, the setup fields,
  and how each metric is calculated.
- Added a **❓ help button** next to "How are we going as of [date]"
  specifically explaining how to read the gauge bars and the band
  descriptors (low / below average / average / above average / high).
- Setup panel field order changed to soil type → dates → crop → site
  (site selection moved to the bottom), so the rest of the form is
  visible and usable immediately rather than being blocked above the
  fold while site search/download is in progress.
- Once a station is selected, the search box/dropdown disappears (as
  before) and now also shows "⏳ Downloading 30 years of daily data may
  take 30-60 seconds. Please wait!" until the SILO fetch completes
  (`climate_ready` session-state flag, set False on station
  selection/reset and True once `ensure_climate_cached` succeeds).
  An explicit `st.rerun()` fires immediately after the FIRST successful
  fetch (guarded so it only fires once, not on every subsequent rerun)
  so the downloading message disappears as soon as data is ready,
  rather than staying visible until some unrelated later interaction
  triggers the next redraw — Streamlit doesn't retroactively remove
  elements already rendered earlier in the same script pass, so without
  this explicit rerun the message would otherwise persist one
  interaction longer than necessary.
- "Download chart" renamed to "Download summary".
- Tightened vertical spacing between stacked form widgets via new CSS
  rules in `core/styles.py` (margin/gap reductions on Streamlit's
  generic block/element wrappers — scoped to be safe to share across
  RiskAware pages if this file is ever merged back, since the
  selectors target generic Streamlit containers rather than anything
  Season-Tracker-specific).

## Bug fixes (this round)

- **Stale radio list after site confirmation**: after confirming a
  station from a multi-result radio list, the radio buttons and
  "Select" button could remain visible below the green confirmed
  banner and downloading message, even though the underlying
  if/else logic should have made them mutually exclusive. Fixed by
  rendering the entire site-selection area inside a single
  `st.empty()` placeholder (`site_area`), rebuilt fully fresh on every
  run and explicitly cleared (`site_area.empty()`) immediately before
  every `st.rerun()` call in that section, so old widgets can never
  visually persist alongside the new confirmed state regardless of
  rerun timing.
- **Misaligned "How are we going as of [date] ❓" header**: the title
  text was sharing a narrow column with the date/month inputs and the
  help button, causing it to wrap onto two lines while the controls
  stayed pinned at a fixed height above the wrapped text — disconnected
  from where the title actually ended up. Fixed by giving the title its
  own full-width line above the date/month/help control row, rather
  than trying to fit a wrapping heading and several widgets into the
  same row of columns.

## Yield gauge correction + summary doc reliability (latest round)

- **"Crop yield outlook" gauge now reports THIS SEASON'S OWN PROJECTED
  yield AT HARVEST** — the same endpoint as the orange "maturity" marker
  on the detail chart (`yield_projection.projected.iloc[-1]`) — rather
  than today's actual cumulative value (the original bug) or the
  conditional median across all historical years (an intermediate
  attempt that was also corrected based on feedback: the projected
  value for THIS year specifically, not a cross-year median, is what's
  wanted). Implemented in
  `compute_crop_expectation_from_projection` in
  `core/dashboard_metrics.py`. The percentile/band descriptor is still
  computed by ranking that projected-at-harvest value against the OUTER
  (unconditional) historical distribution at harvest, via interpolation
  against the p10/p50/p90 anchor points. Verified in
  `test_app_integration.py` and `test_header_and_yield_changes.py` with
  an explicit assertion that the gauge value equals
  `yield_projection.projected.iloc[-1]`.
- **Found and fixed the actual cause of "Yield outlook chart could not
  be rendered... Reason: TypeError: Type is not JSON serializable:
  Timestamp"**: the "today" and "maturity" point markers on the yield
  detail chart were built with `x=[some_timestamp_index_value]` — a bare
  `pandas.Timestamp` object sitting inside a plain Python list, rather
  than as part of a `pandas.Series`/`DatetimeIndex` (which Plotly does
  know how to normalise before serialisation). This is fine for Plotly's
  interactive renderer but fails under kaleido's stricter JSON encoder
  (confirmed by reproducing the exact same error message directly via
  `orjson.dumps({"x": [pd.Timestamp(...)]})`, which is the underlying
  library kaleido 1.x's `choreographer` module uses). This explains why
  the five small gauge bars rendered fine while the more complex yield
  chart failed — the gauge bars never built marker traces this way.
  Fixed in `gauge_utils.py::make_yield_projection_figure` by converting
  both marker x-values to `.isoformat()` strings before passing them to
  Plotly. Confirmed fixed via a regression test in
  `test_header_and_yield_changes.py` that inspects the figure's raw
  dict representation and asserts both marker x-values are plain
  strings, not Timestamp objects. The earlier retry logic in
  `_fig_to_png_bytes` is left in place as a defensive measure for
  genuinely transient subprocess failures, but this specific recurring
  error was deterministic, not transient — retries alone would not have
  fixed it, which is why finding and fixing the actual root cause
  mattered here.

## Bug fixes + chart embedding (earlier round)

- **Dates section month dropdown truncation**: "Oct", "Apr", "Nov" etc.
  were being clipped to "O..", "A..", "N.." since the dates row was
  constrained too narrowly (60% of container width) and the day/month
  column split inside each group left too little room for the month
  selectbox. Fixed by widening the dates row to ~83% of the container
  and rebalancing the inner day/month ratio from 1:1.3 to 1:1.6. Also
  added a defensive CSS rule (`core/styles.py`) giving the three
  date-month selectboxes a guaranteed minimum width via
  `st.container(key=...)` wrappers (confirmed against Streamlit 1.58's
  documented `st-key-{name}` class-naming behavior), so they can't
  truncate again even on a narrower viewport than tested here.
- **"Download summary" now embeds charts, not just a table.** The five
  gauge bars (as shown on screen) and the detailed yield outlook
  10-90%ile plume chart are now embedded as images in the Word
  document, in addition to the existing setup/results tables.
  Plotly figures are exported to PNG via kaleido
  (`fig.to_image(...)`) before embedding, since Word documents can't
  contain interactive charts.
  **Important dependency note:** kaleido's newer major version (1.x)
  requires a separately installed system Chrome/Chromium to render
  images — if that's missing, image export fails entirely. This
  project pins `kaleido==0.2.1` instead, which bundles its own
  Chromium inside the package, avoiding that external dependency
  (kaleido 0.2.1 is a large wheel, ~80MB, for this reason). If image
  embedding ever silently stops working after a `pip install` upgrade,
  check whether `kaleido` got bumped past 0.2.x and re-pin it.
  Image export failures are caught per-chart (one broken chart doesn't
  take down the rest of the document) and surfaced as a clear warning
  in the app after download, listing exactly which chart(s) couldn't
  be rendered and why — rather than silently producing a docx missing
  some or all of its images with no explanation. `build_summary_docx`
  now returns `(docx_bytes, warnings)` rather than bare bytes; any code
  calling it directly needs updating for the new signature (see
  `test_summary_doc.py` for example usage covering both the
  no-images and with-images cases).

## Setup panel redesign + working download (earlier round)

- **Dates section**: each of Fallow start / Plant / Harvest now has its
  label sitting directly above its own bordered box (not below, as
  captions previously were), and the three groups are visually
  distinct — each is its own small bordered container rather than six
  flat, equal-width columns that read as one undifferentiated row. The
  whole dates row is also now constrained to roughly 60% of the
  container width rather than stretching edge-to-edge, so the boxes
  read as compact day/month pairs rather than oversized inputs.
- **WUE and threshold water** now use integer number inputs (`min_value=0,
  value=25/120, step=1/5`) instead of floats, so they display as `25`
  and `120` rather than `25.00` and `120.00`.
- **"Download summary" now actually works.** It was previously a
  non-functional `st.button` stub with no click handler — clicking it
  did nothing and produced no file, which is why it couldn't be found.
  It's now a real `st.download_button` wired to
  `core/summary_doc.py::build_summary_docx`, which generates an actual
  Word document (.docx, via `python-docx`) containing the setup inputs
  (site, soil, dates, WUE, threshold water) and a table of the five
  gauge results (value, unit, plain-language band descriptor, or "not
  yet relevant" / "need more history" as appropriate), built fresh from
  the live `MetricResult` objects each time the page renders. Validated
  by round-tripping through python-docx and also converting to PDF via
  LibreOffice to confirm the underlying XML is genuinely well-formed,
  not just readable by a lenient parser — see
  `test_summary_doc.py`.
  Note: `python-docx` (a Python library for runtime document
  generation) is a different tool from the Node.js `docx`/docx-js
  tooling used elsewhere for Claude's own static document-authoring
  skill — this document needs to be built live inside the running app
  from that moment's gauge values, which is a different use case.
- **`python-docx` import is now wrapped defensively.** If the package
  isn't installed (e.g. `pip install -r requirements.txt` hasn't been
  run yet, or was run against a different Python/pip than the one
  Streamlit is using), the app no longer crashes entirely at startup
  with a raw `ModuleNotFoundError` traceback. Instead, every other
  feature works normally, and only the "Download summary" button shows
  a clear, actionable message explaining exactly what to run to fix it.
  Confirmed working by running the app inside a separate virtual
  environment with every dependency installed EXCEPT `python-docx`.

## Known limitations / next steps

- **Soil water at planting**: currently uses the fallow water balance
  result *as of today*, not as of the actual planting date. Once the
  fallow period genuinely ends at planting (not "today"), this should
  be split into two windows: fallow (start → plant) and in-crop
  (plant → today), with soil water at planting read from the end of
  the fallow window specifically.
- **Photothermal index** is a simple seasonal mean PTQ — it isn't yet
  flagged against a specific growth stage (e.g. flowering window),
  which is where PTQ is most agronomically meaningful for grain set.
- **Nitrogen model units**: the original C# `TotalN` accumulator's
  units weren't fully disambiguated from the source file alone (see
  `core/nitrogen.py` docstring) — worth checking the absolute values
  against a known CliMate/HowLeaky result before trusting them as
  kg N/ha. The percentile ranking is more robust than the absolute
  number, since model units cancel out in a same-engine comparison.
- **Crop cover/root depth** are currently fixed in the fallow window
  (bare fallow assumption, `total_cover=0.1`, no transpiration) — fine
  for the fallow leg, but the in-crop period doesn't yet model canopy
  development, which would matter for an in-season water balance.
- "Download chart" button is still a placeholder.
- Live SILO connectivity could not be tested from the sandbox this was
  built in (network egress there is restricted to package registries).
  `core/silo.py` is an unmodified copy of your working module, so it
  should connect fine locally — but this is the one part that
  genuinely needs your live test.

## Running locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploying to Streamlit Community Cloud

1. Push this repo to GitHub (e.g. `David-Freebairn/Yieldrisk`)
2. Go to share.streamlit.io → New app → select the repo, branch `main`, file `app.py`
3. All dependencies in `requirements.txt` are installed automatically by Streamlit Cloud
4. Note: `kaleido==0.2.1` is pinned deliberately — it bundles its own Chromium for chart
   image export in the "Download summary" Word document. Do not upgrade to kaleido>=1.0
   without also ensuring Chrome is available in the deployment environment.

## Files

```
app.py                      # main Streamlit app / layout
gauge_utils.py               # gauge bar + detail chart rendering
core/
  silo.py                    # SILO fetch/cache (unmodified from RiskAware)
  soil_xml.py                # HowLeaky .soil XML reader (extended for N chemistry)
  soil.py                    # SoilLayer/SoilProfile dataclasses + init_sw
                              #   (reconstructed — original RiskAware core/soil.py
                              #    also has a .PRM reader not included here)
  styles.py                  # shared CSS + station persistence (unmodified)
  waterbalance.py             # PERFECT water balance engine (unmodified)
  nitrogen.py                 # HowWetN mineralisation, ported from C# (see above)
  crop_metrics.py              # PTQ + yield outlook calculations
  season_metrics.py            # calendar-aligned historical series + percentile
  dashboard_metrics.py          # orchestrates all 5 metrics for the dashboard
data/
  *.xml                       # 12 HowLeaky soil profiles
test_metrics_pipeline.py      # synthetic end-to-end test of all 4 metric pipelines
test_app_integration.py       # synthetic test simulating app.py's full data flow
```
