"""
clienttest.py (Mainnet Production Tester)
Simulates an AI Agent paying for and calling the live Render API using Mainnet USDC.
"""
import asyncio
import json
import base64
import logging

from algosdk import mnemonic, account, encoding
from x402.client import x402Client
from x402.mechanisms.avm.exact import ExactAvmScheme
from x402.http.clients.httpx import wrapHttpxWithPayment

logging.basicConfig(level=logging.INFO)
logging.basicConfig(level=logging.DEBUG)

logging.getLogger("x402").setLevel(logging.DEBUG)
logging.getLogger("x402_avm").setLevel(logging.DEBUG)
logging.getLogger("httpx").setLevel(logging.DEBUG)
logging.getLogger("httpcore").setLevel(logging.DEBUG)
# --- 1. NATIVE SIGNER ENGINE ---
class MnemonicSigner:
    def __init__(self, mnemonic_phrase: str):
        self._private_key_b64 = mnemonic.to_private_key(mnemonic_phrase)
        self._address = account.address_from_private_key(self._private_key_b64)
        
    @property
    def address(self) -> str:
        return self._address
        
    def sign_transactions(self, unsigned_txns: list[bytes], indexes_to_sign: list[int]) -> list[bytes | None]:
        results = [None] * len(unsigned_txns)
        for i in indexes_to_sign:
            b64_txn = base64.b64encode(unsigned_txns[i]).decode('utf-8')
            txn = encoding.msgpack_decode(b64_txn)
            stxn = txn.sign(self._private_key_b64)
            b64_stxn = encoding.msgpack_encode(stxn)
            results[i] = base64.b64decode(b64_stxn)
        return results

# --- 2. EXECUTE RUN ENGINE ---
async def run_test():
    print("\n🌿 Agrometric Intelligence API - Mainnet Client 🌿")
    print("---------------------------------------------------")
    
    # Standard input avoids the VS Code terminal freeze bug
    print("⚠️ WARNING: You are connecting to ALGORAND MAINNET.")
    buyer_phrase = input("company frequent protect inhale steel radar mask used wedding actress lawsuit purpose prepare genre raw uphold divide coast little spray cheap car awesome able chalk ")
    
    try:
        signer = MnemonicSigner(buyer_phrase.strip())
    except Exception as e:
        print("❌ Invalid mnemonic phrase structure. Ensure it is exactly 25 words.")
        return

    print(f"\n✅ Authenticated Mainnet Wallet: {signer.address}")
    
    # Confirmation Safety Switch
    confirm = input("💳 This request will cost 0.083 REAL USDC. Proceed? (y/n): ")
    if confirm.lower() != 'y':
        print("🛑 Request aborted. No funds spent.")
        return

    # Initialize client and explicitly register the Algorand MAINNET Genesis Hash
    x402_client = x402Client()
    x402_client.register("algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73ktiC1qzkkit8=", ExactAvmScheme(signer=signer))
    
    # ⚠️ CRITICAL: Replace '<YOUR-CUSTOM-RENDER-NAME>' with your actual Render URL
    API_URL = "https://agrometeorological-api.onrender.com/weather-risk"
    
    payload = {
        "lat": 18.35,
        "lon": 77.31,
        "crop": "soybean",
        "sowing_date": "2026-06-20",
        "harvest_date": "2026-10-15",
        "forecast_days": 16
    }

    print(f"\n🚀 Sending payment payload to: {API_URL}")

    try:
        async with wrapHttpxWithPayment(x402_client) as http:
            response = await http.post(
                API_URL,
                json=payload,
                timeout=30.0
            )
            
            print(f"Status Code Received: {response.status_code}")
            
            if response.status_code == 200:
                print("✅ Mainnet Payment Settled! Agronomic Data Received:\n")
                print(json.dumps(response.json(), indent=2))
            else:
                print(f"⚠️ Server returned an error: {response.text}")
            
    except Exception as e:
        print(f"\n❌ Pipeline Communication Error: {e}")
        print("Ensure the wallet has Mainnet ALGO for gas and Mainnet USDC (Asset ID: 31566704).")

if __name__ == "__main__":
    asyncio.run(run_test())
