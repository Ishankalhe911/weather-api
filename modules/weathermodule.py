"""
weather_module.py (v2)
-----------------------
Pure data fetcher and computation engine. No Gemini. No payments.

Returns THREE data horizons in one payload, plus precomputed derived
signals so any calling agent (Gemini, a DeFi contract, a trading algo)
can answer whatever specific question the farmer actually asked without
the endpoint needing to parse natural language intent.

HORIZON 1  (days 0-16)      : Precise daily forecast - Open-Meteo (ECMWF/NOAA)
HORIZON 2  (days 17-40)     : Reserved for IMD extended-range parsing (phase 2)
HORIZON 3  (day 40 -> harvest): Monthly climatology (NASA POWER 30yr) adjusted
                                by ENSO/IOD direct-feature multiplier - NOT an
                                ML model, a published statistical relationship.

Fallback chain per horizon is independent - if one horizon's source fails,
the others are unaffected and still returned.
"""

import httpx
import asyncio
import sys
import math
import pathlib
from datetime import date, timedelta
from typing import Optional
import logging

sys.path.append(str(pathlib.Path(__file__).parent))
from enso_iod_module import get_enso_iod_state, get_monthly_adjustment_factor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
NASA_POWER_DAILY_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
NASA_POWER_CLIMATOLOGY_URL = "https://power.larc.nasa.gov/api/temporal/climatology/point"

TIMEOUT_SECONDS = 1.5
CLIMATOLOGY_TIMEOUT = 3.0

CROP_THRESHOLDS = {
    "soybean": {"max_daily_rain_mm": 50, "min_rain_7d_mm": 20, "max_temp_c": 38, "min_temp_c": 15, "spray_rain_block_mm": 5, "base_temp_gdd": 10},
    "cotton":  {"max_daily_rain_mm": 60, "min_rain_7d_mm": 25, "max_temp_c": 42, "min_temp_c": 15, "spray_rain_block_mm": 5, "base_temp_gdd": 15.5},
    "tur":     {"max_daily_rain_mm": 45, "min_rain_7d_mm": 15, "max_temp_c": 40, "min_temp_c": 12, "spray_rain_block_mm": 5, "base_temp_gdd": 10},
    "jowar":   {"max_daily_rain_mm": 55, "min_rain_7d_mm": 10, "max_temp_c": 40, "min_temp_c": 12, "spray_rain_block_mm": 5, "base_temp_gdd": 10},
    "wheat":   {"max_daily_rain_mm": 30, "min_rain_7d_mm": 10, "max_temp_c": 35, "min_temp_c": 5,  "spray_rain_block_mm": 3, "base_temp_gdd": 4.4},
    "default": {"max_daily_rain_mm": 50, "min_rain_7d_mm": 20, "max_temp_c": 40, "min_temp_c": 12, "spray_rain_block_mm": 5, "base_temp_gdd": 10},
}

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december"
]

MONTH_DAYS = {
    "JAN": 31, "FEB": 28, "MAR": 31, "APR": 30, "MAY": 31, "JUN": 30,
    "JUL": 31, "AUG": 31, "SEP": 30, "OCT": 31, "NOV": 30, "DEC": 31
}

# ---------------------------------------------------------------------------
# HORIZON 1 - Open-Meteo precise forecast (days 0-16)
# ---------------------------------------------------------------------------

async def _fetch_open_meteo(lat: float, lon: float, days: int = 16) -> dict:
    params = {
        "latitude": lat, "longitude": lon,
        "daily": ",".join([
            "precipitation_sum",
            "temperature_2m_max",
            "temperature_2m_min",
            "relative_humidity_2m_max",
            "relative_humidity_2m_min",
            "et0_fao_evapotranspiration",
            "wind_speed_10m_max",
            "weathercode"
        ]),
        "timezone": "auto",
        "forecast_days": days,
    }
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        r = await client.get(OPEN_METEO_URL, params=params)
        r.raise_for_status()
        return r.json()


