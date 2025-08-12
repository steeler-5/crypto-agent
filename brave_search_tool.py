import requests
import os
import time
from datetime import datetime

# === CONFIGURATION ===
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")  # Or replace with a string literal for local dev
RATE_LIMIT_SECONDS = 10
DAILY_LIMIT = 50
USAGE_LOG_FILE = "brave_usage_log.json"

# === INTERNAL STATE ===
_last_search_time = 0
_usage = {
    "daily_count": 0,
    "last_reset": datetime.utcnow().date().isoformat()
}

# === CORE SEARCH FUNCTION ===
def perform_brave_search(query):
    global _last_search_time, _usage
    now = time.time()
    current_date = datetime.utcnow().date().isoformat()

    # Reset daily count if date changed
    if _usage["last_reset"] != current_date:
        _usage = {"daily_count": 0, "last_reset": current_date}

    if _usage["daily_count"] >= DAILY_LIMIT:
        return "Daily search limit reached. Please try again tomorrow."

    if now - _last_search_time < RATE_LIMIT_SECONDS:
        return "Search too soon. Please wait before searching again."

    _last_search_time = now
    _usage["daily_count"] += 1

    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": BRAVE_API_KEY
    }
    params = {
        "q": query
    }

    try:
        response = requests.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        results = data.get("web", {}).get("results", [])
        if not results:
            return "No relevant results found."

        formatted = [f"• {res.get('title')}: {res.get('description')}\n{res.get('url')}" for res in results[:5]]
        return "\n\n".join(formatted)
    except Exception as e:
        return f"Error during Brave search: {str(e)}"

# === TOOL WRAPPER ===
def brave_search_tool(query: str) -> str:
    return perform_brave_search(query)

# Example usage
if __name__ == "__main__":
    print(brave_search_tool("solana price news"))
