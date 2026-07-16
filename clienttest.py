"""
clienttest.py
Simulates an AI Agent paying for and calling your local API.
"""
import os
import asyncio
import json
import base64

# Import algosdk utilities for our native signer
from algosdk import mnemonic, account, encoding

# Import the x402 client tools
from x402.client import x402Client
from x402.mechanisms.avm.exact import ExactAvmScheme
# NEW: Import the httpx wrapper!
from x402.http.clients.httpx import wrapHttpxWithPayment
import logging
# This forces the x402 client to print exactly why the payment failed
logging.basicConfig(level=logging.DEBUG)

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
        """Signs the array of transactions as requested by the x402 Facilitator."""
        results = [None] * len(unsigned_txns)
        for i in indexes_to_sign:
            b64_txn = base64.b64encode(unsigned_txns[i]).decode('utf-8')
            txn = encoding.msgpack_decode(b64_txn)
            stxn = txn.sign(self._private_key_b64)
            b64_stxn = encoding.msgpack_encode(stxn)
            results[i] = base64.b64decode(b64_stxn)
        return results

# --- 2. SETUP THE BUYER ---
# Make sure your full 25-word phrase is pasted here
BUYER_MNEMONIC = os.environ.get(
    "BUYER_MNEMONIC", 
    "valley scene survey kiwi purchase outer crumble toast slow left tower simple rebuild digital lesson morning between control vital grocery prefer catch tennis above gym"
)

signer = MnemonicSigner(BUYER_MNEMONIC)

# --- 3. CONFIGURE THE x402 CLIENT ---
x402_client = x402Client()
# Register the Algorand Testnet scheme
x402_client.register("algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=", ExactAvmScheme(signer=signer))


async def run_test():
    print("🚀 Firing request to local Agronomic Intelligence Engine...")
    print(f"💳 Paying from test wallet: {signer.address}")
    
    payload = {
        "lat": 18.35,
        "lon": 77.31,
        "crop": "soybean",
        "sowing_date": "2026-06-20",
        "harvest_date": "2026-10-15",
        "forecast_days": 16
    }

    try:
        # NEW: Wrap the x402_client inside httpx so it can actually make internet requests
        async with wrapHttpxWithPayment(x402_client) as http:
            
            # Now we use 'http.post' instead of 'client.post'
            response = await http.post(
                "http://localhost:8001/weather-risk",
                json=payload,
                timeout=20.0
            )
            
            print(f"✅ Status Code: {response.status_code}")
            
            if response.status_code == 200:
                print("✅ Payment settled successfully and data received!")
                print(json.dumps(response.json(), indent=2))
            else:
                print("⚠️ Request failed. Response:")
                print(response.text)
            
    except Exception as e:
        print(f"❌ Payment handling or API communication error: {e}")

if __name__ == "__main__":
    asyncio.run(run_test())