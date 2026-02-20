# helius_bot_runner.py

import uvicorn

if __name__ == "__main__":
    uvicorn.run("helius_webhook:app", host="0.0.0.0", port=8000, reload=True, access_log=False)

# helius_webhook.py

from fastapi import FastAPI, Request
from helius_settings import tracked_tokens, logger
from helius_core import monitor_tokens
import asyncio
import time

app = FastAPI()

@app.post("/helius-webhook")
async def helius_webhook(request: Request):
    body = await request.json()
    for event in body:
        if event.get("type") == "TOKEN_MINT":
            transfers = event.get("tokenTransfers", [])
            mint = transfers[0].get("mint") if transfers else None
            raw_ts = event.get("timestamp")
            timestamp = raw_ts / 1000 if raw_ts and raw_ts > 10**12 else (raw_ts or time.time())

            if mint and mint not in tracked_tokens:
                tracked_tokens[mint] = {"timestamp": timestamp, "state": "new", "last_check": 0.0, "data": {}}
                logger.info(f"🆕 New token minted: {mint} at {timestamp}")
    return {"status": "ok"}

@app.on_event("startup")
async def start_background_tasks():
    logger.info("🚀 Launching monitor loop (startup event)...")
    asyncio.create_task(monitor_tokens())

# helius_settings.py

import os
import logging
import time

from dotenv import load_dotenv
load_dotenv()

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

# Configuration Constants
TOKEN_MINIMUM_AGE = 600   # 10 minutes
CHECK_WATCH_EVERY = 600   # 10 minutes
CHECK_TRACK_EVERY = 180   # 3 minutes
CHECK_FLAGGED_EVERY = 60  # 1 minute
CACHE_TTL = 180           # cache lifetime (sec)
REQUEST_DELAY = 1.0       # throttle: 1 req/sec total

# Logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("helius_bot")

# Global state
tracked_tokens = {}
CACHE = {}
LAST_REQUEST = 0.0

# helius_core.py

import os
import time
import json
import asyncio
import math
from helius_settings import logger, DISCORD_WEBHOOK_URL, tracked_tokens
from helius_fetchers import fetch_token_data
import aiohttp

class DeployerReputationManager:
    def __init__(self, path="deployer_history.json"):
        self.path = path
        if os.path.exists(path):
            with open(path, "r") as f:
                self.data = json.load(f)
        else:
            self.data = {}

    def get_score(self, address: str) -> float:
        if address == "renounced":
            return 0.8
        info = self.data.get(address, {"rugs": 0, "safe": 0})
        total = info["rugs"] + info["safe"]
        if total == 0:
            return 0.5
        return round(info["safe"] / total, 2)

    def record_outcome(self, address: str, success: bool):
        if address == "renounced":
            return
        record = self.data.setdefault(address, {"rugs": 0, "safe": 0})
        if success:
            record["safe"] += 1
        else:
            record["rugs"] += 1
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)

def calculate_moon_score(data: dict, deployer_score: float = 0.0):
    deployer_type = data.get("deployer_type", "unknown")
    type_bonus = {
        "renounced": 5,
        "factory": -10,
        "bare-mint": -5,
        "token-2022": 3
    }.get(deployer_type, 0)

    liquidity_score = min(data.get("liquidity_usd", 0) / 5000, 1) * 20
    holder_score = min(data.get("holder", 0) / 50, 1) * 15
    volume_score = min(data.get("volume_24h_usd", 0) / 10000, 1) * 25
    momentum_score = max(min(data.get("price_change_1h", 0) / 20, 1), 0) * 10
    concentration_score = (1 - data.get("top10_holder_ratio", 0.85)) * 20
    deployer_component = max(min(deployer_score, 1), -1) * 10

    total = liquidity_score + holder_score + volume_score + momentum_score + concentration_score + deployer_component + type_bonus
    total = round(max(0, min(total, 100)), 2)

    return total, {
        "liquidity_score": liquidity_score,
        "holder_score": holder_score,
        "volume_score": volume_score,
        "momentum_score": momentum_score,
        "concentration_score": concentration_score,
        "deployer_component": deployer_component,
    }

