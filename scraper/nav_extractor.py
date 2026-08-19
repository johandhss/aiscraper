from urllib.parse import urljoin
from bs4 import BeautifulSoup


def _extract_nav_items(nav_container, base_url):
    """Extract nested links and labels from a nav element."""
    items = []
    
    # Try finding top-level list
    top_lists = nav_container.find_all(["ul", "ol"], recursive=False)
    if not top_lists:
        # If no direct ul/ol, search any top ul
        top_lists = nav_container.find_all(["ul", "ol"])

    if top_lists:
        for ul in top_lists:
            # Process direct li children
            for li in ul.find_all("li", recursive=False):
                link = li.find("a", href=True)
                label = ""
                href = ""
                if link:
                    label = link.get_text(strip=True)
                    href = urljoin(base_url, link["href"])
                else:
                    # Maybe span/button
                    label = li.get_text(strip=True)[:40]

                if not label:
                    continue

                item = {"label": label, "url": href, "children": []}

                # Check for sub-menus
                sub_ul = li.find(["ul", "ol"])
                if sub_ul:
                    for sub_li in sub_ul.find_all("li", recursive=False):
                        sub_link = sub_li.find("a", href=True)
                        if sub_link:
                            sub_label = sub_link.get_text(strip=True)
                            sub_href = urljoin(base_url, sub_link["href"])
                            if sub_label:
                                item["children"].append({"label": sub_label, "url": sub_href})

                items.append(item)
    else:
        # Fallback: find all direct or nested <a> tags
        for a in nav_container.find_all("a", href=True):
            label = a.get_text(strip=True)
            href = urljoin(base_url, a["href"])
            if label and href:
                items.append({"label": label, "url": href, "children": []})

    return items


def extract_site_navigation(html_content, base_url):
    """
    Extract structured navigation menus (main_nav, footer_nav, sidebar_nav) from HTML.
    """
    soup = BeautifulSoup(html_content, "lxml")
    result = {}

    # 1. Main Nav: <header> nav or first <nav>
    main_nav_element = None
    header = soup.find("header")
    if header:
        main_nav_element = header.find("nav")
    if not main_nav_element:
        # Look for nav with class/id containing 'main', 'menu', 'header', 'primary'
        for nav in soup.find_all("nav"):
            attrs_str = str(nav.attrs).lower()
            if any(k in attrs_str for k in ["main", "primary", "header", "menu", "nav"]):
                main_nav_element = nav
                break
    if not main_nav_element:
        main_nav_element = soup.find("nav")

    if main_nav_element:
        main_items = _extract_nav_items(main_nav_element, base_url)
        if main_items:
            result["main_nav"] = main_items

    # 2. Footer Nav: <footer> nav or links in footer
    footer = soup.find("footer")
    if footer:
        footer_nav_element = footer.find("nav") or footer
        footer_items = _extract_nav_items(footer_nav_element, base_url)
        if footer_items:
            result["footer_nav"] = footer_items

    return result
