import json
import time

# Simulate your exact backend payload output
payload = {
  "crop": "generic",
  "lat": 18.35,
  "lon": 77.31,
  "sowing_date": "2026-06-20",
  "harvest_date": "2026-10-15",
  "days_to_harvest": 92,
  "season_to_date": {
    "monsoon_start": "2026-06-01",
    "accumulated_rain_mm": 220.8,
    "agronomic_context": "Compare against Horizon 3 monthly normals to determine regional deficit."
  },
  "horizon_1_forecast": {
    "rainfall_total_mm": 59.5,
    "rainfall_7d_mm": 39.1,
    "et0_7d_mm": 31.6,
    "net_water_balance_7d": 7.5,
    "next_rain_date": "2026-07-17",
    "next_dry_spell": {
      "start_date": "2026-07-22",
      "end_date": "2026-07-25",
      "days": 4
    },
    "optimal_drone_spray_dates": [],
    "wind_risk_days": [
      "2026-07-15",
      "2026-07-18",
      "2026-07-19",
      "2026-07-20",
      "2026-07-21",
      "2026-07-22",
      "2026-07-23",
      "2026-07-24",
      "2026-07-25",
      "2026-07-26",
      "2026-07-27",
      "2026-07-30"
    ],
    "pest_disease_risk_windows": [
      "2026-07-17 to 2026-07-19"
    ],
    "heavy_rain_days": [],
    "heat_stress_days": [],
    "risk_level": "HIGH",
    "risk_factors": [
      "manual spray window blocked on ['2026-07-17', '2026-07-18', '2026-07-19', '2026-07-20']",
      "high wind (spray drift risk) on ['2026-07-15', '2026-07-18', '2026-07-19']",
      "high pest/fungal risk (high RH + warm temps) during ['2026-07-17 to 2026-07-19']"
    ],
    "growth_stage": "vegetative",
    "gdd_accumulated_forecast_window": 274.1,
    "irrigation_recommended": False,
    "daily_preview": [
      {
        "date": "2026-07-15",
        "rain_mm": 0.9,
        "et0_mm": 6.34,
        "t_max_c": 31.6,
        "t_min_c": 24.5,
        "rh_max_pct": 76,
        "rh_min_pct": 46,
        "wind_kmh": 20.1,
        "wcode": 51
      },
      {
        "date": "2026-07-16",
        "rain_mm": 0.8,
        "et0_mm": 5.05,
        "t_max_c": 31.9,
        "t_min_c": 24.2,
        "rh_max_pct": 79,
        "rh_min_pct": 52,
        "wind_kmh": 19.0,
        "wcode": 51
      },
      {
        "date": "2026-07-17",
        "rain_mm": 6.3,
        "et0_mm": 3.74,
        "t_max_c": 31.5,
        "t_min_c": 23.9,
        "rh_max_pct": 89,
        "rh_min_pct": 54,
        "wind_kmh": 19.4,
        "wcode": 80
      },
      {
        "date": "2026-07-18",
        "rain_mm": 7.4,
        "et0_mm": 3.57,
        "t_max_c": 30.4,
        "t_min_c": 23.8,
        "rh_max_pct": 91,
        "rh_min_pct": 59,
        "wind_kmh": 24.1,
        "wcode": 81
      },
      {
        "date": "2026-07-19",
        "rain_mm": 15.9,
        "et0_mm": 3.33,
        "t_max_c": 28.4,
        "t_min_c": 23.8,
        "rh_max_pct": 91,
        "rh_min_pct": 68,
        "wind_kmh": 22.4,
        "wcode": 95
      },
      {
        "date": "2026-07-20",
        "rain_mm": 5.7,
        "et0_mm": 4.4,
        "t_max_c": 29.8,
        "t_min_c": 23.7,
        "rh_max_pct": 88,
        "rh_min_pct": 64,
        "wind_kmh": 24.0,
        "wcode": 53
      },
      {
        "date": "2026-07-21",
        "rain_mm": 2.1,
        "et0_mm": 5.2,
        "t_max_c": 30.4,
        "t_min_c": 23.9,
        "rh_max_pct": 83,
        "rh_min_pct": 59,
        "wind_kmh": 26.2,
        "wcode": 51
      }
    ],
    "source": "open_meteo"
  },
  "horizon_2_subseasonal": {
    "source": "ecmwf_seasonal_extended_range",
    "method": "open_meteo_api",
    "valid_window": "2026-07-29 to 2026-08-11",
    "weekly_outlook": [
      {
        "week": 3,
        "dates": "2026-07-29 to 2026-08-04",
        "projected_rain_mm": 55.6,
        "trend": "normal_or_wet"
      },
      {
        "week": 4,
        "dates": "2026-08-05 to 2026-08-11",
        "projected_rain_mm": 55.2,
        "trend": "normal_or_wet"
      }
    ]
  },
  "horizon_3_seasonal": {
    "source": "nasa_power_climatology + enso_iod_adjustment",
    "method": "direct_feature_lookup",
    "monthly_outlook": [
      {
        "month": "august",
        "year": 2026,
        "rainfall_normal_mm": 6.7,
        "rainfall_adjusted_mm": 5.5,
        "rainfall_pct_of_normal": 82,
        "t_max_normal_c": 36.0,
        "adjustment_basis": "ENSO=el_nino, IOD=negative_iod"
      },
      {
        "month": "september",
        "year": 2026,
        "rainfall_normal_mm": 5.3,
        "rainfall_adjusted_mm": 4.4,
        "rainfall_pct_of_normal": 82,
        "t_max_normal_c": 34.4,
        "adjustment_basis": "ENSO=el_nino, IOD=negative_iod"
      },
      {
        "month": "october",
        "year": 2026,
        "rainfall_normal_mm": 2.3,
        "rainfall_adjusted_mm": 1.9,
        "rainfall_pct_of_normal": 82,
        "t_max_normal_c": 37.0,
        "adjustment_basis": "ENSO=el_nino, IOD=negative_iod"
      }
    ]
  },
  "enso_iod_state": {
    "oni_value": 0.98,
    "oni_phase": "el_nino",
    "dmi_value": None,
    "dmi_phase": "negative_iod",
    "source_ok": True,
    "as_of": "2026-07-15"
  }
}

def run_local_evaluation():
    # If using a local inference tool like Ollama, you can call it via requests
    import requests
    
    # Format the prompt optimized for WhatsApp limits (Short, clear, structured)
    system_prompt = (
        "You are a precise WhatsApp agritech assistant. Summarize the following crop data "
        "into a short, conversational update for a farmer. Use bullet points and clear emojis. "
        "Keep it under 3 sentences. Focus only on critical warnings."
    )
    
    user_prompt = f"Data to process:\n{json.dumps(payload, indent=2)}"
    
    print("Sending payload to local 8B model tier...")
    start_time = time.time()
    
    try:
        response = requests.post(
            "http://localhost:11434/api/generate", # Standard local Ollama port
            json={
                "model": "llama3:8b", # Or mistral:7b
                "prompt": f"{system_prompt}\n\n{user_prompt}",
                "stream": False
            }
        )
        latency = time.time() - start_time
        output_text = response.json().get("response", "")
        
        print("\n=== EVALUATION RESULTS ===")
        print(f"Inference Latency: {latency:.2f} seconds")
        print("--- Model WhatsApp Output ---")
        print(output_text)
        print("=============================")
        
    except requests.exceptions.ConnectionError:
        print("\n[Error] Local inference engine not running. Please start your local model runner first.")

if __name__ == "__main__":
    run_local_evaluation()