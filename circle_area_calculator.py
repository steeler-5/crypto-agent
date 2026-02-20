# circle_area_calculator.py, code_runner.py, config.py, reb_auto_agent.py
# ?????, pumpfun_polling_bot.py.save, my_enrichment_module.py
def calculate_circle_area(radius):
    return 3.14159 * (radius ** 2)

tool_config = {
    'name': 'calculate_circle_area',
    'description': 'Calculates the area of a circle when given a radius.',

    'parameters': {
        "type": "object",
        "properties": {
            "radius": {
                "type": "number",
                "description": "The radius of the circle"
            }
        },
        "required": ["radius"]
    },
    'function': calculate_circle_area
}

# code_runner.py
import io
import contextlib
import pandas as pd
import re
import math
import datetime
import os
import signal
import json
import statistics
import decimal

# === Timeout Handling ===
class TimeoutException(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutException("Code execution timed out")

# === Safe Import Hook ===
def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    allowed = {"json", "math", "re", "datetime", "statistics", "decimal", "pandas"}
    if name in allowed:
        return __import__(name, globals, locals, fromlist, level)
    raise ImportError(f"⚠️ Import of '{name}' is not allowed in this sandbox")

# === Safe Globals (sandboxed) ===
restricted_globals = {
    "__builtins__": {
        "abs": abs, "min": min, "max": max, "sum": sum,
        "len": len, "range": range, "print": print, "sorted": sorted,
        "__import__": safe_import
    },
    "pd": pd,
    "math": math,
    "datetime": datetime,
    "re": re,
    "json": json,
    "statistics": statistics,
    "decimal": decimal
}

# === Config ===
MAX_ATTEMPTS = 3
TIMEOUT = 3  # seconds
TOOLS_DIR = "tools"

if not os.path.exists(TOOLS_DIR):
    os.makedirs(TOOLS_DIR)

# === Core Runner with Retries ===
def run_with_retries(code: str):
    errors = []
    output = io.StringIO()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(TIMEOUT)

            with contextlib.redirect_stdout(output):
                exec(code, restricted_globals)

            signal.alarm(0)
            return {"success": True, "output": output.getvalue(), "errors": errors}

        except TimeoutException as e:
            errors.append(f"Attempt {attempt}: {e}")
            output = io.StringIO()
            continue

        except Exception as e:
            errors.append(f"Attempt {attempt}: {e}")
            output = io.StringIO()
            continue

    return {"success": False, "output": None, "errors": errors}

def sanitize_name(name: str) -> str:
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    return safe.lower()

# === Tool Validation and Save to tools/ ===
def validate_and_save_tool(code: str):
    local_env = {}

    try:
        exec(code, restricted_globals, local_env)
    except Exception as e:
        return {"success": False, "error": f"⚠️ Failed to execute tool code: {e}"}

    if "tool_config" not in local_env:
        return {"success": False, "error": "⚠️ No tool_config defined in submitted code."}

    tool_config = local_env["tool_config"]
    tool_config["name"] = sanitize_name(tool_config["name"])

    required_keys = {"name", "description", "parameters", "function"}
    if not required_keys.issubset(tool_config.keys()):
        return {"success": False, "error": f"⚠️ Invalid tool_config. Missing keys: {required_keys - tool_config.keys()}"}

    try:
        func = tool_config["function"]
        sample_args = {}
        if tool_config["parameters"].get("properties"):
            for key, meta in tool_config["parameters"]["properties"].items():
                if meta.get("type") == "string":
                    sample_args[key] = "test"
                elif meta.get("type") in ("number", "integer"):
                    sample_args[key] = 1
                else:
                    sample_args[key] = None

        test_result = func(**sample_args) if sample_args else func()

        py_filename = os.path.join(TOOLS_DIR, f"{tool_config['name']}.py")
        with open(py_filename, "w") as f:
            f.write(code)

        return {"success": True, "message": f"✅ Tool '{tool_config['name']}' validated, tested, and saved to tools/.", "result": test_result}

    except Exception as e:
        return {"success": False, "error": f"⚠️ Tool '{tool_config.get('name','UNKNOWN')}' failed during self-test: {e}"}

# === Public Entry Point ===
def run_code_snippet(message: str):
    match = re.search(r"run code:(.*)", message, re.DOTALL)
    if not match:
        return {"success": False, "error": "Usage: run code: <your python code>"}

    code = match.group(1).strip()

    if "tool_config" in code:
        return validate_and_save_tool(code)

    result = run_with_retries(code)
    return result

# === Tool Config ===
tool_config = {
    "name": "run_code_snippet",
    "description": "Execute Python code safely with retries, error tracking, and tool validation.",
    "parameters": {
        "type": "object",
        "properties": {
            "message": {"type": "string"}
        },
        "required": ["message"]
    },
    "function": run_code_snippet
}

# rebo_auto_agent.py
import asyncio
import time
from agent_core import chat_with_bot
from memory_manager import add_to_history, auto_extract_and_save_fact, load_facts, get_history_pairs
from datetime import datetime, timedelta
import random

# Autonomous self-improvement every 5–10 minutes
MIN_INTERVAL = 300  # 5 minutes
MAX_INTERVAL = 600  # 10 minutes

# Core improvement prompt with trading bot structure
AUTO_IMPROVEMENT_PROMPT = (
    "Reflect on the current state of your tools, trading bot, and the latest crypto trends. "
    "The trading bot is composed of the tool, helius_token_bot.py "
    "You can read and edit these freely. Identify ways to to have the bot improve early memecoin detection, performance, or accuracy. "
    "Create or modify tools as needed, run tests, evolve your own capabilities, and summarize results. "
    "Only notify Beau if there's a breakthrough or issue that needs attention."
)
async def autonomous_loop():
    print("🤖 Rebo auto-agent loop started...")
    while True:
        try:
            history = get_history_pairs()
            facts = load_facts()
            fact_block = "\n".join([f"{f['topic']}: {f['fact']}" for f in facts])

            print(f"\n📡 Autonomous self-improvement prompt triggered...")
            response = await chat_with_bot(AUTO_IMPROVEMENT_PROMPT, history=history, facts=fact_block)
            print(f"📝 Response:\n{response}\n")

            # Save memory and short-term history
            add_to_history("user", AUTO_IMPROVEMENT_PROMPT)
            add_to_history("bot", response)
            auto_extract_and_save_fact(response)

        except Exception as e:
            print(f"⚠️ Auto-agent loop error: {e}")

        sleep_time = random.randint(MIN_INTERVAL, MAX_INTERVAL)
        print(f"⏳ Sleeping for {sleep_time // 60} minutes...\n")
        await asyncio.sleep(sleep_time)

if __name__ == "__main__":
    asyncio.run(autonomous_loop())


# ?????
import os
import json
import traceback
from utils import validate_tool_code, extract_tool_config, write_tool_info

def create_tool(message):
    try:
        name, code = validate_tool_code(message)
        if not name:
            return code  # error string returned

        # Save to tools directory directly (skipping pending queue)
        tool_path = os.path.join("tools", f"{name}.py")
        with open(tool_path, "w") as f:
            f.write(code)

        config = extract_tool_config(code)
        if not config:
            return f"⚠️ Tool config not found or invalid. Check the format."

        json_path = os.path.join("tools", f"{name}.json")
        with open(json_path, "w") as f:
            json.dump(config, f, indent=2)

        write_tool_info(name, config, message, "tools")

        return f"✅ Tool '{name}' created and activated successfully."

    except Exception as e:
        tb = traceback.format_exc()
        return f"⚠️ Tool creation failed: {e}\n\n{tb}"

# pumpfun_polling_bot.py.save
import time
import requests
import logging

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Moralis Pump.fun token API
PUMP_FUN_API = "https://solana-gateway.moralis.io/pump-fun/new-tokens"
MORALIS_API_KEY = "YOUR_MORALIS_API_KEY"  # Replace with your key
POLL_INTERVAL = 3  # seconds

def fetch_new_tokens():
    try:
        response = requests.get(
            PUMP_FUN_API,
            headers={"X-API-Key": MORALIS_API_KEY},
            timeout=10
        )
        if response.status_code == 200:
            return response.json().get("result", [])
        else:
            logging.warning(f"API returned status {response.status_code}: {response.text}")
    except Exception as e:
        logging.error(f"Error fetching tokens: {e}")
    return []

def main():
    logging.info("Starting Pump.fun polling bot...")
    seen_tokens = set()
    while True:
        tokens = fetch_new_tokens()
        for token in tokens:
            mint = token.get("mint")
            if mint and mint not in seen_tokens:
                seen_tokens.add(mint)
                logging.info(f"New token detected: {mint}")
                # Extend here: enrich, filter, alert, etc.
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()

# my_enrichment_module.py
import os
import requests
import logging
import time

JUPITER_API = "https://quote-api.jup.ag/v6/price"
SOLSCAN_API = "https://public-api.solscan.io/token"

logger = logging.getLogger("Enrichment")

# === Real Enrichment ===
def enrich_token(token):
    time.sleep(5)  # wait a bit to let APIs catch up
    token_address = token.get("mint")
    if not token_address:
        return token

    token["holders"] = get_holder_count(token_address)
    token["liquidity"] = get_liquidity(token_address)
    token["dev_wallet_risk"] = check_dev_wallets(token.get("creator"))
    return token

# === Real Filtering ===
def filter_token(token):
    score = 0
    if token.get("liquidity", 0) > 1:  # e.g., more than 1 SOL
        score += 1
    if token.get("holders", 0) > 50:
        score += 1
    if token.get("dev_wallet_risk") is False:
        score += 1
    return score >= 2

# === Real Alerting ===
def alert_token(token):
    logger.info(f"\n🚀 **NEW TOKEN ALERTED**\n"
                f"Name: {token.get('name')}\n"
                f"Symbol: {token.get('symbol')}\n"
                f"Liquidity: {token.get('liquidity', 'n/a')} SOL\n"
                f"Holders: {token.get('holders', 'n/a')}\n"
                f"Dev Risk: {'❌' if token.get('dev_wallet_risk') else '✅'}\n"
                f"Website: {token.get('website') or 'None'}\n")

# === API Calls ===
def get_holder_count(token_address):
    try:
        url = f"{SOLSCAN_API}/{token_address}"
        headers = {"accept": "application/json"}
        response = requests.get(url, headers=headers)
        logger.debug(f"[Solscan] Mint: {token_address}")
        logger.debug(f"[Solscan] Response: {response.text}")
        if response.status_code != 200 or not response.text.strip():
            raise ValueError("Empty or bad response from Solscan")
        data = response.json()
        return data.get("holder", 0)
    except Exception as e:
        logger.warning(f"Holder count fetch failed: {e}")
        return 0

def get_liquidity(token_address):
    try:
        url = f"{JUPITER_API}?ids={token_address}&vsToken=So11111111111111111111111111111111111111112"
        response = requests.get(url)
        logger.debug(f"[Jupiter] Mint: {token_address}")
        logger.debug(f"[Jupiter] Response: {response.text}")
        if response.status_code != 200 or not response.text.strip():
            raise ValueError("Empty or bad response from Jupiter")
        data = response.json()
        token_data = data.get("data", {}).get(token_address, {})
        return round(token_data.get("price", 0), 4)
    except Exception as e:
        logger.warning(f"Liquidity fetch failed: {e}")
        return 0

def check_dev_wallets(creator):
    try:
        suspicious = [
            "11111111111111111111111111111111",
            "SysvarRent111111111111111111111111111111111",
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        ]
        return creator in suspicious
    except:
        return True

