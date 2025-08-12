import requests
from bs4 import BeautifulSoup
import urllib.parse
from config import client

def perform_duckduckgo_search(query):
    headers = {"User-Agent": "Mozilla/5.0"}
    url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
    resp = requests.get(url, headers=headers)
    soup = BeautifulSoup(resp.text, "html.parser")
    summaries = []

    for link in soup.find_all("a", class_="result__a", limit=3):
        href = link.get("href")
        title = link.get_text()
        clean_url = href.split("uddg=")[-1].split("&")[0] if "uddg=" in href else href
        clean_url = urllib.parse.unquote(clean_url)
        try:
            page_resp = requests.get(clean_url, headers=headers, timeout=10)
            page_text = BeautifulSoup(page_resp.text, "html.parser").get_text()
            summary = summarize_page(page_text)
            summaries.append(f"**{title}**\n{summary}")
        except Exception as e:
            summaries.append(f"**{title}**\n(Unable to load page content: {e})")

    return "\n\n---\n\n".join(summaries) if summaries else "No results found."

def summarize_page(text):
    prompt = "Summarize this article clearly and briefly for research purposes:\n" + text[:3000]
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )
    return response.choices[0].message.content.strip()

def should_search_web(message):
    decision_prompt = f"""Decide if this message requires real-time web search to answer accurately:
\"{message}\"
Respond with "yes" or "no" followed by a brief reason."""
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": decision_prompt}],
        temperature=0
    )
    result = response.choices[0].message.content.strip().lower()
    return result.startswith("yes")
