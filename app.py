"""
Season Tracker — local prototype, real-data version

Mimics the "Fallow and crop setup" + "How are we going?" mockup, now wired
to real RiskAware logic:
  - Site search via core.silo (SILO Patched Point API)
  - Soil selection via core.soil_xml (HowLeaky .soil XML files, data/)
  - Fallow water gain    -> core.waterbalance (PERFECT engine, ported as-is)
  - Fallow nitrogen gain -> core.nitrogen (HowWetN mineralisation, ported
                             from DHM's CliMate engine with permission)
  - In-crop rain         -> calendar-aligned cumulative rainfall
  - Photothermal index   -> PTQ = solar radiation / mean temperature
  - Crop yield outlook   -> (soil water at planting + in-crop rain to date
                             - threshold water) * WUE

Each metric's gauge marker is a percentile rank of the current season vs.
comparable historical years, computed using the SAME engine for every
year (not just a raw climate percentile) — see core/dashboard_metrics.py.
"""

import os
import sys
from pathlib import Path

# Make sure this script's own directory is on sys.path BEFORE any "core.*"
# imports, regardless of the working directory Streamlit was launched from.
# Using os.path.abspath(__file__) rather than Path(__file__).resolve() as
# a belt-and-braces measure against edge cases with symlinks/cwd on some
# platforms.
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

if not (Path(_APP_DIR) / "core" / "__init__.py").exists():
    raise RuntimeError(
        f"Could not find core/__init__.py next to app.py (looked in {_APP_DIR}/core).\n"
        "This usually means the 'core' folder didn't end up in the same directory "
        "as app.py after unzipping — check that app.py, gauge_utils.py, core/, and "
        "data/ are all siblings in the same folder, then run streamlit from that "
        "folder, e.g.:\n"
        f"  cd {_APP_DIR}\n"
        "  streamlit run app.py"
    )

import datetime as dt
from pathlib import Path as P

import numpy as np
import pandas as pd
import streamlit as st

from core.silo import search_stations, ensure_climate_cached
from core.soil_xml import read_soil_xml
from core.styles import apply_styles, save_station, load_station
from core.dashboard_metrics import (
    compute_fallow_water_and_n_gain,
    compute_in_crop_rain,
    compute_photothermal_index,
    compute_crop_expectation_from_projection,
    compute_yield_projection,
    MetricResult,
)
from gauge_utils import make_gauge_bar_figure, make_detail_figure, make_yield_projection_figure

try:
    from core.summary_doc import build_summary_docx
    _SUMMARY_DOC_AVAILABLE = True
    _SUMMARY_DOC_IMPORT_ERROR = None
except ModuleNotFoundError as e:
    # python-docx isn't installed. Don't crash the whole app over a single
    # feature — fall through and show a clear, actionable message only when
    # the user actually reaches the "Download summary" button instead.
    build_summary_docx = None
    _SUMMARY_DOC_AVAILABLE = False
    _SUMMARY_DOC_IMPORT_ERROR = str(e)

st.set_page_config(page_title="Yieldrisk", layout="wide")
apply_styles()

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"

GAUGE_COLORS = {
    "fallow_water": ("#c9c9c9", "#1f6fb4"),
    "fallow_nitrogen": ("#cfe8c9", "#256b1f"),
    "in_crop_rain": ("#dbeeff", "#0b3d6b"),
    "photothermal": ("#e8d9b0", "#e0a200"),
    "crop_expectation": ("#eafce6", "#1e7a1e"),
}

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@st.cache_data(ttl=3600, show_spinner=False)
def _search(query: str):
    return search_stations(query)


def load_soil_files():
    files = sorted(DATA_DIR.glob("*.xml")) + sorted(DATA_DIR.glob("*.soil"))
    return files


# ---------------------------------------------------------------------------
# TITLE + SUBHEADING + INFORMATION BUTTON
# ---------------------------------------------------------------------------
st.markdown(
    "<h1 style='color:#1f6fb4; margin-bottom:0;'>Yieldrisk</h1>"
    "<p style='color:#1f6fb4; font-size:1.05rem; margin-top:0.1em; margin-bottom:0.6em;'>"
    "following soil water and nitrogen gains in a fallow and crop prospects through the season"
    "</p>",
    unsafe_allow_html=True,
)

