"""
helius_token_bot.py — Free Mode (DexScreener + Birdeye Public)
───────────────────────────────────────────────────────────────
✅ Helius webhook for new mints (free)
✅ DexScreener for liquidity / price / volume (no key)
✅ Birdeye Public fallback (no key)
✅ Built-in throttling & caching (prevents 429 errors)
✅ Uses your MoonScore + deployer reputation system
───────────────────────────────────────────────────────────────
"""

import os
import time
import json
import logging
import asyncio
import aiohttp
from pathlib import Path
from fastapi import FastAPI, Request
from dotenv import load_dotenv
load_dotenv()
import uvicorn
import random

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

async def send_discord_message(mint: str, data: dict, score_details: dict, total_score: float, deployer_score: float):
    """Send structured notification to Discord."""
    if not DISCORD_WEBHOOK_URL:
        return

    embed = {
        "title": f"🚀 New Token Watched: {data.get('symbol', 'Unknown')} ({mint[:6]}...)",
        "color": 0x00ffcc if total_score >= 70 else 0xffcc00,
        "fields": [
            {"name": "Mint Address", "value": f"`{mint}`", "inline": False},
            {"name": "Total MoonScore", "value": f"**{total_score:.2f}**", "inline": True},
            {"name": "Deployer Reputation", "value": f"{deployer_score:.2f}", "inline": True},
            {"name": "Liquidity Score", "value": f"{score_details['liquidity_score']:.1f}", "inline": True},
            {"name": "Holder Score", "value": f"{score_details['holder_score']:.1f}", "inline": True},
            {"name": "Volume Score", "value": f"{score_details['volume_score']:.1f}", "inline": True},
            {"name": "Momentum Score", "value": f"{score_details['momentum_score']:.1f}", "inline": True},
            {"name": "Whale Distribution", "value": f"{score_details['concentration_score']:.1f}", "inline": True},
            {"name": "Deployer Impact", "value": f"{score_details['deployer_component']:.1f}", "inline": True},
            {"name": "Liquidity (USD)", "value": f"${data.get('liquidity_usd', 0):,.0f}", "inline": True},
            {"name": "Volume 24h", "value": f"${data.get('volume_24h_usd', 0):,.0f}", "inline": True},
            {"name": "Price (USD)", "value": f"${data.get('price_usd', 0):,.6f}", "inline": True},
            {"name": "Top 10 Holders", "value": f"{data.get('top10_holder_ratio', 0):.2f}", "inline": True},
        ],
        "footer": {"text": f"Tracked by Helius Token Bot — {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC"}
    }

    payload = {"embeds": [embed]}

    async with aiohttp.ClientSession() as session:
        try:
            await session.post(DISCORD_WEBHOOK_URL, json=payload)
        except Exception as e:
            logger.warning(f"Discord send failed: {e}")

# =====================================================
# CONFIGURATION
# =====================================================
app = FastAPI()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("helius_bot")

TOKEN_MINIMUM_AGE = 900   # 15 minutes
CHECK_WATCH_EVERY = 600   # 10 minutes
CHECK_TRACK_EVERY = 180   # 3 minutes
CHECK_FLAGGED_EVERY = 60  # 1 minute
CACHE_TTL = 180            # cache lifetime (sec)
REQUEST_DELAY = 1.0        # throttle: 1 req/sec total

tracked_tokens = {}
CACHE = {}
LAST_REQUEST = 0.0

# =====================================================
# DEPLOYER REPUTATION MANAGER
# =====================================================
class DeployerReputationManager:
    def __init__(self, filepath="deployer_reputation.json"):
        self.filepath = Path(filepath)
        if self.filepath.exists():
            with open(self.filepath, "r") as f:
                self.data = json.load(f)
        else:
            self.data = {}

    def get_score(self, address: str) -> float:
        info = self.data.get(address, {"rugs": 0, "safe": 0})
        total = info["rugs"] + info["safe"]
        if total == 0:
            return 0.0
        return round((info["safe"] - info["rugs"]) / total, 2)

    def update(self, address: str, is_rug: bool):
        record = self.data.get(address, {"rugs": 0, "safe": 0})
        if is_rug:
            record["rugs"] += 1
        else:
            record["safe"] += 1
        self.data[address] = record
        with open(self.filepath, "w") as f:
            json.dump(self.data, f, indent=2)

deployer_rep = DeployerReputationManager()

