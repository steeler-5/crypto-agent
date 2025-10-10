# tools/web_search_tool.py
import requests
import re
import trafilatura
from openai import OpenAI
from config import client


# === Brave Search Wrapper ===
def brave_search(query, max_results=5):
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {"Accept": "application/json", "X-Subscription-Token": "YOUR_BRAVE_API_KEY"}
    params = {"q": query, "count": max_results}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code == 200:
            return [res["url"] for res in r.json().get("web", {}).get("results", [])]
        else:
            return []
    except Exception:
        return []


# === Page Scraper ===
def extract_clean_text(url):
    try:
        response = requests.get(url, timeout=10)
        downloaded = trafilatura.extract(response.text)
        return downloaded if downloaded else ""
    except Exception:
        return ""


# === GPT Summary Generator ===
def summarize_text(text, query):
    prompt = [
        {"role": "system", "content": "You are an expert research assistant."},
        {"role": "user", "content": f"Given this content, answer the question: '{query}'\n\n{text[:6000]}"}
    ]
    try:
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=prompt
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ Failed to summarize: {e}"


# === Unified Web Search Tool ===
def search_web_and_summarize(query):
    links = brave_search(query)
    if not links:
        return "No search results found."

    pages = [extract_clean_text(url) for url in links]
    combined = "\n\n".join(filter(None, pages))
    if not combined:
        return "Couldn't extract any readable content from top search results."

    return summarize_text(combined, query)


# === Tool Config ===
tool_config = {
    "name": "search_web_and_summarize",
    "description": "Search the web and summarize the best matching content for the user's question.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"}
        },
        "required": ["query"]
    },
    "function": lambda query: search_web_and_summarize(query)
}
