import os
import requests

BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY")

def fetch_memecoins(max_pairs=50):
    url = "https://public-api.birdeye.so/defi/token_trending"
    params = {
        "chain": "solana",
        "limit": max_pairs,
        "api_key": BIRDEYE_API_KEY
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json().get("data", [])
    except Exception as e:
        print(f"❌ Birdeye fetch failed: {e}")
        return []

    coins = []
    for token in data:
        try:
            coins.append({
                "symbol": token.get("symbol", "N/A"),
                "address": token.get("address", "N/A"),
                "liquidity": token.get("liquidity"),
                "volume_24h": token.get("volume"),
                "market_cap": token.get("mc"),
                "pool_age": token.get("created_at"),
                "transactions_24h": token.get("txns", {}).get("h24", 0),
            })
        except Exception as e:
            print("⚠️ Token parse error:", e)
    return coins
