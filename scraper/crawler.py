import requests
import cloudscraper
import traceback
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

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}


def _get_scraper():
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "darwin", "mobile": False}
    )


def _clean_domain(netloc):
    """Normalize domain by removing port and www. prefix for consistent matching."""
    if not netloc:
        return ""
    domain = netloc.lower().split(":")[0].strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def normalize_url(url):
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    # Strip www. to prevent duplicate pages (me-studio.nl == www.me-studio.nl)
    netloc = parsed.netloc
    if netloc.lower().startswith("www."):
        netloc = netloc[4:]
    normalized = urlunparse((
        parsed.scheme or "https",
        netloc,
        path,
        "",
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


def _fetch_html(url, scraper_instance=None):
    """Fetch HTML with fallback across requests and cloudscraper."""
    # Attempt 1: Direct requests with modern browser headers
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=12, allow_redirects=True)
        if r.status_code == 200 and "text/html" in r.headers.get("Content-Type", ""):
            return r.text, r.url
    except Exception as e:
        pass

    # Attempt 2: Cloudscraper (bypasses Cloudflare / anti-bot challenges)
    try:
        scraper = scraper_instance or _get_scraper()
        r = scraper.get(url, timeout=15, allow_redirects=True)
        if r.status_code == 200 and "text/html" in r.headers.get("Content-Type", ""):
            return r.text, r.url
    except Exception as e:
        print(f"[Crawler] Error fetching {url}: {e}")

    return None, url


def crawl_site(start_url, max_pages=50, progress_callback=None):
    """
    BFS crawl a website with www-agnostic domain matching and multi-engine HTTP fetch.
    Returns a list of dicts with URL, path, title, h1, and meta_description.
    """
    start_parsed = urlparse(start_url)
    start_domain_clean = _clean_domain(start_parsed.netloc)

    if not start_domain_clean:
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

        html_text, final_url = _fetch_html(current_url, scraper)
        if not html_text:
            continue

        try:
            soup = BeautifulSoup(html_text, "lxml")

            # Extract title, h1, description for mini-analysis
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

            # Discover internal links
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()

                if href.startswith(("javascript:", "mailto:", "tel:", "#")):
                    continue

                full_url = urljoin(final_url or current_url, href)
                normalized = normalize_url(full_url)
                target_domain_clean = _clean_domain(urlparse(normalized).netloc)

                # Match domain regardless of www. or subpath redirects
                if target_domain_clean != start_domain_clean:
                    continue

                if not is_crawlable(normalized):
                    continue

                if normalized not in visited and normalized not in queue:
                    queue.append(normalized)

        except Exception as e:
            print(f"[Crawler] Parse error on {current_url}: {e}")
            continue

    return pages_data
