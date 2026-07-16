"""
weather_endpoint.py (v3)
-------------------------
FastAPI route: POST /weather-risk
x402-avm payment gate: $0.083 USDC on Algorand mainnet

Payment flow (M2M / direct x402):
    Any caller -> sends X-PAYMENT header with USDC tx
    -> GoPlausible facilitator verifies on Algorand
    -> 200 OK with structured JSON

Human farmer flow (via WhatsApp agent):
    Razorpay webhook fires payment.captured
    -> WhatsApp backend calls this endpoint from float wallet
    -> Returns JSON -> WhatsApp agent formats into Marathi

This endpoint does NOT know or care which flow called it.

IMPORTANT - VERIFY BEFORE PRODUCTION:
    Confirm whether PaymentMiddlewareASGI settles the on-chain USDC
    transfer BEFORE or AFTER this route handler runs, and whether it
    only settles on a 2xx response. If settlement happens before the
    handler, a caller sending invalid input (bad lat/lon, malformed
    harvest_date) pays for a request that will always fail. Check the
    x402-avm docs/source for verify-then-settle-on-success semantics
    before relying on the 400 responses below to be "free" for the caller.
"""

import os
import logging
from datetime import date, timedelta
from typing import Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

# x402-avm: pip install "x402-avm[fastapi,avm,extensions]"
from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.avm.exact import ExactAvmServerScheme
# from x402.mechanisms.evm.exact import ExactEvmServerScheme   
# from x402.mechanisms.svm.exact import ExactSvmServerScheme
from x402.schemas import Network
from x402.server import x402ResourceServer

# Our pure data module - no payments, no AI

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).parent / "modules")) # <--- Changed here
from weathermodule import get_weather_risk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config - set via environment variables (Defaults to Mainnet)
# ---------------------------------------------------------------------------
import os
os.environ["ALGOD_TOKEN"] = ""
os.environ["AVM_ALGOD_TOKEN"] = ""
# 1. Your production merchant wallet address (Must be a valid Mainnet address)
AVM_ADDRESS = os.getenv("AVM_ENDPOINT_WALLET", "BRSMWTNWFRW26LU7FQ7CG2KY65P5HTCBXX6QAOIEM35NESQFGWM4KWEYDU")
FACILITATOR_URL = "https://facilitator.goplausible.xyz"

# 2. Mainnet Genesis Hash (Fixed implicit concatenation bug)
AVM_NETWORK: Network = os.getenv(
    "AVM_NETWORK", 
    "algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73ktiC1qzkkit8="
)

# 3. Real USDC on Algorand Mainnet is 31566704 (Fixed duplicate overwrite bug)
USDC_ASA_ID = os.getenv("USDC_ASA_ID", "31566704")

# 4. Price targeted via absolute atomic micro-units (Fixed decimal scaling bug)
WEATHER_PRICE = os.getenv("WEATHER_PRICE_MICRO_USDC", "83000")

MAX_HARVEST_HORIZON_DAYS = 270

# ---------------------------------------------------------------------------
# x402 server setup
# ---------------------------------------------------------------------------

facilitator = HTTPFacilitatorClient(
    FacilitatorConfig(url=FACILITATOR_URL)
)

server = x402ResourceServer(facilitator)
server.register(AVM_NETWORK, ExactAvmServerScheme())
# server.register(EVM_NETWORK, ExactEvmServerScheme())  # NEW: Register Base
# server.register(SVM_NETWORK, ExactSvmServerScheme())

routes: dict[str, RouteConfig] = {
    "POST /weather-risk": RouteConfig(
        accepts=[
            PaymentOption(
                scheme="exact", network=AVM_NETWORK, pay_to=AVM_ADDRESS,
                price=WEATHER_PRICE, extra={"asset": USDC_ASA_ID, "name": "USDC", "decimals": 6}
            ),
            # PaymentOption(
            #     scheme="exact", network=EVM_NETWORK, pay_to=EVM_ADDRESS,
            #     price=WEATHER_PRICE_MICRO_USDC, asset=BASE_USDC_CONTRACT, extra={"name": "USDC", "decimals": 6}
            # ),
            # PaymentOption(
            #     scheme="exact", network=SVM_NETWORK, pay_to=SVM_ADDRESS,
            #     price=WEATHER_PRICE_MICRO_USDC, asset=SOLANA_USDC_MINT, extra={"name": "USDC", "decimals": 6}
            # )
        ],
        description=(
            "Agricultural weather intelligence for Maharashtra farmers. "
            "Returns three horizons in one payload: (1) precise 16-day forecast "
            "with derived signals - next rain date, dry spells, spray windows, "
            "wind risk, GDD accumulation, drone-spray safety windows, pest/disease "
            "risk windows; (2) ECMWF sub-seasonal outlook for weeks 3-4 (when "
            "harvest_date is given); (3) NASA POWER 30-year climatology adjusted "
            "by ENSO/IOD teleconnection state, spanning day 40 through harvest_date. "
            "Response is pure structured data - no language, no advice - for any "
            "calling agent (LLM, DeFi contract, trading algorithm) to interpret."
        ),
        mime_type="application/json",
    ),
}

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AgriIntel Weather Risk API",
    description="Agricultural weather risk endpoint - x402 payment gated, Algorand USDC",
    version="2.0.0",
)