async def send_discord_message(mint: str, data: dict, score_details: dict, total_score: float, deployer_score: float):
    if not DISCORD_WEBHOOK_URL:
        return

    embed = {
        "title": f"🚀 New Token Watched: {data.get('symbol', 'Unknown')} ({mint[:6]}...)",
        "color": 0x00ffcc,
        "fields": [
            {"name": "Mint Address", "value": f"`{mint}`", "inline": False},
            {"name": "Liquidity (USD)", "value": f"${data.get('liquidity_usd', 0):,.0f}", "inline": True},
            {"name": "Volume 24h", "value": f"${data.get('volume_24h_usd', 0):,.0f}", "inline": True},
            {"name": "Price (USD)", "value": f"${data.get('price_usd', 0):,.6f}", "inline": True},
            {"name": "Holders", "value": f"{data.get('holder', 0)}", "inline": True},
            {"name": "Top 10 Holders", "value": f"{data.get('top10_holder_ratio', 0):.2f}", "inline": True},
        ],
        "footer": {"text": f"Tracked by Helius Token Bot — {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC"}
    }

    async with aiohttp.ClientSession() as session:
        try:
            await session.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]})
        except Exception as e:
            logger.warning(f"Discord send failed: {e}")

async def analyze_token(mint: str):
    token = tracked_tokens[mint]
    logger.info(f"[{mint}] Performing first analysis (10 min mark)...")
    data = await fetch_token_data(mint)
    if not data:
        logger.info(f"[{mint}] No data found — skipping.")
        return

    rep_mgr = DeployerReputationManager()
    deployer = data.get("deployer", "unknown")
    deployer_score = rep_mgr.get_score(deployer)

    score, details = calculate_moon_score(data, deployer_score)
    token.update({"data": data, "moon_score": score, "last_check": time.time()})

    # Simple filter: if it has bare minimums, keep watching; else ignore
    if data.get("liquidity_usd", 0) < 10000:
        token["state"] = "ignore"
        logger.info(f"[{mint}] ❌ Ignored: too little liquidity")
    elif data.get("volume_24h_usd", 0) < 10000:
        token["state"] = "ignore"
        logger.info(f"[{mint}] ❌ Ignored: too little volume")
    elif data.get("holder", 0) < 25:
        token["state"] = "ignore"
        logger.info(f"[{mint}] ❌ Ignored: too few holders")
    elif data.get("top10_holder_ratio", 1.0) > 0.85:
        token["state"] = "ignore"
        logger.info(f"[{mint}] ❌ Ignored: top 10 holders too concentrated")
    else:
        token["state"] = "watch"
        logger.info(f"[{mint}] 👀 Passed filter, now watching")
        await send_discord_message(mint, data)

async def refresh_token_state(mint: str):
    from helius_settings import CHECK_WATCH_EVERY, CHECK_TRACK_EVERY, CHECK_FLAGGED_EVERY

    token = tracked_tokens[mint]
    now = time.time()
    elapsed = now - token.get("last_check", 0)
    state = token["state"]

    if (state == "watch" and elapsed < CHECK_WATCH_EVERY) or \
       (state == "track" and elapsed < CHECK_TRACK_EVERY) or \
       (state == "flagged" and elapsed < CHECK_FLAGGED_EVERY):
        return

    data = await fetch_token_data(mint)
    if not data:
        return

    score, details = calculate_moon_score(data)
    token.update({"data": data, "moon_score": score, "last_check": now})

    if score < 40:
        token["state"] = "ignore"
        logger.info(f"[{mint}] ⏹️ Dropped to ignore (MoonScore={score})")
    elif state == "watch" and score >= 70:
        token["state"] = "track"
        logger.info(f"[{mint}] 📈 Promoted to TRACK (MoonScore={score})")
    elif state == "track" and score >= 85:
        token["state"] = "flagged"
        logger.info(f"[{mint}] 🚀 Promoted to FLAGGED (MoonScore={score})")
    elif state == "flagged" and score < 70:
        token["state"] = "track"
        logger.info(f"[{mint}] ⬇️ Demoted to TRACK (MoonScore={score})")

