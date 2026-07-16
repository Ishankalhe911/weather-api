"""
clienttest.py (Mainnet Production Tester)
Simulates an AI Agent paying for and calling the live Agrometric Intelligence API.
"""
import asyncio
import json
import base64
import logging
import getpass # For secure password/mnemonic entry

from algosdk import mnemonic, account, encoding
from x402.client import x402Client
from x402.mechanisms.avm.exact import ExactAvmScheme
from x402.http.clients.httpx import wrapHttpxWithPayment

# Turn on debug logging to see the payment handshake
logging.basicConfig(level=logging.INFO) # Changed to INFO so it doesn't spam their terminal, just shows HTTP status

# --- 1. BUILD THE NATIVE SIGNER ---
class MnemonicSigner:
    """Implements the ClientAvmSigner protocol natively using algosdk."""
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

# --- 2. THE TEST EXECUTION ---
async def run_test():
    print("\n🌿 Welcome to the Agrometric Intelligence API Tester 🌿")
    print("------------------------------------------------------")
    
    # Securely ask the colleague for their wallet phrase (it hides the text as they type)
    print("⚠️ WARNING: You are connecting to ALGORAND MAINNET.")
    buyer_phrase = getpass.getpass("Paste your 25-word wallet phrase (input will be hidden): ")
    
    try:
        signer = MnemonicSigner(buyer_phrase.strip())
    except Exception as e:
        print("❌ Invalid mnemonic phrase. Please ensure it is exactly 25 words.")
        return

    print(f"\n✅ Wallet authenticated: {signer.address}")
    
    # Confirmation Safety Switch
    confirm = input("💳 This request will cost 0.083 REAL USDC. Proceed? (y/n): ")
    if confirm.lower() != 'y':
        print("🛑 Request aborted. No funds spent.")
        return

    # Configure the client for Mainnet
    x402_client = x402Client()
    x402_client.register("algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73ktiC1qzkkit8=", ExactAvmScheme(signer=signer))
    
    # ⚠️ REPLACE THIS URL WITH YOUR ACTUAL RENDER URL
    API_URL = "https://agri-intel-weather.onrender.com/weather-risk"
    
    payload = {
        "lat": 18.35,
        "lon": 77.31,
        "crop": "soybean",
        "sowing_date": "2026-06-20",
        "harvest_date": "2026-10-15",
        "forecast_days": 16
    }

    print("\n🚀 Firing request to live Agrometric Intelligence Engine...")

    try:
        async with wrapHttpxWithPayment(x402_client) as http:
            response = await http.post(
                API_URL,
                json=payload,
                timeout=30.0 # Bumped timeout to 30s just in case Render is waking up from sleep
            )
            
            print(f"\nHTTP Status Code: {response.status_code}")
            
            if response.status_code == 200:
                print("✅ Payment settled on Mainnet! Data received:\n")
                print(json.dumps(response.json(), indent=2))
            else:
                print("⚠️ Request failed. Response:")
                print(response.text)
            
    except Exception as e:
        print(f"\n❌ Payment handling or API communication error: {e}")
        print("Make sure your wallet has at least 0.1 ALGO for gas and is opted into USDC (Asset: 31566704).")

if __name__ == "__main__":
    asyncio.run(run_test())