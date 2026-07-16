"""
enso_iod_module.py
-------------------
Fetches current ENSO (ONI) and IOD (DMI) state.
These are GLOBAL monthly indices — not location-specific — so this module
is intentionally separate from weather_module.py and cached daily.

ONI  : Oceanic Nino Index. >=+0.5 El Nino, <=-0.5 La Nina, else Neutral.
       Source: NOAA PSL, free, no key, plain text, updated monthly.
DMI  : Dipole Mode Index (Indian Ocean Dipole). >=+0.4 Positive IOD,
       <=-0.4 Negative IOD, else Neutral.
       Source: NOAA PSL, free, no key, plain text, updated monthly.

These are used as DIRECT FEATURES (not an ML model) to adjust the
seasonal climatology in weather_module.py — a documented, published
statistical relationship, not a trained black box.
"""

import httpx
import asyncio
import logging
from datetime import date
from functools import lru_cache

logger = logging.getLogger(__name__)

ONI_URL = "https://psl.noaa.gov/data/correlation/oni.data"
DMI_URL = "https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data"

TIMEOUT_SECONDS = 3.0  # these are small text files, but PSL can be slow
MISSING_FLAGS = (-99.9, -99.99, -999.0)

# NOAA PSL returns 403 without a browser-like User-Agent
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
          "jul", "aug", "sep", "oct", "nov", "dec"]


# ---------------------------------------------------------------------------
# Generic PSL fixed-format parser
# ---------------------------------------------------------------------------

def _parse_psl_format(text: str) -> dict[int, list[float]]:
    """
    PSL time-series files look like:
        1950  2026          <- start/end year (first line, ignore)
        1950  -1.68 -1.15 ... (12 monthly values)
        1951   0.42  0.38 ...
        ...
        -99.99                <- footer / missing-value legend, stop here
    Returns {year: [12 monthly values]}, missing values as None.
    """
    result = {}
    lines = text.strip().splitlines()

    for line in lines[1:]:  # skip first line (start/end year header)
        tokens = line.split()
        if len(tokens) != 13:
            continue  # footer lines, metadata, blank lines
        try:
            year = int(tokens[0])
        except ValueError:
            continue
        if year < 1900 or year > 2100:
            continue

        try:
            values = [float(t) for t in tokens[1:]]
        except ValueError:
            continue

        values = [None if any(abs(v - m) < 0.01 for m in MISSING_FLAGS) else v for v in values]
        result[year] = values

    return result


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

async def _fetch_oni() -> dict[int, list[float]]:
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, headers=_HEADERS) as client:
        r = await client.get(ONI_URL)
        r.raise_for_status()
        return _parse_psl_format(r.text)


async def _fetch_dmi() -> dict[int, list[float]]:
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, headers=_HEADERS) as client:
        r = await client.get(DMI_URL)
        r.raise_for_status()
        return _parse_psl_format(r.text)


def _latest_value(series: dict[int, list[float]]) -> tuple[float, int, int] | None:
    """Returns (value, year, month_1indexed) of the most recent non-null entry."""
    for year in sorted(series.keys(), reverse=True):
        months = series[year]
        for m in range(11, -1, -1):
            if months[m] is not None:
                return months[m], year, m + 1
    return None


# ---------------------------------------------------------------------------
# Classification (published thresholds — not derived from training data)
# ---------------------------------------------------------------------------

def _classify_oni(value: float) -> str:
    if value >= 0.5:
        return "el_nino"
    elif value <= -0.5:
        return "la_nina"
    return "neutral"


def _classify_dmi(value: float) -> str:
    if value >= 0.4:
        return "positive_iod"
    elif value <= -0.4:
        return "negative_iod"
    return "neutral"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_cache = {"data": None, "fetched_on": None}


async def get_enso_iod_state(force_refresh: bool = False) -> dict:
    """
    Returns current ENSO and IOD state. Cached per calendar day since
    these indices update monthly at most — no need to hit NOAA per farmer query.
    """
    today = date.today()
    if not force_refresh and _cache["data"] is not None and _cache["fetched_on"] == today:
        return _cache["data"]

    oni_state = "unknown"
    oni_value = None
    dmi_state = "unknown"
    dmi_value = None
    source_ok = True

    try:
        oni_series = await _fetch_oni()
        latest = _latest_value(oni_series)
        if latest:
            oni_value, oni_year, oni_month = latest
            oni_state = _classify_oni(oni_value)
    except Exception as e:
        logger.warning(f"[enso_iod] ONI fetch failed: {e}")
        source_ok = False

    try:
        dmi_series = await _fetch_dmi()
        latest = _latest_value(dmi_series)
        if latest:
            dmi_value, dmi_year, dmi_month = latest
            dmi_state = _classify_dmi(dmi_value)
    except Exception as e:
        logger.warning(f"[enso_iod] DMI fetch failed: {e}")
        source_ok = False

    result = {
        "oni_value": round(oni_value, 2) if oni_value is not None else None,
        "oni_phase": oni_state,
        "dmi_value": round(dmi_value, 2) if dmi_value is not None else None,
        "dmi_phase": dmi_state,
        "source_ok": source_ok,
        "as_of": today.isoformat(),
    }

    _cache["data"] = result
    _cache["fetched_on"] = today
    return result


# ---------------------------------------------------------------------------
# Monsoon rainfall adjustment matrix — direct feature lookup, not ML
# ---------------------------------------------------------------------------
# Published climatological relationships (IITM Pune / IMD research):
# El Nino years -> below-normal Indian monsoon (JJAS), roughly -8% to -15%
# La Nina years -> above-normal monsoon, roughly +5% to +10%
# Positive IOD offsets/counters El Nino's drying effect on Indian monsoon
# Negative IOD compounds El Nino's drying effect
# These adjustments only apply to monsoon-season months (Jun-Oct) for
# Maharashtra; rabi-season months are governed by different teleconnections
# and are left unadjusted (multiplier 1.0) in this version.

MONSOON_ADJUSTMENT_MATRIX = {
    ("el_nino", "positive_iod"): 0.97,   # IOD offsets most of the El Nino drying
    ("el_nino", "neutral"):      0.90,   # standard El Nino deficit
    ("el_nino", "negative_iod"): 0.82,   # compounded drying — highest drought risk
    ("la_nina", "positive_iod"): 1.12,
    ("la_nina", "neutral"):      1.07,
    ("la_nina", "negative_iod"): 1.02,
    ("neutral", "positive_iod"): 1.05,
    ("neutral", "neutral"):      1.00,
    ("neutral", "negative_iod"): 0.95,
}

MONSOON_MONTHS = {6, 7, 8, 9, 10}  # June - October


def get_monthly_adjustment_factor(oni_phase: str, dmi_phase: str, month: int) -> float:
    """
    Returns a multiplier to apply to climatological monthly rainfall.
    Outside monsoon months, returns 1.0 (no adjustment — different drivers apply).
    """
    if month not in MONSOON_MONTHS:
        return 1.0
    return MONSOON_ADJUSTMENT_MATRIX.get((oni_phase, dmi_phase), 1.0)


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    async def _test():
        state = await get_enso_iod_state(force_refresh=True)
        import json
        print(json.dumps(state, indent=2))
        factor = get_monthly_adjustment_factor(state["oni_phase"], state["dmi_phase"], 8)
        print(f"August adjustment factor: {factor}")

    asyncio.run(_test())