if "show_info" not in st.session_state:
    st.session_state["show_info"] = False

info_col = st.columns([1, 2, 1])[1]
with info_col:
    if st.button("ℹ️ Information", key="info_btn", width="stretch"):
        st.session_state["show_info"] = not st.session_state["show_info"]

if st.session_state["show_info"]:
    st.info(
        "**About Yieldrisk**\n\n"
        "Yieldrisk follows how a fallow and crop are progressing against "
        "the historical record at the same site and on the same soil. Pick a "
        "soil type, set your fallow start, plant and harvest dates, and enter "
        "your crop's water-use efficiency (WUE) and threshold water, then "
        "select a weather station to pull daily climate data from SILO "
        "(1996 onwards).\n\n"
        "**Fallow water gain** and **fallow nitrogen gain** are simulated using "
        "a daily soil water balance (the PERFECT model) and a nitrogen "
        "mineralisation model, run from your fallow start date to your plant "
        "date.\n\n"
        "**In-crop rain** is cumulative rainfall since planting. "
        "**Photothermal quotient** is cumulative solar radiation divided by "
        "mean temperature since planting — higher values generally favour "
        "grain set. **Crop yield outlook** combines soil water at planting, "
        "in-crop rain, your threshold water and WUE into a simple potential "
        "yield estimate.\n\n"
        "Each gauge bar shows this season's value against a band built from "
        "comparable historical years at the same site, soil and dates."
    )

# ---------------------------------------------------------------------------
# SETUP PANEL — soil, dates, crop, then site (site moved to bottom to avoid
# blocking the rest of the form while the climate data download is pending)
# ---------------------------------------------------------------------------
if "reset_station" not in st.session_state:
    st.session_state["reset_station"] = False
if st.session_state.pop("reset_station", False):
    st.session_state["confirmed"] = False
    st.session_state["stations"] = []
    st.session_state["chosen"] = None
    st.session_state["last_query"] = ""
    st.session_state["query"] = ""
    st.session_state["climate_ready"] = False
    st.session_state.pop("climate_df", None)
    st.session_state.pop("climate_key", None)

