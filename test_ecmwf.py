import requests

def test_ecmwf_seasonal():
    url = "https://seasonal-api.open-meteo.com/v1/seasonal"
    params = {
        "latitude": 18.35,
        "longitude": 77.31,
        "daily": "precipitation_sum,temperature_2m_max",
        "models": "ecmwf_seasonal_ensemble_mean_seamless",
        "timezone": "Asia/Kolkata",
        "forecast_days": 35,
    }
    
    print("Pinging Open-Meteo Seasonal API...")
    r = requests.get(url, params=params)
    
    if r.status_code != 200:
        print(f"FAILED! Status: {r.status_code}\nError: {r.text}")
        return
        
    data = r.json()
    daily = data.get("daily", {})
    times = daily.get("time", [])
    
    print("\n=== API RESPONSE SCHEMA ===")
    print(f"Number of daily data points returned: {len(times)}")
    
    if len(times) > 0:
        print(f"Start date (Index 0): {times[0]}")
        print(f"End date (Index {len(times)-1}): {times[-1]}")
        
    if len(times) >= 28:
        print("\n=== HORIZON 2 SLICING CHECK ===")
        print(f"Week 3 maps to Indices 14-20: {times[14]} to {times[20]}")
        print(f"Week 4 maps to Indices 21-27: {times[21]} to {times[27]}")
        print("Status: SLICING IS SAFE ✅")
    else:
        print(f"\n[WARNING] Array is only {len(times)} days long! Slicing [14:21] will fail. ❌")

if __name__ == "__main__":
    test_ecmwf_seasonal()