async def _fetch_nasa_power_recent(lat: float, lon: float) -> dict:
    """Fallback for Horizon 1 if Open-Meteo fails - last 7 days actuals only."""
    end, start = date.today(), date.today() - timedelta(days=7)
    params = {
        "parameters": "PRECTOTCORR,T2M_MAX,T2M_MIN,RH2M,EVPTRNS",
        "community": "AG", "longitude": lon, "latitude": lat,
        "start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"),
        "format": "JSON",
    }
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        r = await client.get(NASA_POWER_DAILY_URL, params=params)
        r.raise_for_status()
        data = r.json()

    props = data["properties"]["parameter"]
    dates = sorted(props["PRECTOTCORR"].keys())

    def _clean_nasa(val):
        return None if val == -999.0 else val

    daily = {
        "time": dates,
        "precipitation_sum": [_clean_nasa(props["PRECTOTCORR"].get(d)) for d in dates],
        "temperature_2m_max": [_clean_nasa(props["T2M_MAX"].get(d)) for d in dates],
        "temperature_2m_min": [_clean_nasa(props["T2M_MIN"].get(d)) for d in dates],
        "relative_humidity_2m_max": [_clean_nasa(props["RH2M"].get(d)) for d in dates],
        "relative_humidity_2m_min": [None] * len(dates),
        "soil_moisture_0_to_1cm": [None] * len(dates),
        "et0_fao_evapotranspiration": [_clean_nasa(props["EVPTRNS"].get(d)) for d in dates],
        "wind_speed_10m_max": [None] * len(dates),
        "weathercode": [None] * len(dates),
    }
    return {"daily": daily}


# ---------------------------------------------------------------------------
# HORIZON 0 & microclimate helpers
# ---------------------------------------------------------------------------

def _calculate_delta_t(t_celsius: float, rh_percent: float) -> float:
    """
    Approximates Delta T (Dry Bulb - Wet Bulb) using Stull's empirical formula.
    Standard Ag limits: 2 to 8 is safe. > 8 is dangerous evaporation.
    """
    if t_celsius is None or rh_percent is None:
        return None

    tw = (t_celsius * math.atan(0.151977 * (rh_percent + 8.313659) ** 0.5) +
          math.atan(t_celsius + rh_percent) - math.atan(rh_percent - 1.676331) +
          0.00391838 * (rh_percent ** (3 / 2)) * math.atan(0.023101 * rh_percent) - 4.686035)

    delta_t = t_celsius - tw
    return round(delta_t, 1)


async def _fetch_season_to_date_rain(lat: float, lon: float) -> float:
    """Accumulated rainfall from June 1st (SW monsoon onset) to today."""
    today = date.today()
    year = today.year if today.month >= 6 else today.year - 1
    start_date = date(year, 6, 1)

    if today <= start_date:
        return 0.0

    params = {
        "parameters": "PRECTOTCORR",
        "community": "AG", "longitude": lon, "latitude": lat,
        "start": start_date.strftime("%Y%m%d"),
        "end": today.strftime("%Y%m%d"),
        "format": "JSON",
    }

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        r = await client.get(NASA_POWER_DAILY_URL, params=params)
        r.raise_for_status()
        data = r.json()

    props = data["properties"]["parameter"]["PRECTOTCORR"]
    total_rain = sum(val for val in props.values() if val != -999.0)
    return round(total_rain, 1)


# ---------------------------------------------------------------------------
# HORIZON 2 - Open-Meteo ECMWF S2S (days 17-35)
# ---------------------------------------------------------------------------