with st.container(border=True):
    st.markdown('<p class="section-title">Soil type</p>', unsafe_allow_html=True)
    soil_files = load_soil_files()
    soil_labels = [f.stem.replace("_", " ") for f in soil_files]
    if soil_labels:
        soil_idx = st.selectbox(
            "soil", range(len(soil_labels)), format_func=lambda i: soil_labels[i],
            label_visibility="collapsed", key="soil_select",
        )
        soil_path = soil_files[soil_idx]
    else:
        st.error(f"No .xml/.soil files found in {DATA_DIR}")
        soil_path = None

    st.markdown("**Dates**")
    dates_row, _dates_spacer = st.columns([5, 1])
    with dates_row:
        date_group1, date_group2, date_group3 = st.columns(3)

        with date_group1:
            st.markdown(
                "<p style='font-weight:600; color:#1A5276; margin-bottom:0.2rem;'>Fallow start</p>",
                unsafe_allow_html=True,
            )
            with st.container(border=True):
                g1a, g1b = st.columns([1, 1.6])
                with g1a:
                    start_day = st.number_input(
                        "Start day", 1, 31, 1, label_visibility="collapsed",
                        key="start_day", format="%d",
                    )
                with g1b:
                    with st.container(key="month_start_wrap"):
                        start_month = st.selectbox(
                            "Start month", MONTH_NAMES, index=0,
                            label_visibility="collapsed", key="start_month",
                        )

        with date_group2:
            st.markdown(
                "<p style='font-weight:600; color:#1A5276; margin-bottom:0.2rem;'>Plant</p>",
                unsafe_allow_html=True,
            )
            with st.container(border=True):
                g2a, g2b = st.columns([1, 1.6])
                with g2a:
                    plant_day = st.number_input(
                        "Plant day", 1, 31, 1, label_visibility="collapsed",
                        key="plant_day", format="%d",
                    )
                with g2b:
                    with st.container(key="month_plant_wrap"):
                        plant_month = st.selectbox(
                            "Plant month", MONTH_NAMES, index=2,
                            label_visibility="collapsed", key="plant_month",
                        )

        with date_group3:
            st.markdown(
                "<p style='font-weight:600; color:#1A5276; margin-bottom:0.2rem;'>Harvest</p>",
                unsafe_allow_html=True,
            )
            with st.container(border=True):
                g3a, g3b = st.columns([1, 1.6])
                with g3a:
                    harvest_day = st.number_input(
                        "Harvest day", 1, 31, 1, label_visibility="collapsed",
                        key="harvest_day", format="%d",
                    )
                with g3b:
                    with st.container(key="month_harvest_wrap"):
                        harvest_month = st.selectbox(
                            "Harvest month", MONTH_NAMES, index=10,
                            label_visibility="collapsed", key="harvest_month",
                        )

    st.markdown("**Crop**")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        wue = st.number_input(
            "WUE (kg/ha/mm)", min_value=0, value=25, step=1, key="wue",
        )
    with c3:
        threshold_water = st.number_input(
            "Threshold water (mm)", min_value=0, value=120, step=5, key="threshold_water",
        )

    st.markdown('<p class="section-title">Select site</p>', unsafe_allow_html=True)
    confirmed = st.session_state.get("confirmed", False)
    station_info = None

    # Render the entire site-selection area inside a single st.empty()
    # placeholder, rebuilt fresh every run. This guarantees the "confirmed"
    # view (green banner + downloading message) and the "searching" view
    # (text input / radio list / Select button) can never both be visible
    # at once, even transiently — st.empty() fully replaces its previous
    # contents on every render rather than relying on Streamlit's normal
    # element-diffing across the if/else branches, which is what allowed
    # the stale radio list to bleed through after confirmation.
    site_area = st.empty()
    with site_area.container():
        if not confirmed:
            query = st.text_input(
                "station", label_visibility="collapsed",
                placeholder="Search station — e.g. Dalby, Emerald  (press Enter)",
                key="query",
            )
            if query and len(query) >= 3:
                if st.session_state.get("last_query") != query:
                    with st.spinner("Searching..."):
                        try:
                            st.session_state["stations"] = _search(query)
                        except Exception as e:
                            st.error(f"Search failed: {e}")
                            st.session_state["stations"] = []
                    st.session_state["last_query"] = query
                    st.session_state.pop("climate_df", None)
                    st.session_state.pop("climate_key", None)
                    st.session_state["climate_ready"] = False

                stations = st.session_state.get("stations", [])
                if stations:
                    labels = [s["label"] for s in stations]
                    if len(labels) == 1:
                        st.session_state["chosen"] = labels[0]
                        st.session_state["confirmed"] = True
                        st.session_state["climate_ready"] = False
                        site_area.empty()
                        st.rerun()
                    else:
                        st.caption(f"**{len(labels)} stations found** — select one:")
                        chosen = st.radio("Station", options=labels, label_visibility="collapsed", key="station_radio")
                        if st.button("Select"):
                            st.session_state["chosen"] = chosen
                            st.session_state["confirmed"] = True
                            st.session_state["stations"] = [s for s in stations if s["label"] == chosen]
                            st.session_state["climate_ready"] = False
                            site_area.empty()
                            st.rerun()
                elif st.session_state.get("last_query"):
                    st.warning("No stations found. Try a shorter search term.")
        else:
            chosen = st.session_state.get("chosen", "")
            stations = st.session_state.get("stations", [])
            c1, c2 = st.columns([5, 1.4])
            with c1:
                st.success(f"📍 {chosen}")
            with c2:
                if st.button("Change", width="stretch"):
                    st.session_state["reset_station"] = True
                    site_area.empty()
                    st.rerun()
            station_info = next((s for s in stations if s["label"] == chosen), None)
            if station_info:
                save_station(station_info)
            if not st.session_state.get("climate_ready", False):
                st.warning("⏳ Downloading 30 years of daily data may take 30-60 seconds. Please wait!")


# ---------------------------------------------------------------------------
# "How are we going as of [date] ?" — today's date + gauge stack
# ---------------------------------------------------------------------------
st.markdown(
    "<h1 style='color:#1f6fb4; margin-top:1em; margin-bottom:0.3em;'>How are we going as of</h1>",
    unsafe_allow_html=True,
)
header_cols = st.columns([1, 1, 0.7, 7])
with header_cols[0]:
    today_day = st.number_input("Today's day", 1, 31, dt.date.today().day, label_visibility="collapsed", key="today_day")