async def monitor_tokens():
    from helius_settings import TOKEN_MINIMUM_AGE

    summary_timer = time.time()
    while True:
        now = time.time()
        for mint, token in list(tracked_tokens.items()):
            age = now - token["timestamp"]
            if token["state"] == "new" and age >= TOKEN_MINIMUM_AGE:
                await analyze_token(mint)
            elif token["state"] in ("watch", "track", "flagged"):
                await refresh_token_state(mint)
            elif token["state"] == "ignore" and age > 3600:
                tracked_tokens.pop(mint, None)

        if now - summary_timer > 1800:
            summary_timer = now
            states = {"new":0,"watch":0,"track":0,"flagged":0,"ignore":0}
            scores = []
            for t in tracked_tokens.values():
                states[t["state"]] += 1
                if t.get("moon_score"): scores.append(t["moon_score"])
            avg = round(sum(scores)/len(scores), 1) if scores else 0
            logger.info(f"=== Status Summary ===  New:{states['new']} Watch:{states['watch']} "
                        f"Track:{states['track']} Flagged:{states['flagged']} Ignore:{states['ignore']} "
                        f"| Avg Score:{avg}")
            logger.info("=======================")

        await asyncio.sleep(5)

# helius_fetchers.py

import aiohttp
import asyncio
import os
from helius_settings import logger, CACHE, CACHE_TTL, REQUEST_DELAY, LAST_REQUEST, BIRDEYE_API_KEY, HELIUS_API_KEY
import time

MORALIS_API_KEY = os.getenv("MORALIS_API_KEY", "")

async def throttled_get(url: str, headers=None, timeout=10):
    global LAST_REQUEST
    now = time.time()
    wait = REQUEST_DELAY - (now - LAST_REQUEST)
    if wait > 0:
        await asyncio.sleep(wait)
    LAST_REQUEST = time.time()

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=timeout) as resp:
            if resp.status != 200:
                logger.debug(f"HTTP {resp.status} for {url}")
                return None
            return await resp.json()

async def fetch_dexscreener_data(mint: str) -> dict:
    if mint in CACHE and time.time() - CACHE[mint]["timestamp"] < CACHE_TTL:
        return CACHE[mint]["data"]

    url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
    try:
        data = await throttled_get(url)
    except Exception as e:
        logger.warning(f"[{mint}] DexScreener failed: {e}")
        return {}

    if not data or not data.get("pairs"):
        return {}

    pair = data["pairs"][0]
    result = {
        "symbol": pair.get("baseToken", {}).get("symbol"),
        "name": pair.get("baseToken", {}).get("name"),
        "mint": mint,
        "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0)),
        "volume_24h_usd": float(pair.get("volume", {}).get("h24", 0)),
        "price_usd": float(pair.get("priceUsd", 0)),
        "price_change_1h": float(pair.get("priceChange", {}).get("h1", 0)),
        "holder": 0,
        "top10_holder_ratio": 0.85
    }
    CACHE[mint] = {"timestamp": time.time(), "data": result}
    return result

