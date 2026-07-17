from algosdk.v2client import algod
import json

def verify_asset_opt_in():
    # 1. Connect to the public Mainnet node (no API token needed)
    algod_address = "https://mainnet-api.algonode.cloud"
    algod_token = ""
    client = algod.AlgodClient(algod_token, algod_address)

    # 2. The exact Merchant Wallet and USDC Asset ID from your error log
    merchant_wallet = "BRSMWTNWFRW26LU7FQ7CG2KY65P5HTCBXX6QAOIEM35NESQFGWM4KWEYDU"
    usdc_asset_id = 31566704

    print(f"🔍 Scanning Mainnet for Wallet: {merchant_wallet}")
    print(f"🎯 Looking for Asset ID: {usdc_asset_id} (USDC)\n")

    try:
        # Fetch the live account data from the blockchain
        account_info = client.account_info(merchant_wallet)
        
        # Isolate the list of assets the wallet has opted into
        assets = account_info.get("assets", [])
        
        # Search the array for our specific USDC asset
        is_opted_in = False
        for asset in assets:
            if asset["asset-id"] == usdc_asset_id:
                is_opted_in = True
                balance = asset["amount"] / 1_000_000 # Convert micro-units to standard USDC
                print(f"✅ VERIFIED: The wallet IS opted into USDC.")
                print(f"💰 Current USDC Balance: {balance}\n")
                break
        
        if not is_opted_in:
            print(f"❌ REJECTED: The wallet is NOT opted into USDC (Asset {usdc_asset_id}).")
            print("👉 Fix: Open your Pera/Defly wallet, select this account, and click 'Add Asset' for 31566704.")
            
    except Exception as e:
        print(f"⚠️ Error reaching the blockchain: {e}")

if __name__ == "__main__":
    verify_asset_opt_in()