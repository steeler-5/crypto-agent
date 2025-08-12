import trafilatura

def scrape_full_page(url: str) -> str:
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return "Failed to access or download the page."
    
    result = trafilatura.extract(downloaded)
    return result or "Couldn't extract meaningful content from the page."