async def _fetch_horizon_2_ecmwf_s2s(lat: float, lon: float) -> dict:
    """
    Fetches days 17-35 sub-seasonal anomaly trends via Open-Meteo's Seasonal API.
    NOTE: model name and daily-array resolution unverified against a live
    response - test this against the real API before trusting the rain[14:21]
    style indexing below.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum,temperature_2m_max",
        "models": "ecmwf_seasonal_ensemble_mean_seamless",
        "timezone": "Asia/Kolkata",
        "forecast_days": 35,
    }

    url = "https://seasonal-api.open-meteo.com/v1/seasonal"

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        r = await client.get(url, params=params)
        if r.status_code == 400:
            logger.error(f"Open-Meteo H2 400 Error Payload: {r.text}")
        r.raise_for_status()
        data = r.json()

    daily = data["daily"]
    times = daily["time"]
    rain = daily["precipitation_sum"]

    week_3_rain = sum(r for r in rain[14:21] if r is not None)
    week_4_rain = sum(r for r in rain[21:28] if r is not None)

    return {
        "source": "ecmwf_seasonal_extended_range",
        "method": "open_meteo_api",
        "valid_window": f"{times[14]} to {times[27]}",
        "weekly_outlook": [
            {
                "week": 3,
                "dates": f"{times[14]} to {times[20]}",
                "projected_rain_mm": round(week_3_rain, 1),
                "trend": "dry_anomaly" if week_3_rain < 15 else "normal_or_wet"
            },
            {
                "week": 4,
                "dates": f"{times[21]} to {times[27]}",
                "projected_rain_mm": round(week_4_rain, 1),
                "trend": "dry_anomaly" if week_4_rain < 15 else "normal_or_wet"
            }
        ]
    }


# ---------------------------------------------------------------------------
# HORIZON 3 - NASA POWER monthly climatology (day 40 -> harvest)
# ---------------------------------------------------------------------------

async def _fetch_nasa_climatology(lat: float, lon: float) -> dict:
    """30-year monthly climatological normals. Static per lat/lon - not cached yet."""
    params = {
        "parameters": "PRECTOTCORR,T2M_MAX,T2M_MIN",
        "community": "AG", "longitude": lon, "latitude": lat,
        "format": "JSON",
    }
    async with httpx.AsyncClient(timeout=CLIMATOLOGY_TIMEOUT) as client:
        r = await client.get(NASA_POWER_CLIMATOLOGY_URL, params=params)
        r.raise_for_status()
        data = r.json()

    props = data["properties"]["parameter"]
    result = {}

    nasa_keys = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                 "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

    for i, month_name in enumerate(MONTH_NAMES):
        month_key = nasa_keys[i]

        raw_precip = props["PRECTOTCORR"].get(month_key)
        raw_tmax = props["T2M_MAX"].get(month_key)
        raw_tmin = props["T2M_MIN"].get(month_key)

        if raw_precip != -999.0 and raw_precip is not None:
            monthly_total_precip = round(raw_precip * MONTH_DAYS[month_key], 1)
        else:
            monthly_total_precip = None

        result[month_name] = {
            "precip_mm_normal": monthly_total_precip,
            "t_max_c_normal": None if raw_tmax == -999.0 else raw_tmax,
            "t_min_c_normal": None if raw_tmin == -999.0 else raw_tmin,
        }
    return result


def _build_seasonal_outlook(
    climatology: dict,
    enso_iod_state: dict,
    start_date: date,
    end_date: date,
) -> list:
    """Month-by-month outlook, day-40 to harvest. Direct feature lookup, not ML."""
    outlook = []
    cursor = date(start_date.year, start_date.month, 1)

    while cursor <= end_date:
        month_name = MONTH_NAMES[cursor.month - 1]
        normal = climatology.get(month_name, {})
        normal_precip = normal.get("precip_mm_normal")

        factor = get_monthly_adjustment_factor(
            enso_iod_state.get("oni_phase", "neutral"),
            enso_iod_state.get("dmi_phase", "neutral"),
            cursor.month,
        )

        adjusted_precip = round(normal_precip * factor, 1) if normal_precip is not None else None
        pct_of_normal = round(factor * 100) if normal_precip is not None else None

        outlook.append({
            "month": month_name,
            "year": cursor.year,
            "rainfall_normal_mm": round(normal_precip, 1) if normal_precip is not None else None,
            "rainfall_adjusted_mm": adjusted_precip,
            "rainfall_pct_of_normal": pct_of_normal,
            "t_max_normal_c": round(normal.get("t_max_c_normal", 0), 1) if normal.get("t_max_c_normal") is not None else None,
            "adjustment_basis": f"ENSO={enso_iod_state.get('oni_phase')}, IOD={enso_iod_state.get('dmi_phase')}" if cursor.month in (6, 7, 8, 9, 10) else "climatology only (outside monsoon)",
        })

        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)

    return outlook


# ---------------------------------------------------------------------------
# Derived signal computation (pure logic - Horizon 1 data only, no I/O)
# ---------------------------------------------------------------------------

def _compute_derived_signals(daily: dict, crop: str, sowing_date: Optional[str]) -> dict:
    safe_crop = (crop or "generic").lower()
    thresh = CROP_THRESHOLDS.get(safe_crop, CROP_THRESHOLDS["default"])

    times = daily.get("time", [])
    rain = daily.get("precipitation_sum", [])
    t_max = daily.get("temperature_2m_max", [])
    t_min = daily.get("temperature_2m_min", [])
    wind = daily.get("wind_speed_10m_max", [])
    et0 = daily.get("et0_fao_evapotranspiration", [])
    rh_max = daily.get("relative_humidity_2m_max", [])
    rh_min = daily.get("relative_humidity_2m_min", [])
    wcode = daily.get("weathercode", [])

    total_rain_mm = sum(r for r in rain if r is not None)
    rain_7d_mm = sum(r for r in rain[:7] if r is not None)
    heavy_rain_days = [i for i, r in enumerate(rain) if r is not None and r > thresh["max_daily_rain_mm"]]
    heat_days = [i for i, t in enumerate(t_max) if t is not None and t > thresh["max_temp_c"]]
    wind_risk_days = [times[i] for i, w in enumerate(wind) if w is not None and w > 20]

    et0_7d_mm = sum(e for e in (et0[:7] if et0 else []) if e is not None)
    net_water_balance_7d = round(rain_7d_mm - et0_7d_mm, 1)

    optimal_drone_days = []
    for i in range(len(rain)):
        if wind and wind[i] is not None and t_max and t_max[i] is not None and rh_min and rh_min[i] is not None:
            delta_t = _calculate_delta_t(t_max[i], rh_min[i])
            if (wind[i] < 15) and (rain[i] is None or rain[i] < 2.0) and (2 <= delta_t <= 8):
                optimal_drone_days.append(times[i])

    pest_risk_windows = []
    if rh_max and len(rh_max) >= 3:
        for i in range(len(rh_max) - 2):
            if all(rh is not None and rh > 85 for rh in rh_max[i:i + 3]) and \
               all(t is not None and 25 <= t <= 32 for t in t_max[i:i + 3]):
                pest_risk_windows.append(f"{times[i]} to {times[i + 2]}")
                break

    next_rain_date = None
    for i, r in enumerate(rain):
        if r is not None and r > 2.0:
            next_rain_date = times[i]
            break

    next_dry_spell = None
    run_start = None
    for i, r in enumerate(rain):
        is_dry = r is not None and r < 1.0
        if is_dry and run_start is None:
            run_start = i
        elif not is_dry and run_start is not None:
            if i - run_start >= 3:
                next_dry_spell = {"start_date": times[run_start], "end_date": times[i - 1], "days": i - run_start}
                break
            run_start = None
    if next_dry_spell is None and run_start is not None and len(rain) - run_start >= 3:
        next_dry_spell = {"start_date": times[run_start], "end_date": times[-1], "days": len(rain) - run_start}

    spray_blocked = [times[i] for i, r in enumerate(rain[:7]) if r is not None and r > thresh["spray_rain_block_mm"]]

    gdd_accumulated = None
    growth_stage = None
    if sowing_date:
        try:
            sown = date.fromisoformat(sowing_date)
            days_since = (date.today() - sown).days
            if days_since < 0: growth_stage = "pre_sowing"
            elif days_since < 15: growth_stage = "germination"
            elif days_since < 35: growth_stage = "vegetative"
            elif days_since < 65: growth_stage = "flowering"
            elif days_since < 90: growth_stage = "pod_fill"
            else: growth_stage = "maturity"

            base_t = thresh["base_temp_gdd"]
            gdd_days = [max(0, ((t_max[i] + t_min[i]) / 2) - base_t)
                        for i in range(len(t_max)) if t_max[i] is not None and t_min[i] is not None]
            gdd_accumulated = round(sum(gdd_days), 1) if gdd_days else None
        except ValueError:
            growth_stage = "unknown"

    crop_stress_factors = []
    operational_factors = []

    if heavy_rain_days:
        crop_stress_factors.append(f"heavy rain on days {[d + 1 for d in heavy_rain_days[:3]]}")
    if heat_days:
        crop_stress_factors.append(f"heat stress on days {[d + 1 for d in heat_days[:3]]}")
    if net_water_balance_7d < -10:
        crop_stress_factors.append(f"severe soil moisture deficit projected ({net_water_balance_7d}mm net balance)")
    if pest_risk_windows:
        crop_stress_factors.append(f"high pest/fungal risk (high RH + warm temps) during {pest_risk_windows}")

    if spray_blocked:
        operational_factors.append(f"manual spray window blocked on {spray_blocked}")
    if wind_risk_days:
        operational_factors.append(f"high wind (spray drift risk) on {wind_risk_days[:3]}")
    if not any(rh_min):
        operational_factors.append("Drone spray safety calculations disabled (missing humidity data in fallback source).")

    crop_stress_risk_level = "HIGH" if len(crop_stress_factors) >= 2 else ("MEDIUM" if crop_stress_factors else "LOW")
    operational_risk_level = "HIGH" if len(operational_factors) >= 2 else ("MEDIUM" if operational_factors else "LOW")

    return {
        "rainfall_total_mm": round(total_rain_mm, 1),
        "rainfall_7d_mm": round(rain_7d_mm, 1),
        "et0_7d_mm": round(et0_7d_mm, 1),
        "net_water_balance_7d": net_water_balance_7d,
        "next_rain_date": next_rain_date,
        "next_dry_spell": next_dry_spell,
        "optimal_drone_spray_dates": optimal_drone_days,
        "wind_risk_days": wind_risk_days,
        "pest_disease_risk_windows": pest_risk_windows,
        "heavy_rain_days": [d + 1 for d in heavy_rain_days],
        "heat_stress_days": [d + 1 for d in heat_days],
        "crop_stress_risk_level": crop_stress_risk_level,
        "crop_stress_factors": crop_stress_factors,
        "operational_risk_level": operational_risk_level,
        "operational_factors": operational_factors,
        "growth_stage": growth_stage,
        "gdd_accumulated_forecast_window": gdd_accumulated,
        "irrigation_recommended": net_water_balance_7d < -5,
        "daily_preview": [
            {
                "date": times[i],
                "rain_mm": rain[i],
                "et0_mm": et0[i] if et0 else None,
                "t_max_c": t_max[i] if t_max else None,
                "t_min_c": t_min[i] if t_min else None,
                "rh_max_pct": rh_max[i] if rh_max else None,
                "rh_min_pct": rh_min[i] if rh_min else None,
                "wind_kmh": wind[i] if wind else None,
                "wcode": wcode[i] if wcode else None,
            }
            for i in range(min(7, len(times)))
        ],
    }


# ---------------------------------------------------------------------------
# Public API - main entry point
# ---------------------------------------------------------------------------

async def get_weather_risk(
    lat: float,
    lon: float,
    crop: Optional[str] = "generic",
    sowing_date: Optional[str] = None,
    harvest_date: Optional[str] = None,
    forecast_days: int = 16,
) -> dict:
    """
    Returns a universal, multi-horizon payload. See BAZAAR_OUTPUT_EXAMPLE
    below for a schema-accurate example of the response shape.
    """

    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return {"error": True, "error_type": "VALIDATION", "error_reason": "Invalid latitude/longitude bounds."}

    days_to_harvest = None
    if harvest_date:
        try:
            h_date = date.fromisoformat(harvest_date)
            if h_date <= date.today():
                return {"error": True, "error_type": "VALIDATION", "error_reason": "harvest_date cannot be in the past."}
            days_to_harvest = (h_date - date.today()).days
        except ValueError:
            return {"error": True, "error_type": "VALIDATION", "error_reason": "Invalid harvest_date format. Use YYYY-MM-DD."}

    result = {
        "error": False,
        "crop": (crop or "generic").lower(),
        "lat": lat, "lon": lon,
        "sowing_date": sowing_date,
        "harvest_date": harvest_date,
        "days_to_harvest": days_to_harvest,
    }

    if harvest_date:
        try:
            season_rain = await _fetch_season_to_date_rain(lat, lon)
            result["season_to_date"] = {
                "monsoon_start": f"{date.today().year if date.today().month >= 6 else date.today().year - 1}-06-01",
                "accumulated_rain_mm": season_rain,
                "agronomic_context": "Compare against Horizon 3 monthly normals to determine regional deficit."
            }
        except Exception as e:
            logger.warning(f"[weather] Season-to-date fetch failed: {e}")
            result["season_to_date"] = {"error": True}
    else:
        result["season_to_date"] = {"note": "harvest_date not provided"}

    h1_source = "open_meteo"
    daily = None
    try:
        data = await _fetch_open_meteo(lat, lon, forecast_days)
        daily = data["daily"]
    except Exception as e:
        logger.warning(f"[weather] open_meteo failed: {e}, trying NASA POWER fallback")
        try:
            fallback = await _fetch_nasa_power_recent(lat, lon)
            daily = fallback["daily"]
            h1_source = "nasa_power_fallback"
        except Exception as e2:
            logger.error(f"[weather] NASA POWER fallback also failed: {e2}")

    if daily is not None:
        signals = _compute_derived_signals(daily, crop, sowing_date)
        signals["source"] = h1_source
        result["horizon_1_forecast"] = signals
    else:
        result["horizon_1_forecast"] = {"error": True, "error_type": "DATA_UNAVAILABLE", "error_reason": "all_sources_unavailable"}

    if harvest_date and days_to_harvest is not None:
        if days_to_harvest > 16:
            try:
                h2_data = await _fetch_horizon_2_ecmwf_s2s(lat, lon)
                result["horizon_2_subseasonal"] = h2_data
            except Exception as e:
                logger.warning(f"[weather] horizon_2 failed: {e}")
                result["horizon_2_subseasonal"] = {"error": True, "error_type": "DATA_UNAVAILABLE", "error_reason": "subseasonal_data_unavailable"}
        else:
            result["horizon_2_subseasonal"] = {"note": "harvest_date within horizon 1 window, sub-seasonal not needed"}
    else:
        result["horizon_2_subseasonal"] = {"note": "harvest_date not provided"}

    if harvest_date:
        try:
            raw_enso_state = await get_enso_iod_state()
            safe_enso_state = dict(raw_enso_state) if raw_enso_state else {}

            # NOTE: enso_iod_module.get_enso_iod_state() already converts
            # missing values to None internally before returning - oni_value/
            # dmi_value can never actually equal these sentinels here. This
            # check is defense-in-depth against a future change in that
            # module, not something that currently fires.
            sentinels = (-999.0, -99.9, -9999.0)
            if safe_enso_state.get("oni_value") in sentinels:
                safe_enso_state["oni_value"] = None
            if safe_enso_state.get("dmi_value") in sentinels:
                safe_enso_state["dmi_value"] = None

            climatology = await _fetch_nasa_climatology(lat, lon)

            start = date.today() + timedelta(days=40)
            end = date.fromisoformat(harvest_date)

            if end > start:
                outlook = _build_seasonal_outlook(climatology, safe_enso_state, start, end)
                result["horizon_3_seasonal"] = {
                    "source": "nasa_power_climatology + enso_iod_adjustment",
                    "method": "direct_feature_lookup",
                    "monthly_outlook": outlook,
                }
            else:
                result["horizon_3_seasonal"] = {"note": "harvest_date within horizon 1/2 window, no seasonal outlook needed"}

            result["enso_iod_state"] = safe_enso_state
        except Exception as e:
            logger.warning(f"[weather] seasonal outlook failed: {e}")
            result["horizon_3_seasonal"] = {"error": True, "error_type": "DATA_UNAVAILABLE", "error_reason": "seasonal_data_unavailable"}
    else:
        result["horizon_3_seasonal"] = {"note": "harvest_date not provided"}
        result["enso_iod_state"] = {"note": "harvest_date not provided"}

    return result


# ---------------------------------------------------------------------------
# Bazaar metadata exports (for x402 endpoint discovery)
# BAZAAR_OUTPUT_EXAMPLE is hand-verified against the actual return shapes of
# _compute_derived_signals and _fetch_horizon_2_ecmwf_s2s - keep it in sync
# whenever those functions change, since this is what other developers and
# agents will read to understand the contract.
# ---------------------------------------------------------------------------

BAZAAR_INPUT_SCHEMA = {
    "properties": {
        "lat": {"type": "number", "minimum": -90, "maximum": 90, "description": "Latitude (decimal degrees)"},
        "lon": {"type": "number", "minimum": -180, "maximum": 180, "description": "Longitude (decimal degrees)"},
        "crop": {"type": "string", "default": "generic", "description": "Crop type (soybean, cotton, tur, jowar, wheat, generic)"},
        "sowing_date": {"type": "string", "format": "date", "description": "ISO date YYYY-MM-DD"},
        "harvest_date": {"type": "string", "format": "date", "description": "ISO date YYYY-MM-DD. Triggers Horizons 2 & 3."},
        "forecast_days": {"type": "integer", "minimum": 1, "maximum": 16, "default": 16},
    },
    "required": ["lat", "lon"],
}

BAZAAR_OUTPUT_EXAMPLE = {
    "crop": "generic",
    "days_to_harvest": 115,
    "partial_data": False,
    "horizon_1_forecast": {
        "rainfall_total_mm": 88.4,
        "rainfall_7d_mm": 32.1,
        "et0_7d_mm": 19.7,
        "net_water_balance_7d": 12.4,
        "crop_stress_risk_level": "LOW",
        "crop_stress_factors": [],
        "operational_risk_level": "MEDIUM",
        "operational_factors": ["high wind (spray drift risk) on ['2026-07-20']"],
        "next_rain_date": "2026-07-22",
        "next_dry_spell": None,
        "optimal_drone_spray_dates": ["2026-07-18", "2026-07-19"],
        "pest_disease_risk_windows": [],
        "wind_risk_days": ["2026-07-20"],
        "heavy_rain_days": [],
        "heat_stress_days": [],
        "gdd_accumulated_forecast_window": 142.5,
        "growth_stage": "vegetative",
        "irrigation_recommended": False,
        "daily_preview": [],
        "source": "open_meteo",
    },
    "horizon_2_subseasonal": {
        "source": "ecmwf_seasonal_extended_range",
        "method": "open_meteo_api",
        "valid_window": "2026-08-01 to 2026-08-14",
        "weekly_outlook": [
            {"week": 3, "dates": "2026-08-01 to 2026-08-07", "projected_rain_mm": 45.0, "trend": "normal_or_wet"},
            {"week": 4, "dates": "2026-08-08 to 2026-08-14", "projected_rain_mm": 8.0, "trend": "dry_anomaly"},
        ],
    },
    "horizon_3_seasonal": {
        "source": "nasa_power_climatology + enso_iod_adjustment",
        "method": "direct_feature_lookup",
        "monthly_outlook": [
            {
                "month": "august", "year": 2026,
                "rainfall_normal_mm": 180.0, "rainfall_adjusted_mm": 198.0,
                "rainfall_pct_of_normal": 110, "t_max_normal_c": 29.4,
                "adjustment_basis": "ENSO=la_nina, IOD=neutral",
            },
        ],
    },
    "enso_iod_state": {"oni_phase": "la_nina", "dmi_phase": "neutral"},
}


if __name__ == "__main__":
    async def _test():
        result = await get_weather_risk(
            lat=18.35, lon=77.31,
            sowing_date="2026-06-20", harvest_date="2026-10-15",
        )
        import json
        print(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(_test())