# =====================================================
# MOONSCORE FUNCTION
# =====================================================
def calculate_moon_score(data: dict, deployer_score: float = 0.0):
    liquidity = float(data.get("liquidity_usd", 0))
    volume = float(data.get("volume_24h_usd", 0))
    price_change = float(data.get("price_change_1h", 0))
    whale_concentration = float(data.get("top10_holder_ratio", 0.85))

    liquidity_score = min(liquidity / 100000, 1) * 20
    holder_score = min(holders / 50, 1) * 15
    volume_score = min(volume / 200000, 1) * 25
    momentum_score = max(min(price_change / 20, 1), 0) * 10
    concentration_score = (1 - whale_concentration) * 20
    deployer_component = max(min(deployer_score, 1), -1) * 10

    total = liquidity_score + holder_score + volume_score + momentum_score + concentration_score + deployer_component
    total = round(max(0, min(total, 100)), 2)

    details = {
        "liquidity_score": liquidity_score,
        "holder_score": holder_score,
        "volume_score": volume_score,
        "momentum_score": momentum_score,
        "concentration_score": concentration_score,
        "deployer_component": deployer_component,
    }

    return total, details

# =====================================================
# THROTTLED REQUEST HELPER
# =====================================================
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

# =====================================================
# DEXSCREENER DATA SOURCE
# =====================================================
async def fetch_dexscreener_data(mint: str) -> dict:
    # caching
    if mint in CACHE and time.time() - CACHE[mint]["timestamp"] < CACHE_TTL:
        return CACHE[mint]["data"]

    url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
    try:
        data = await throttled_get(url)
    except Exception as e:
        logger.warning(f"[{mint}] DexScreener failed: {e}")
        return {}

    if not data:
        return {}

    pairs = data.get("pairs", [])
    if not pairs:
        return {}

    pair = pairs[0]
    result = {
        "symbol": pair.get("baseToken", {}).get("symbol"),
        "name": pair.get("baseToken", {}).get("name"),
        "mint": mint,
        "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0)),
        "volume_24h_usd": float(pair.get("volume", {}).get("h24", 0)),
        "price_usd": float(pair.get("priceUsd", 0)),
        "price_change_1h": float(pair.get("priceChange", {}).get("h1", 0)),
        "price_change_5m": float(pair.get("priceChange", {}).get("m5", 0)),
        "holder": 0,
        "top10_holder_ratio": 0.85
    }
    CACHE[mint] = {"timestamp": time.time(), "data": result}
    return result