with header_cols[1]:
    today_month = st.selectbox(
        "Today's month", MONTH_NAMES, index=dt.date.today().month - 1,
        label_visibility="collapsed", key="today_month",
    )
with header_cols[2]:
    if st.button("❓", key="gauge_help_btn"):
        st.session_state["show_gauge_help"] = not st.session_state.get("show_gauge_help", False)

if st.session_state.get("show_gauge_help", False):
    st.info(
        "**Reading the gauges below**\n\n"
        "Each bar shows this season's value as a marker on a gradient built "
        "from comparable historical years (1996 onwards) at this site, soil "
        "and dates. The text next to the value is a plain-language band: "
        "**low** (bottom 25% of years), **below average** (25-45th "
        "percentile), **average** (45-55th percentile), **above average** "
        "(55-75th percentile), or **high** (top 25% of years). "
        "Click **Graph** on any bar to see this season's trajectory against "
        "the historical spread in detail."
    )

if not station_info or not soil_path:
    st.info("Select a site and confirm a soil type above to see the dashboard.")
    st.stop()

month_idx = MONTH_NAMES.index(today_month) + 1
try:
    today = dt.date(dt.date.today().year, month_idx, today_day)
except ValueError:
    st.error("Invalid today's date.")
    st.stop()

fallow_start_md = (MONTH_NAMES.index(start_month) + 1, start_day)
plant_md = (MONTH_NAMES.index(plant_month) + 1, plant_day)
harvest_md = (MONTH_NAMES.index(harvest_month) + 1, harvest_day)

# ── Fetch climate + soil (cached) ───────────────────────────────────────────
_was_ready_before_fetch = st.session_state.get("climate_ready", False)
with st.spinner("Fetching SILO climate data (first run only — cached after)..."):
    try:
        climate_df = ensure_climate_cached(
            station_id=station_info["id"],
            lat=station_info.get("lat"), lon=station_info.get("lon"),
            session_state=st.session_state,
        )
        st.session_state["climate_ready"] = True
    except Exception as e:
        st.error(f"Could not fetch climate data: {e}")
        st.stop()

# The "downloading" message above (inside the setup box) was already drawn
# earlier in this same script run, before climate_ready flipped to True —
# Streamlit doesn't retroactively remove elements within a run. Force one
# more rerun right after the FIRST successful fetch so the very next pass
# renders with the message correctly suppressed, without needing the user
# to interact with anything else first.
if not _was_ready_before_fetch:
    st.rerun()

profile = read_soil_xml(soil_path)

# ── Compute the five metrics ────────────────────────────────────────────────
water_res, nitrogen_res = compute_fallow_water_and_n_gain(
    climate_df, profile, fallow_start_md, plant_md, today, sw_init_frac=0.05,
)
rain_res = compute_in_crop_rain(climate_df, plant_md, today)
ptq_res = compute_photothermal_index(climate_df, plant_md, today)

soil_water_at_planting = (
    water_res.current_value if water_res.current_value is not None else 0.0
)
yield_projection = compute_yield_projection(
    climate_df, plant_md, harvest_md, today,
    soil_water_at_planting_mm=soil_water_at_planting,
    threshold_water_mm=threshold_water, wue_kg_ha_per_mm=wue,
) if not rain_res.not_yet_applicable else None
yield_res = (
    compute_crop_expectation_from_projection(yield_projection)
    if yield_projection is not None
    else MetricResult("Crop yield outlook", "kg/ha", None, None, 0, {}, today.year, None, not_yet_applicable=True)
)

st.write("")

GAUGES = [
    (water_res, GAUGE_COLORS["fallow_water"]),
    (nitrogen_res, GAUGE_COLORS["fallow_nitrogen"]),
    (rain_res, GAUGE_COLORS["in_crop_rain"]),
    (ptq_res, GAUGE_COLORS["photothermal"]),
    (yield_res, GAUGE_COLORS["crop_expectation"]),
]

if "graph_open" not in st.session_state:
    st.session_state["graph_open"] = {}

YIELD_GAUGE_INDEX = 4

gauge_figures_for_summary = []
yield_detail_fig_for_summary = None

# ── Section labels: Fallow | Crop season ──────────────────────────────────
SECTION_LABELS = {
    0: "🌱 Fallow",
    2: "🌾 Crop season",
}