# Add x402 payment middleware (checks X-PAYMENT header before route handler runs)
app.add_middleware(PaymentMiddlewareASGI, server=server, routes=routes)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class WeatherRiskRequest(BaseModel):
    lat: float = Field(
        ..., ge=-90.0, le=90.0,
        description="Latitude (decimal degrees)",
        json_schema_extra={"example": 18.35},
    )
    lon: float = Field(
        ..., ge=-180.0, le=180.0,
        description="Longitude (decimal degrees)",
        json_schema_extra={"example": 77.31},
    )
    crop: Optional[str] = Field(
        "generic",
        description="Crop type (e.g., soybean, cotton, tur, jowar, wheat). Omit for generic weather/drone data.",
    )
    sowing_date: Optional[str] = Field(
        None, description="ISO date YYYY-MM-DD when crop was sown",
        json_schema_extra={"example": "2026-06-20"},
    )
    harvest_date: Optional[str] = Field(
        None,
        description=f"ISO date YYYY-MM-DD for planned harvest. Triggers Horizons 2 & 3. Must be in the future and within {MAX_HARVEST_HORIZON_DAYS} days.",
        json_schema_extra={"example": "2026-10-15"},
    )
    forecast_days: int = Field(16, ge=1, le=16, description="Days of precise forecast (max 16)")

    @field_validator("harvest_date")
    @classmethod
    def validate_harvest_date(cls, v: Optional[str]) -> Optional[str]:
        """
        Defense-in-depth: reject unreasonable harvest_date values at the
        request-validation layer, before get_weather_risk() ever runs.
        Note: if PaymentMiddlewareASGI settles payment before this validator
        runs (verify the library's behavior), this check happens too late
        to save the caller's payment - it only protects server resources.
        """
        if v is None:
            return v
        try:
            h_date = date.fromisoformat(v)
        except ValueError:
            raise ValueError("harvest_date must be in YYYY-MM-DD format")

        if h_date <= date.today():
            raise ValueError("harvest_date must be in the future")

        if (h_date - date.today()).days > MAX_HARVEST_HORIZON_DAYS:
            raise ValueError(
                f"harvest_date too far out - max {MAX_HARVEST_HORIZON_DAYS} days "
                f"({MAX_HARVEST_HORIZON_DAYS // 30} months) ahead, beyond which "
                f"seasonal climatology has no meaningful skill"
            )
        return v


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------

@app.post("/weather-risk",responses={
        402: {
            "description": "Payment Required. A cryptographically signed Algorand transaction proof for $0.083 USDC must be provided in the X-PAYMENT header."
        }
    })