# =====================================================
# BIRDEYE PREMIUM DATA SOURCE (SAFE VERSION)
# =====================================================
async def fetch_birdeye_premium(mint: str) -> dict:
    api_key = os.getenv("BIRDEYE_API_KEY", "")
    if not api_key:
        logger.warning("⚠️ No Birdeye API key found in environment!")
        return {}

    url = f"https://public-api.birdeye.so/defi/token_overview?address={mint}&chain=solana"
    headers = {
        "X-API-KEY": api_key,
        "accept": "application/json"
    }

    try:
        data = await throttled_get(url, headers=headers)
    except Exception as e:
        logger.warning(f"[{mint}] Birdeye premium failed: {e}")
        return {}

    info = data.get("data") if data else None
    if not info:
        return {}

    # Helper for safe numeric conversion
    def safe_float(value, default=0.0):
        try:
            return float(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    def safe_int(value, default=0):
        try:
            return int(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    return {
        "symbol": info.get("symbol") or "",
        "name": info.get("name") or "",
        "liquidity_usd": safe_float(info.get("liquidity")),
        "volume_24h_usd": safe_float(info.get("volume_24h")),
        "price_usd": safe_float(info.get("price")),
        "holder": safe_int(info.get("holder")),
        "top10_holder_ratio": safe_float(info.get("top10_holder_ratio"), 0.85),
    }

# =====================================================
# HELIUS DEPLOYER FETCHER (DAS FALLBACK)
# =====================================================
async def fetch_helius_deployer(mint: str) -> str:
    helius_key = os.getenv("HELIUS_API_KEY", "")
    if not helius_key:
        return ""

    url = f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
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
                authorities = data.get("result", {}).get("authorities", [])
                if not authorities:
                    return ""
                deployer = authorities[0].get("address", "")
                if deployer == "11111111111111111111111111111111":
                    deployer = "renounced"
                return deployer
    except Exception as e:
        logger.warning(f"[{mint}] Helius DAS deployer fetch failed: {e}")
        return ""

# =====================================================
# COMBINED FETCHER
# =====================================================
async def fetch_token_data(mint: str) -> dict:
    data = await fetch_dexscreener_data(mint)
    if not data:
        data = await fetch_birdeye_premium(mint)

    if data:
        deployer = await fetch_birdeye_deployer(mint)
        if not deployer:
            deployer = await fetch_helius_deployer(mint)
        if deployer:
            data["deployer"] = deployer

    return data

# =====================================================
# ANALYSIS LOGIC
# =====================================================
async def analyze_token(mint: str):
    token = tracked_tokens[mint]
    logger.info(f"[{mint}] Performing first analysis (15 min mark)...")

    data = await fetch_token_data(mint)
    if not data:
        logger.info(f"[{mint}] No data found — skipping.")
        return

    creator = f"FakeDeployer_{random.randint(1000,9999)}"
    deployer_score = deployer_rep.get_score(creator)

    score, score_details = calculate_moon_score(data, deployer_score)
    token.update({"data": data, "moon_score": score, "last_check": time.time()})

    if score < 40:
        token["state"] = "ignore"
        logger.info(f"[{mint}] ❌ Ignored (MoonScore={score})")
    elif score < 70:
        token["state"] = "watch"
        logger.info(f"[{mint}] 👀 Now watching (MoonScore={score})")
        await send_discord_message(mint, data, score_details, score, deployer_score)
    elif score < 85:
        token["state"] = "track"
        logger.info(f"[{mint}] 📡 Tracking (MoonScore={score})")
    else:
        token["state"] = "flagged"
        logger.info(f"[{mint}] 🚀 Flagged as moon candidate! (MoonScore={score})")

# =====================================================
# REFRESH LOOP
# =====================================================
async def refresh_token_state(mint: str):
    token = tracked_tokens[mint]
    now = time.time()
    elapsed = now - token.get("last_check", 0)
    state = token["state"]

    # check intervals
    if (state == "watch" and elapsed < CHECK_WATCH_EVERY) or \
       (state == "track" and elapsed < CHECK_TRACK_EVERY) or \
       (state == "flagged" and elapsed < CHECK_FLAGGED_EVERY):
        return

    data = await fetch_token_data(mint)
    if not data:
        return

    score, score_details = calculate_moon_score(data)
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

# =====================================================
# MONITOR LOOP
# =====================================================
async def monitor_tokens():
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

        # every 30 min print summary
        if now - summary_timer > 1800:
            summary_timer = now
            states = {"new":0,"watch":0,"track":0,"flagged":0,"ignore":0}
            scores = []
            for t in tracked_tokens.values():
                states[t["state"]] = states.get(t["state"],0)+1
                if t.get("moon_score"): scores.append(t["moon_score"])
            avg = round(sum(scores)/len(scores),1) if scores else 0
            logger.info(f"=== Status Summary ===  New:{states['new']} Watch:{states['watch']} "
                        f"Track:{states['track']} Flagged:{states['flagged']} Ignore:{states['ignore']} "
                        f"| Avg Score:{avg}")
            logger.info("=======================")

        await asyncio.sleep(5)

# =====================================================
# WEBHOOK HANDLER
# =====================================================
@app.post("/helius-webhook")
async def helius_webhook(request: Request):
    body = await request.json()
    for event in body:
        if event.get("type") == "TOKEN_MINT":
            transfers = event.get("tokenTransfers", [])
            mint = transfers[0].get("mint") if transfers else None
            raw_ts = event.get("timestamp")
            if raw_ts and raw_ts > 10**12:
                timestamp = raw_ts / 1000
            else:
                timestamp = raw_ts or time.time()

            if mint and mint not in tracked_tokens:
                tracked_tokens[mint] = {"timestamp": timestamp, "state": "new", "last_check": 0.0, "data": {}}
                logger.info(f"🆕 New token minted: {mint} at {timestamp}")
    return {"status": "ok"}

# =====================================================
# STARTUP
# =====================================================
@app.on_event("startup")
async def start_background_tasks():
    logger.info("🚀 Launching monitor loop (startup event)...")
    asyncio.create_task(monitor_tokens())

if __name__ == "__main__":
    logger.info("🚀 Starting Helius Token Bot — Free Mode")
    uvicorn.run("helius_token_bot:app", host="0.0.0.0", port=8000, reload=True, access_log=False)