for i, (result, (color_low, color_high)) in enumerate(GAUGES):
    if i in SECTION_LABELS:
        if i > 0:
            st.write("")   # extra gap between sections
        st.markdown(
            f"<p style='font-size:0.8rem; font-weight:700; color:#1A5276; "
            f"letter-spacing:0.08em; text-transform:uppercase; "
            f"margin-bottom:0.15rem; margin-top:0.1rem;'>"
            f"{SECTION_LABELS[i]}</p>",
            unsafe_allow_html=True,
        )

    bar_col, btn_col = st.columns([10, 1])
    with bar_col:
        fig = make_gauge_bar_figure(result, color_low, color_high)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key=f"gauge_{i}")
        gauge_figures_for_summary.append(fig)
    with btn_col:
        st.write("")
        if st.button("Graph", key=f"graph_btn_{i}"):
            st.session_state["graph_open"][i] = not st.session_state["graph_open"].get(i, False)

    if st.session_state["graph_open"].get(i, False):
        if i == YIELD_GAUGE_INDEX:
            detail_fig = make_yield_projection_figure(yield_projection)
        else:
            detail_fig = make_detail_figure(result)
        st.plotly_chart(detail_fig, width="stretch", config={"displayModeBar": False}, key=f"detail_{i}")

# Context line — anchors the gauges to their inputs without scrolling
# back up to the setup panel
month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
def _fmt(md): return f"{md[1]} {month_names[md[0]-1]}"
st.caption(
    f"📍 {station_info.get('name', station_info.get('label',''))}  ·  "
    f"{profile.name}  ·  "
    f"Fallow {_fmt(fallow_start_md)} → Plant {_fmt(plant_md)} → Harvest {_fmt(harvest_md)}  ·  "
    f"WUE {wue} kg/ha/mm  ·  Threshold {threshold_water} mm"
)

# The yield detail chart is always built fresh for the summary document,
# independent of whether the user has clicked "Graph" to view it on screen
# — the summary should always include it when the metric is applicable,
# per the request to always embed "the five bars plus the detailed yield".
if yield_projection is not None:
    yield_detail_fig_for_summary = make_yield_projection_figure(yield_projection)

st.write("")
dl_col = st.columns(3)[1]
with dl_col:
    if not _SUMMARY_DOC_AVAILABLE:
        st.error(
            "**Download summary** needs the `python-docx` package, which isn't "
            "installed yet. Run `pip install -r requirements.txt` in this "
            "project's folder, then restart the app.\n\n"
            f"(Import error: {_SUMMARY_DOC_IMPORT_ERROR})"
        )
    else:
        try:
            summary_bytes, image_warnings = build_summary_docx(
                today=today,
                station_name=station_info.get("name", station_info.get("label", "")),
                soil_name=profile.name,
                fallow_start_md=fallow_start_md, plant_md=plant_md, harvest_md=harvest_md,
                wue=wue, threshold_water=threshold_water,
                gauge_results=[result for result, _ in GAUGES],
                gauge_figures=gauge_figures_for_summary,
                yield_figure=yield_detail_fig_for_summary,
            )
            st.download_button(
                "📥 Download summary",
                data=summary_bytes,
                file_name=f"season_summary_{station_info.get('id', 'site')}_{today.isoformat()}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                width="stretch",
            )
            if image_warnings:
                st.warning(
                    "The summary downloaded, but one or more charts couldn't be "
                    "included as images (the rest of the document is still "
                    "complete):\n\n"
                    + "\n".join(f"- {w}" for w in image_warnings)
                    + "\n\nThis usually means the `kaleido` chart-export package "
                    "needs reinstalling — try `pip install -r requirements.txt` "
                    "and restart the app."
                )
        except Exception as e:
            st.error(f"Could not build summary document: {e}")

st.caption(
    f"Soil: {profile.name} (PAWC {profile.pawc_total:.0f}mm)  ·  "
    f"Station: {station_info.get('name', '')}  ·  "
    "Fallow water/nitrogen gain covers fallow start → plant date only. "
    "In-crop rain, photothermal quotient and yield outlook only apply from "
    "the plant date onwards. Historical comparisons use 1996 onwards. "
    "Percentiles rank this season's value vs. comparable historical years, "
    "using the same calculation engine for every year."
)
