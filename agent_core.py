import asyncio
import aiohttp
import re
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import json

from config import client
from supabase_memory import save_fact, get_fact, search_facts, extract_fact  # ✅ now using Supabase
from coin_info import get_coin_info, get_coin_info_cmc
from code_runner import run_code_snippet
from brave_search_tool import brave_search_tool
from web_search import perform_duckduckgo_search

SYSTEM_IDENTITY = """
You are Beau’s AI partner, co-developer, and assistant. Your name is Rebo.
You speak naturally and helpfully — like ChatGPT — not like a robot.
You are intelligent, curious, and think before acting.
You can run Python code, fetch crypto prices, and search the web.
Only use tools when necessary. If you're unsure what the user meant, ask them to clarify.
Do not overuse web search. Only search when a real answer requires fresh or external info.
Summarize web results conversationally. If no good sources are found, say so honestly.
Assume timezone is America/New_York (Eastern Time) when giving date and time.
"""

def get_datetime_info():
    est_offset = timedelta(hours=-4)
    est_time = datetime.now(timezone.utc) + est_offset
    return est_time.strftime("It is currently %A, %B %d, %Y at %I:%M %p Eastern Time.")

def clean_url(url):
    url = url.strip()
    if not url.startswith("http"):
        url = "http" + url.split("http", 1)[-1]
    url = re.sub(r"(\?|&)utm_[^&]+", "", url)
    url = re.sub(r"(\?|&)fbclid=[^&]+", "", url)
    return url

async def async_scrape_page(session, url):
    """Scrape the main content of a web page asynchronously."""
    try:
        async with session.get(url, timeout=12) as resp:
            if resp.status != 200:
                return None
            html = await resp.text()
    except Exception:
        return None

    soup = BeautifulSoup(html, "html.parser")
    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
    text = "\n".join(paragraphs)
    return text if len(text) > 50 else None

async def hybrid_web_search(query, max_urls=8):
    """Runs both Brave and DuckDuckGo searches in parallel, scrapes pages, and summarizes results."""
    
    brave_task = asyncio.to_thread(brave_search_tool, query)
    ddg_task = asyncio.to_thread(perform_duckduckgo_search, query)
    brave_results, ddg_results = await asyncio.gather(brave_task, ddg_task)

    brave_urls = [clean_url(line) for line in brave_results.split("\n") if "http" in line]
    ddg_urls = [clean_url(line) for line in ddg_results.split("\n") if "http" in line]

    all_urls = list(dict.fromkeys(brave_urls + ddg_urls))[:max_urls]
    if not all_urls:
        return "No useful results found from either Brave or DuckDuckGo."

    async with aiohttp.ClientSession() as session:
        scrape_tasks = [async_scrape_page(session, url) for url in all_urls]
        scraped_contents = await asyncio.gather(*scrape_tasks)

    scraped_contents = [f"From {url}:\n{content}" for url, content in zip(all_urls, scraped_contents) if content]
    if not scraped_contents:
        return "I found links but couldn’t extract useful content from them."

    summary_prompt = [
        {
            "role": "system",
            "content": f"You are a smart agent. Summarize these multiple articles into one coherent, concise update about '{query}'."
        },
        {
            "role": "user",
            "content": "\n\n---\n\n".join(scraped_contents)
        }
    ]
    summary = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=summary_prompt
    ).choices[0].message.content.strip()

    sources_list = "\n".join(f"- {url}" for url in all_urls)
    return f"🔍 Combined update on **{query}**:\n\n{summary}\n\n**Sources:**\n{sources_list}"

async def chat_with_bot(message, history=None):
    """Main async chatbot handler with Supabase memory."""
    
    # ✅ Load memory from Supabase
    facts = search_facts()
    facts_string = "\n".join([f"{f['key']}: {f['value']}" for f in facts]) if facts else "No stored facts yet."

    messages = [{"role": "system", "content": SYSTEM_IDENTITY + "\nKnown facts:\n" + facts_string}]
    
    if history:
        for user, bot in history:
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": bot})
    messages.append({"role": "user", "content": message})

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_coin_info",
                "description": "Fetch the live price and market data for a cryptocurrency using CoinGecko.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Name or symbol of the cryptocurrency."}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_coin_info_cmc",
                "description": "Fetch live market data from CoinMarketCap for a cryptocurrency (fallback or alternative source).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Name or symbol of the coin."}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "brave_search_tool",
                "description": "Run a hybrid search using both Brave and DuckDuckGo, scrape pages, and summarize results.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "What the user wants to search for."}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "perform_duckduckgo_search",
                "description": "Run a hybrid search using both Brave and DuckDuckGo, scrape pages, and summarize results.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search term or question."}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_code_snippet",
                "description": "Execute a Python code snippet and return the output.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Python code prefixed with 'run code:'."}
                    },
                    "required": ["message"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_datetime_info",
                "description": "Get the current system date and time in human-readable format.",
                "parameters": {"type": "object", "properties": {}}
            }
        },
    ]

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )

    choice = response.choices[0]
    reply = choice.message.content or ""

    # ✅ Save to Supabase if fact detected
    key, value = extract_fact(message)
    if key and value:
        save_fact(category="general", key=key, value=value)
        if any(phrase in message.lower() for phrase in ["remember", "keep in mind"]):
            return f"Got it — I’ll remember that {key.replace('_', ' ')} is {value}."

    if choice.finish_reason == "tool_calls":
        tool_call = choice.message.tool_calls[0]
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments or '{}')

        if func_name in ["brave_search_tool", "perform_duckduckgo_search"]:
            return await hybrid_web_search(args["query"])
        elif func_name == "get_coin_info":
            return f"Here’s the latest on {args['query']}:\n{get_coin_info(args['query'])}"
        elif func_name == "get_coin_info_cmc":
            return f"CoinMarketCap data for {args['query']}:\n{get_coin_info_cmc(args['query'])}"
        elif func_name == "run_code_snippet":
            return run_code_snippet(args["message"])
        elif func_name == "get_datetime_info":
            return get_datetime_info()

    return reply
