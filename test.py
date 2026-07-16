import httpx

BUYER = "74QXCL674VOAJ2KPY5TGUERAPJVXSCSC2WGFGEQXOQTW27VTEQ5FPKDZQQ"
MERCHANT = "3TWBSI64D4DHR7JK3REJMO5QV4GFEW3FCKXJEUNAWEO3IXBA2DHUNJ5N6E"
ASSET_ID = 10458941

def check_wallet(name, address):
    print(f"\n--- Checking {name} Wallet: {address} ---")
    url = f"https://testnet-api.algonode.cloud/v2/accounts/{address}"
    resp = httpx.get(url)
    
    if resp.status_code != 200:
        print("❌ ERROR: Wallet not found on blockchain (0 ALGO balance).")
        return False
        
    data = resp.json()
    algo = data.get('amount', 0) / 1_000_000
    print(f"ALGO Balance: {algo} ALGO")
    
    # Extract all assets the wallet is opted into
    assets = {a['asset-id']: a['amount'] for a in data.get('assets', [])}
    
    if ASSET_ID not in assets:
        print(f"❌ ERROR: Wallet is NOT opted into USDC (Asset {ASSET_ID})")
        return False
        
    usdc_micro = assets[ASSET_ID]
    print(f"USDC Balance: ${usdc_micro / 1_000_000:.6f} ({usdc_micro} micro-units)")
    
    # The Buyer must have enough to pay the $0.083 fee
    if name == "BUYER" and usdc_micro < 83000:
        print(f"❌ ERROR: Buyer has insufficient USDC. You need to use the Circle Faucet!")
        return False
        
    print("✅ Looks good!")
    return True

print("🔍 RUNNING BLOCKCHAIN DIAGNOSTIC...")
b_ok = check_wallet("BUYER", BUYER)
m_ok = check_wallet("MERCHANT", MERCHANT)

if b_ok and m_ok:
    print("\n✅ BOTH WALLETS ARE PERFECT. The simulation should pass.")
else:
    print("\n❌ FIX THE ERRORS LISTED ABOVE.")