async def weather_risk(request: Request, body: WeatherRiskRequest,):
    """
    Returns a multi-horizon structured weather payload for a given location.

    Payment: $0.083 USDC via x402 header (Algorand mainnet)
    No API key required. No account needed.

    Response is pure data - no language, no advice.
    Build your own presentation layer on top.

    Status codes:
        200 - success (horizon_1 always present; horizon_2/3 present only
              if harvest_date was given, and may individually contain
              their own error_type: DATA_UNAVAILABLE if that horizon's
              external source failed - core forecast still returned)
        400 - VALIDATION error (bad input - lat/lon out of range,
              malformed or unreasonable harvest_date)
        503 - DATA_UNAVAILABLE for horizon_1 - both Open-Meteo and NASA
              POWER fallback failed, no forecast could be produced at all
    """
    result = await get_weather_risk(
        lat=body.lat,
        lon=body.lon,
        crop=body.crop,
        sowing_date=body.sowing_date,
        harvest_date=body.harvest_date,
        forecast_days=body.forecast_days,
    )

    # Top-level error = bad input caught by get_weather_risk's own validation
    if result.get("error"):
        return JSONResponse(status_code=400, content=result)

    # Horizon 1 (core forecast) totally unavailable = genuine service outage
    if result.get("horizon_1_forecast", {}).get("error"):
        return JSONResponse(status_code=503, content=result)

    # Horizon 1 succeeded but Horizon 2/3 partially failed - still 200,
    # since the core paid-for forecast is present, but flag it so the
    # caller (who paid the same price either way) knows the payload
    # is incomplete rather than silently trusting a missing seasonal outlook.
    partial_failures = []
    if result.get("horizon_2_subseasonal", {}).get("error"):
        partial_failures.append("horizon_2_subseasonal")
    if result.get("horizon_3_seasonal", {}).get("error"):
        partial_failures.append("horizon_3_seasonal")

    if partial_failures:
        result["partial_data"] = True
        result["partial_data_reason"] = f"unavailable: {', '.join(partial_failures)}"
    else:
        result["partial_data"] = False

    return result


# ---------------------------------------------------------------------------
# Health check (unpaid - for monitoring)
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "endpoint": "weather-risk", "price_usdc": "0.083"}


# ---------------------------------------------------------------------------
# Discovery endpoint (unpaid - for Bazaar indexing + judges)
# Kept in sync with the actual v2 module output shape.
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    return {
        "name": "AgriIntel Weather Risk API",
        "version": "2.0.0",
        "endpoint": "POST /weather-risk",
        "price": "$0.083 USDC",
        "network": "Algorand mainnet",
        "payment": "x402 (X-PAYMENT header)",
        "coverage": "Maharashtra, India",
        "crops": ["soybean", "cotton", "tur", "jowar", "wheat", "generic"],
        "inputs": {
            "lat": "float, required, -90 to 90",
            "lon": "float, required, -180 to 180",
            "crop": "string, optional, default 'generic'",
            "sowing_date": "YYYY-MM-DD, optional",
            "harvest_date": f"YYYY-MM-DD, optional - triggers horizon 2 & 3, max {MAX_HARVEST_HORIZON_DAYS} days out",
            "forecast_days": "int, optional, 1-16, default 16",
        },
        "outputs": {
            "horizon_1_forecast": {
                "description": "Precise 0-16 day forecast (Open-Meteo, NASA POWER fallback)",
                "crop_stress_risk_level": "LOW | MEDIUM | HIGH",
                "crop_stress_factors": "list[string] - biological threats",
                "operational_risk_level": "LOW | MEDIUM | HIGH",
                "operational_factors": "list[string] - management blockers like wind/rain",
                "next_rain_date": "ISO date | null",
                "next_dry_spell": "dict {start_date, end_date, days} | null",
                "optimal_drone_spray_dates": "list[ISO date] - Delta-T based drone spray safety",
                "pest_disease_risk_windows": "list[str date ranges]",
                "wind_risk_days": "list[ISO date]",
                "heavy_rain_days": "list[int] - day indices",
                "heat_stress_days": "list[int] - day indices",
                "gdd_accumulated_forecast_window": "float | null",
                "growth_stage": "string | null - derived from sowing_date",
                "irrigation_recommended": "bool",
                "net_water_balance_7d": "float",
                "daily_preview": "list - 7-day daily breakdown",
            },
            "horizon_2_subseasonal": {
                "description": "ECMWF sub-seasonal weeks 3-4 outlook (only if harvest_date given)",
                "weekly_outlook": "list[{week, dates, projected_rain_mm, trend}]",
            },
            "horizon_3_seasonal": {
                "description": "NASA POWER 30yr climatology + ENSO/IOD adjustment, day 40 through harvest_date",
                "method": "direct_feature_lookup (published climatological relationship, not ML)",
                "monthly_outlook": "list[{month, rainfall_normal_mm, rainfall_adjusted_mm, rainfall_pct_of_normal}]",
            },
            "enso_iod_state": {
                "oni_phase": "el_nino | la_nina | neutral",
                "dmi_phase": "positive_iod | negative_iod | neutral",
            },
            "days_to_harvest": "int | null",
            "partial_data": "bool - true if horizon_2 or horizon_3 failed but horizon_1 succeeded",
        },
    }


# ---------------------------------------------------------------------------
# Run (dev only - use gunicorn/uvicorn in production)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)