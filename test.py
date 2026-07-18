import httpx
import base64
import json

def verify_bazaar_metadata():
    url = "https://agrometeorological-api.onrender.com/weather-risk"
    print(f"🔍 Probing Bazaar Metadata for: {url}\n")
    
    # 1. Trigger the 402 header (no payment needed for discovery)
    response = httpx.post(url, json={"lat": 18.35, "lon": 77.31, "crop": "soybean"})
    
    if response.status_code == 402:
        payment_required = response.headers.get("payment-required")
        if payment_required:
            decoded = json.loads(base64.b64decode(payment_required))
            extensions = decoded.get("extensions", {}).get("bazaar", {})
            
            if extensions:
                print("✅ BAZAAR METADATA FOUND:")
                print(json.dumps(extensions, indent=2))
                print("\n✅ STATUS: API is correctly broadcasting discovery metadata.")
            else:
                print("❌ ERROR: No bazaar extensions found in metadata.")
        else:
            print("❌ ERROR: No 'payment-required' header found.")
    else:
        print(f"Status Code: {response.status_code}. Is the server live?")

if __name__ == "__main__":
    verify_bazaar_metadata()