async def fetch_moralis_holder_data(mint: str) -> tuple[int, float]:
    if not MORALIS_API_KEY:
        return 0, 0.85

    url = f"https://solana-gateway.moralis.io/token/mainnet/{mint}/top-holders?limit=10"
    headers = {"X-API-Key": MORALIS_API_KEY, "accept": "application/json"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(f"[{mint}] Moralis holder fetch failed: HTTP {resp.status}")
                    return 0, 0.85
                data = await resp.json()
                holders = data.get("result", [])
                total_holders = len(holders)
                top10_ratio = sum(h.get("percentageRelativeToTotalSupply", 0.0) for h in holders) / 100.0
                return total_holders, round(top10_ratio, 4)
    except Exception as e:
        logger.warning(f"[{mint}] Moralis holder fetch error: {e}")
        return 0, 0.85


async def fetch_birdeye_premium(mint: str) -> dict:
    if not BIRDEYE_API_KEY:
        logger.warning("⚠️ No Birdeye API key found in environment!")
        return {}

    url = f"https://public-api.birdeye.so/defi/token_overview?address={mint}&chain=solana"
    headers = {"X-API-KEY": BIRDEYE_API_KEY, "accept": "application/json"}

    try:
        data = await throttled_get(url, headers=headers)
        return data.get("data") or {}
    except Exception as e:
        logger.warning(f"[{mint}] Birdeye premium failed: {e}")
        return {}


async def fetch_helius_deployer(mint: str) -> tuple[str, str]:
    if not HELIUS_API_KEY:
        logger.warning("⚠️ No Helius API key found in environment!")
        return "", "unknown"

    url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
    payload = {
        "jsonrpc": "2.0",
        "id": "fetchDeployer",
        "method": "getAsset",
        "params": {"id": mint}
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                result = data.get("result", {})
                authorities = result.get("authorities", [])
                if not authorities:
                    return "", "unknown"

                deployer = authorities[0].get("address", "")
                if deployer == "11111111111111111111111111111111":
                    deployer = "renounced"

                return deployer, classify_deployer_type(result)
    except Exception as e:
        logger.warning(f"[{mint}] Helius DAS deployer fetch failed: {e}")
        return "", "unknown"

def classify_deployer_type(result: dict) -> str:
    authorities = result.get("authorities", [])
    creators = result.get("creators", [])
    token_program = result.get("token_info", {}).get("token_program", "")
    metadata_links = result.get("content", {}).get("links", {})

    if authorities and authorities[0].get("address") == "11111111111111111111111111111111":
        return "renounced"
    if "Tokenz" in token_program or "2022" in token_program:
        return "token-2022"
    if len(creators) > 1 or any("factory" in c.get("address", "").lower() for c in creators):
        return "factory"
    if not metadata_links:
        return "bare-mint"
    return "standard"

async def fetch_token_data(mint: str) -> dict:
    data = await fetch_dexscreener_data(mint)

    if not data:
        # logger.warning(f"[{mint}] DexScreener failed, trying Birdeye fallback")
        birdeye_data = await fetch_birdeye_premium(mint)
        if not birdeye_data:
            logger.warning(f"[{mint}] No data found in DexScreener or Birdeye — skipping")
            return {}

        data = {
            "symbol": birdeye_data.get("symbol"),
            "name": birdeye_data.get("name"),
            "mint": mint,
            "liquidity_usd": birdeye_data.get("liquidity_usd", 0),
            "volume_24h_usd": birdeye_data.get("volume_24h_usd", 0),
            "price_usd": birdeye_data.get("price_usd", 0),
            "price_change_1h": 0.0,
            "holder": 0,
            "top10_holder_ratio": 0.85
        }

    # Even if we have DexScreener, use Birdeye to enrich
    birdeye_data = await fetch_birdeye_premium(mint)
    if birdeye_data:
        for key in ("symbol", "name", "price_usd", "liquidity_usd", "volume_24h_usd"):
            if birdeye_data.get(key):
                data[key] = birdeye_data[key]

    holders, top10_ratio = await fetch_moralis_holder_data(mint)
    if holders > 0:
        data["holder"] = holders
    if top10_ratio:
        data["top10_holder_ratio"] = top10_ratio

    if data:
        deployer, deployer_type = await fetch_helius_deployer(mint)
        data["deployer"] = deployer
        data["deployer_type"] = deployer_type

    return data

tracked_tokens = {}

def get_tracked_tokens():
    from helius_webhook import tracked_tokens  # Import shared memory
    return {k: v["data"] for k, v in tracked_tokens.items()}
