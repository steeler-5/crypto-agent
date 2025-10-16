"""
helius_token_bot.py
───────────────────────────────
Continuous-Mode Architecture (CU-Free)
───────────────────────────────
Current behavior:
- Listen for new token mints from Helius webhook
- Store & track all tokens in memory
- Wait 15 min for each before first check
- Automatically move tokens through mock states:
    "new" → "watch" → "track" → "flagged" (simulated)
───────────────────────────────
"""

import os
import time
import json
import logging
import asyncio
from fastapi import FastAPI, Request
import uvicorn

# =====================================================
#  CONFIGURATION
# =====================================================
app = FastAPI()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("helius_bot")

# Placeholder keys
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "")

# Timing configuration (seconds)
TOKEN_MINIMUM_AGE = 900     # 15 min until first analysis
CHECK_WATCH_EVERY = 600     # 10 min
CHECK_TRACK_EVERY = 180     # 3 min
CHECK_FLAGGED_EVERY = 60    # 1 min

# =====================================================
#  GLOBAL STATE
# =====================================================
tracked_tokens = {}  # mint -> {timestamp, state, last_check, data}


# =====================================================
#  PLACEHOLDER DATA FUNCTIONS
# =====================================================
async def mock_fetch_token_data(mint: str) -> dict:
    """
    Placeholder for Birdeye / Jupiter metrics.
    Returns mock data for demonstration.
    """
    await asyncio.sleep(0.1)  # simulate small delay
    # fake "data evolution" by randomizing values slightly
    import random
    holders = random.randint(0, 200)
    liquidity = random.randint(0, 10000)
    volume = random.randint(0, 8000)
    score = (liquidity / 200) + (holders / 5) + (volume / 400)
    return {
        "holders": holders,
        "liquidity": liquidity,
        "volume": volume,
        "mock_score": round(score, 2)
    }


def simulate_moon_score(data: dict) -> float:
    """Rough proxy until Birdeye data is connected."""
    return data.get("mock_score", 0.0)


# =====================================================
#  TOKEN ANALYSIS
# =====================================================
async def analyze_token(mint: str):
    """Perform first analysis when token hits 15 min age."""
    token = tracked_tokens[mint]
    logger.info(f"[{mint}] Performing first analysis (15 min mark)...")
    data = await mock_fetch_token_data(mint)
    score = simulate_moon_score(data)
    token["data"] = data
    token["moon_score"] = score
    token["last_check"] = time.time()

    # Classify based on score thresholds
    if score < 40:
        token["state"] = "ignore"
        logger.info(f"[{mint}] ❌ Ignored (MoonScore={score})")
    elif 40 <= score < 70:
        token["state"] = "watch"
        logger.info(f"[{mint}] 👀 Now watching (MoonScore={score})")
    elif 70 <= score < 85:
        token["state"] = "track"
        logger.info(f"[{mint}] 📡 Tracking (MoonScore={score})")
    else:
        token["state"] = "flagged"
        logger.info(f"[{mint}] 🚀 Flagged as moon candidate! (MoonScore={score})")


async def refresh_token_state(mint: str):
    """Re-check existing tokens based on their current state."""
    token = tracked_tokens[mint]
    now = time.time()
    elapsed = now - token.get("last_check", 0)
    state = token["state"]

    if state == "watch" and elapsed >= CHECK_WATCH_EVERY:
        logger.info(f"[{mint}] 🔄 Refreshing WATCH token...")
    elif state == "track" and elapsed >= CHECK_TRACK_EVERY:
        logger.info(f"[{mint}] 🔄 Refreshing TRACK token...")
    elif state == "flagged" and elapsed >= CHECK_FLAGGED_EVERY:
        logger.info(f"[{mint}] 🔄 Refreshing FLAGGED token...")
    else:
        return  # not yet time to check again

    data = await mock_fetch_token_data(mint)
    score = simulate_moon_score(data)
    token["data"] = data
    token["moon_score"] = score
    token["last_check"] = now

    # State transitions
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
    else:
        logger.debug(f"[{mint}] Score updated: {score}")


# =====================================================
#  MASTER MONITOR LOOP
# =====================================================
async def monitor_tokens():
    """Main continuous loop managing all token checks."""
    while True:
        now = time.time()
        if not tracked_tokens:
            await asyncio.sleep(5)
            continue

        for mint, token in list(tracked_tokens.items()):
            age = now - token["timestamp"]

            # 1️⃣  First-time analysis after 15 min
            if token["state"] == "new" and age >= TOKEN_MINIMUM_AGE:
                await analyze_token(mint)

            # 2️⃣  Periodic refresh for watch/track/flagged
            elif token["state"] in ("watch", "track", "flagged"):
                await refresh_token_state(mint)

            # 3️⃣  Cleanup ignored tokens after 1 hr
            elif token["state"] == "ignore" and age > 3600:
                logger.info(f"[{mint}] 🧹 Removing ignored token from memory.")
                tracked_tokens.pop(mint, None)

        await asyncio.sleep(5)  # Small delay between full passes


# =====================================================
#  TOKEN REGISTRATION
# =====================================================
async def add_token(mint: str, timestamp: float):
    """Register new token from Helius event."""
    if mint in tracked_tokens:
        return
    tracked_tokens[mint] = {
        "timestamp": timestamp,
        "state": "new",
        "last_check": 0.0,
        "data": {}
    }
    logger.info(f"🆕 New token minted: {mint} at {timestamp}")


# =====================================================
#  WEBHOOK HANDLER
# =====================================================
@app.post("/helius-webhook")
async def helius_webhook(request: Request):
    """Receive webhook payloads from Helius."""
    body = await request.json()

    for event in body:
        if event.get("type") == "TOKEN_MINT":
            transfers = event.get("tokenTransfers", [])
            mint = transfers[0].get("mint") if transfers else None
            timestamp = event.get("timestamp")
            if mint:
                await add_token(mint, timestamp)
            else:
                logger.warning("⚠️ Missing mint address in event.")

    return {"status": "ok"}


# =====================================================
#  STARTUP
# =====================================================
if __name__ == "__main__":
    logger.info("🚀 Starting Continuous-Mode Helius Token Bot (CU-Free)")
    # Launch background monitoring loop
    asyncio.get_event_loop().create_task(monitor_tokens())
    uvicorn.run("helius_token_bot:app", host="0.0.0.0", port=8000, reload=True, access_log=False)
