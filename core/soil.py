"""
core/soil.py
============
Soil profile dataclasses shared by core.soil_xml (HowLeaky .soil XML reader)
and core.waterbalance (PERFECT daily water balance engine).

NOTE: reconstructed for the Season Tracker prototype based on the field
usage observed in soil_xml.py and waterbalance.py — the original RiskAware
core/soil.py also contains a .PRM reader (read_prm) which is not needed
here since all RiskAware soils are now in HowLeaky .soil XML format.
If a .PRM file ever needs to be read, read_prm should be reinstated from
the real RiskAware repo rather than re-derived from scratch.
"""

from dataclasses import dataclass, field
from typing import List
import numpy as np


@dataclass
class SoilLayer:
    depth_mm: float          # cumulative depth to bottom of this layer (mm)
    thickness: float         # layer thickness (mm)
    airdry: float            # air-dry water content, fraction of volume
    ll: float                 # lower limit / wilting point, fraction of volume
    dul: float                # drained upper limit / field capacity, fraction of volume
    sat: float                # saturation, fraction of volume
    ksat: float                # saturated hydraulic conductivity (mm/hr)
    ll_mm: float               # water at LL for this layer (mm)
    dul_mm: float              # water at DUL for this layer (mm)
    sat_mm: float              # water at SAT for this layer (mm)
    airdry_mm: float           # water at air-dry for this layer (mm)
    airdry_below_wp: float     # mm of water between LL and air-dry (>= 0)
    pawc: float                 # plant available water capacity for this layer (mm) = dul_mm - ll_mm
    bulk_density: float          # g/cm3


@dataclass
class SoilProfile:
    name: str
    layers: List[SoilLayer]
    cona: float                  # Stage-II soil evap coefficient (mm/day^0.5)
    u: float                      # Stage-I soil evap limit (mm)
    cn2_bare: float                # SCS curve number, bare soil
    cn_cover_reduction: float       # max CN reduction at 100% cover
    cn_tillage_max: float            # max CN reduction from tillage
    cn_roughness_rain: float          # rain (mm) to remove tillage roughness
    musle_k: float                     # USLE/MUSLE soil erodibility K factor
    musle_p: float                      # USLE/MUSLE support practice P factor
    slope_pct: float                     # field slope (%)
    slope_length: float                   # slope length (m)
    rill_ratio: float                      # rill:interrill erosion ratio
    bulk_density: float                     # mean bulk density across layers (g/cm3)
    cracking: bool = False                   # soil cracking enabled
    crack_infil: float = 0.0                  # max infiltration into cracks (mm)
    # Nitrogen mineralisation chemistry (HowWetN engine inputs) — optional,
    # default to 0 so existing soil-water-only callers are unaffected.
    organic_carbon_pct: float = 0.0             # OrganicCarbon, layer 1, %
    carbon_nitrogen_ratio: float = 0.0           # CarbonNitrogenRatio, layer 1
    n_mineralisation_coefficient: float = 0.0     # NitrateMineralisationCoefficient
    total_depth: float = field(default=0.0, init=False)
    pawc_total: float = field(default=0.0, init=False)


def init_sw(profile: SoilProfile, sw_init_frac: float) -> np.ndarray:
    """
    Initialise per-layer soil water (mm) at a given fraction of PAWC above LL.

    sw_init_frac : 0-1, fraction of each layer's PAWC (DUL - LL) to fill
                   above the lower limit. 0.0 = profile at LL (driest),
                   1.0 = profile at DUL (full).

    Returns np.array of soil water (mm) per layer, length = len(profile.layers).
    """
    sw_init_frac = max(0.0, min(1.0, sw_init_frac))
    sw = np.array([
        layer.ll_mm + sw_init_frac * layer.pawc
        for layer in profile.layers
    ])
    return sw
