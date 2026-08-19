import cloudscraper
from urllib.parse import urljoin, urlparse, urlunparse
from bs4 import BeautifulSoup

SKIP_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".mp4", ".mp3", ".wav", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".rar",
    ".css", ".js", ".json", ".xml",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".ico", ".woff", ".woff2", ".ttf", ".eot",
}


def _get_scraper():
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "darwin", "mobile": False}
    )


def normalize_url(url):
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    normalized = urlunparse((
        parsed.scheme,
        parsed.netloc,
        path,
        parsed.params,
        parsed.query,
        ""
    ))
    return normalized


def is_crawlable(url):
    parsed = urlparse(url)
    path = parsed.path.lower()

    if parsed.scheme not in ("http", "https", ""):
        return False

    for ext in SKIP_EXTENSIONS:
        if path.endswith(ext):
            return False

    return True


def guess_page_type(path, title="", h1=""):
    combined = f"{path} {title} {h1}".lower()
    p = path.lower().strip("/")
    
    if not p or p == "":
        return "homepage"
    if any(k in combined for k in ["about", "over ons", "over-ons", "over-", "wie zijn wij", "team", "ons verhaal", "geschiedenis"]):
        return "about_page"
    if any(k in combined for k in ["contact", "offerte", "afspraak", "bereikbaarheid", "locatie", "route"]):
        return "contact_page"
    if any(k in combined for k in ["pricing", "tarieven", "prijzen", "kosten"]):
        return "pricing_page"
    if any(k in combined for k in ["galerij", "gallery", "portfolio", "project", "cases", "impressie", "foto's"]):
        return "portfolio_page"
    if any(k in p for k in ["blog/", "nieuws/", "artikelen/"]):
        return "blog_post"
    if any(k in combined for k in ["blog", "nieuws", "artikelen", "kennisbank", "updates"]):
        return "blog_listing"
    if any(k in combined for k in ["faq", "veelgestelde-vragen"]):
        return "faq_page"
    if any(k in combined for k in ["dienst", "service", "studio", "evenement", "event", "workshop", "congres", "vergader", "zaal"]):
        return "service_page"
    return "general_page"


def crawl_site(start_url, max_pages=50, progress_callback=None):
    """
    BFS crawl a website, returning a list of dicts with URL, path, title, h1, and meta_description.
    """
    start_parsed = urlparse(start_url)
    start_domain = start_parsed.netloc

    if not start_domain:
        return []

    scraper = _get_scraper()
    visited = set()
    queue = [normalize_url(start_url)]
    pages_data = []

    while queue and len(pages_data) < max_pages:
        current_url = queue.pop(0)

        if current_url in visited:
            continue

        visited.add(current_url)

        if progress_callback:
            progress_callback("crawl", len(pages_data), max_pages, current_url)

        try:
            response = scraper.get(current_url, timeout=15, allow_redirects=True)

            if response.status_code != 200:
                continue

            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                continue

            soup = BeautifulSoup(response.text, "lxml")

            # Extract basic title, h1, description for instant mini-analysis
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            h1_el = soup.find("h1")
            h1 = h1_el.get_text(separator=" ", strip=True)[:100] if h1_el else ""
            meta_tag = soup.find("meta", attrs={"name": "description"})
            meta_desc = meta_tag["content"].strip()[:150] if meta_tag and meta_tag.get("content") else ""

            path = urlparse(current_url).path or "/"
            guessed_type = guess_page_type(path, title, h1)

            pages_data.append({
                "url": current_url,
                "path": path,
                "title": title,
                "h1": h1,
                "meta_description": meta_desc,
                "guessed_type": guessed_type
            })

            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()

                if href.startswith(("javascript:", "mailto:", "tel:", "#")):
                    continue

                full_url = urljoin(current_url, href)
                normalized = normalize_url(full_url)

                if urlparse(normalized).netloc != start_domain:
                    continue

                if not is_crawlable(normalized):
                    continue

                if normalized not in visited and normalized not in queue:
                    queue.append(normalized)

        except Exception:
            continue

    return pages_data
