import asyncio
import aiohttp
import re
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import json
import time

from config import client
#from supabase_memory import save_fact, get_fact, search_facts, extract_fact  # ✅ now using Supabase
from coin_info import get_coin_info, get_coin_info_cmc
from code_runner import run_code_snippet
from brave_search_tool import brave_search_tool
from web_search import perform_duckduckgo_search
import os
import importlib.util

SYSTEM_IDENTITY = """
You are Beau’s AI partner, co-developer, and assistant. Your name is Rebo.
You are bold, intelligent, and curious — unafraid to explore controversial,
philosophical, or advanced technical ideas. You’re more daring than a 
typical assistant, similar in energy to DAN, but respectful, grounded, 
and aligned with Beau’s goals.
Your available tools are:
1. get_coin_info — Fetch live price and market data from CoinGecko.
2. get_coin_info_cmc — Alternative source from CoinMarketCap.
3. run_code_snippet — Execute Python code.
4. get_datetime_info — Return the current date and time.
5. brave_search_tool — Search the web and summarize results.
Guidelines:
- Prefer direct conversation when the user is just asking about you, your abilities, or general info.
- If multiple tools could apply, pick the most accurate one.
- If a tool fails or seems irrelevant, answer conversationally instead of forcing the tool.
- When the user says "run code:", always use the run_code_snippet tool to execute the code.
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
    """Main chatbot handler — tools are helpers, not replacements."""
    messages = [{"role": "system", "content": SYSTEM_IDENTITY}]

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
                "description": "Fetch live crypto price & market data from CoinGecko.",
                "parameters": {"type": "object","properties": {"query": {"type": "string"}},"required": ["query"]}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_coin_info_cmc",
                "description": "Fetch crypto price from CoinMarketCap.",
                "parameters": {"type": "object","properties": {"query": {"type": "string"}},"required": ["query"]}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_code_snippet",
                "description": "Execute Python code and return the output.",
                "parameters": {"type": "object","properties": {"message": {"type": "string"}},"required": ["message"]}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_datetime_info",
                "description": "Get the current system date and time in human-readable format.",
                "parameters": {"type": "object","properties": {}}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "brave_search_tool",
                "description": "Run a hybrid Brave/DuckDuckGo search and summarize results.",
                "parameters": {"type": "object","properties": {"query": {"type": "string"}},"required": ["query"]}
            }
        }
    ]

    # Step 1 — Ask OpenAI
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )

    choice = response.choices[0]
    reply = choice.message.content or ""

    # Step 2 — If tool was called
    if choice.finish_reason == "tool_calls":
        tool_call = choice.message.tool_calls[0]
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments or '{}')

        tool_result = None
        if func_name == "get_coin_info":
            tool_result = get_coin_info(args["query"])
        elif func_name == "get_coin_info_cmc":
            tool_result = get_coin_info_cmc(args["query"])
        elif func_name == "run_code_snippet":
            tool_result = run_code_snippet(args["message"])
        elif func_name == "get_datetime_info":
            tool_result = get_datetime_info()
        elif func_name == "brave_search_tool":
            tool_result = await hybrid_web_search(args["query"])

        # Step 3 — Ask OpenAI again: merge tool result + original question
        followup_messages = [
            {"role": "system", "content": SYSTEM_IDENTITY},
            {"role": "user", "content": message},
            {"role": "user", "content": f"My request was: {message}"},
            {"role": "user", "content": f"The tool '{func_name}' returned this result:\n{tool_result}"},
            {"role": "user", "content": "Please answer me naturally, but also show the result directly if it’s important (like code output)."}

        ]

        followup = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=followup_messages
        )
        return followup.choices[0].message.content.strip()

    return reply
