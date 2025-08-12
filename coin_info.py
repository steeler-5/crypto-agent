import requests
import os
from config import CMC_API_KEY

def get_coin_info(symbol_or_name):
    base_url = "https://api.coingecko.com/api/v3"

    overrides = {
        "xrp": "ripple",
        "wbtc": "wrapped-bitcoin",
        "eth": "ethereum"
    }
    coin_id = overrides.get(symbol_or_name.lower(), symbol_or_name.lower())

    params = {'vs_currency': 'usd', 'ids': coin_id}
    r = requests.get(f"{base_url}/coins/markets", params=params)
    if r.status_code == 200 and r.json():
        data = r.json()[0]
        return f"{data['name']} ({data['symbol'].upper()}) is trading at ${data['current_price']:,} with a market cap of ${data['market_cap']:,} and a 24h volume of ${data['total_volume']:,}."

    list_res = requests.get(f"{base_url}/coins/list")
    if list_res.status_code != 200:
        return f"Coin '{symbol_or_name}' not found on CoinGecko."

    coins = list_res.json()
    filtered = [c for c in coins if c['symbol'].lower() == symbol_or_name.lower() and not any(bad in c['id'] for bad in ['peg', 'wrapped', 'wormhole', 'binance'])]
    if not filtered:
        filtered = [c for c in coins if symbol_or_name.lower() in c['name'].lower() and not any(bad in c['id'] for bad in ['peg', 'wrapped', 'wormhole', 'binance'])]

    if not filtered:
        return f"Coin '{symbol_or_name}' not found on CoinGecko."

    coin_id = filtered[0]['id']
    r2 = requests.get(f"{base_url}/coins/markets", params={"vs_currency": "usd", "ids": coin_id})
    if r2.status_code == 200 and r2.json():
        data = r2.json()[0]
        return f"{data['name']} ({data['symbol'].upper()}) is trading at ${data['current_price']:,} with a market cap of ${data['market_cap']:,} and a 24h volume of ${data['total_volume']:,}."

    return f"Coin '{symbol_or_name}' not found on CoinGecko."

def get_coin_info_cmc(symbol_or_name):
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {
        'X-CMC_PRO_API_KEY': CMC_API_KEY
    }
    params = {
        'start': '1',
        'limit': '5000',
        'convert': 'USD'
    }
    r = requests.get(url, headers=headers, params=params)
    if r.status_code != 200:
        return "Failed to fetch from CoinMarketCap."

    for coin in r.json().get("data", []):
        if symbol_or_name.lower() in [coin["symbol"].lower(), coin["name"].lower()]:
            return f"{coin['name']} ({coin['symbol']}) is trading at ${coin['quote']['USD']['price']:.4f}, market cap ${coin['quote']['USD']['market_cap']:,}, 24h volume ${coin['quote']['USD']['volume_24h']:,}."

    return f"Coin '{symbol_or_name}' not found on CoinMarketCap."
