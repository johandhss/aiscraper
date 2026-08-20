import os
import cloudscraper
from bs4 import BeautifulSoup, NavigableString
from urllib.parse import urljoin
import uuid
import re
import json

from scraper.image_handler import process_and_upload_image, resolve_image_source
from scraper.screenshot_handler import capture_page_screenshot_and_media
from scraper.ai_labeler import classify_page_semantics, _heuristic_classification



def _get_scraper():
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "darwin", "mobile": False}
    )


SECTION_TAGS = {"main", "article", "section", "aside", "header", "footer", "nav"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
CONTENT_TAGS = {"p", "blockquote", "pre", "code", "figcaption", "figure"}
LIST_TAGS = {"ul", "ol"}
TABLE_TAGS = {"table"}
MEDIA_TAGS = {"img", "video", "audio", "picture", "source"}
INTERACTIVE_TAGS = {"form", "button", "input", "select", "textarea"}
LINK_TAGS = {"a"}
SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "meta", "link", "head"}

ALL_BLOCK_TAGS = (
    SECTION_TAGS | HEADING_TAGS | CONTENT_TAGS | LIST_TAGS | 
    TABLE_TAGS | MEDIA_TAGS | INTERACTIVE_TAGS | LINK_TAGS | {"li"}
)


def _get_direct_text(element):
    parts = []
    for child in element.children:
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                parts.append(text)
    return " ".join(parts)


def _get_full_text(element):
    return element.get_text(separator=" ", strip=True)


def _classify_tag(tag_name):
    if tag_name in SECTION_TAGS:
        return "section"
    elif tag_name in HEADING_TAGS:
        return "heading"
    elif tag_name == "p":
        return "paragraph"
    elif tag_name in LIST_TAGS:
        return "list"
    elif tag_name == "li":
        return "list_item"
    elif tag_name in TABLE_TAGS:
        return "table"
    elif tag_name in MEDIA_TAGS:
        return "media"
    elif tag_name in INTERACTIVE_TAGS:
        return "interactive"
    elif tag_name in LINK_TAGS:
        return "link"
    elif tag_name in {"blockquote"}:
        return "blockquote"
    elif tag_name in {"pre", "code"}:
        return "code"
    elif tag_name in {"figure", "figcaption"}:
        return "figure"
    return "unknown"


def _heading_level(tag_name):
    if tag_name in HEADING_TAGS:
        return int(tag_name[1])
    return None


def _extract_attributes(node):
    attrs = {}
    useful_attrs = {"id", "class", "href", "src", "alt", "title", "name", "type", 
                    "placeholder", "value", "action", "method", "role", "aria-label",
                    "data-testid"}
    for k, v in node.attrs.items():
        if k in useful_attrs:
            if isinstance(v, list):
                attrs[k] = " ".join(v)
            else:
                attrs[k] = str(v)
    return attrs


def html_to_markdown(body_element):
    if not body_element:
        return ""
    from copy import deepcopy
    body = deepcopy(body_element)
    
    for tag in body.find_all(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()

    lines = []
    
    def _walk(element, list_depth=0):
        for child in element.children:
            if isinstance(child, NavigableString):
                text = str(child).strip()
                if text:
                    lines.append(text)
                continue
            
            if not hasattr(child, "name") or not child.name:
                continue
                
            tag = child.name
            
            if tag in SKIP_TAGS:
                continue
            elif tag in HEADING_TAGS:
                level = int(tag[1])
                text = child.get_text(separator=" ", strip=True)
                if text:
                    lines.append(f"\n{'#' * level} {text}\n")
            elif tag == "p":
                text = child.get_text(separator=" ", strip=True)
                if text:
                    lines.append(f"\n{text}\n")
            elif tag == "a":
                href = child.get("href", "")
                text = child.get_text(separator=" ", strip=True)
                if text:
                    lines.append(f"[{text}]({href})")
            elif tag == "img":
                alt = child.get("alt", "")
                src = child.get("src", "")
                lines.append(f"![{alt}]({src})")
            elif tag in ("ul", "ol"):
                _walk(child, list_depth + 1)
            elif tag == "li":
                indent = "  " * list_depth
                text = child.get_text(separator=" ", strip=True)
                if text:
                    lines.append(f"{indent}- {text}")
            elif tag in ("pre", "code"):
                text = child.get_text()
                lines.append(f"\n```\n{text}\n```\n")
            elif tag == "blockquote":
                text = child.get_text(separator=" ", strip=True)
                if text:
                    lines.append(f"\n> {text}\n")
            elif tag == "table":
                rows = child.find_all("tr")
                for i, row in enumerate(rows):
                    cells = row.find_all(["td", "th"])
                    cell_texts = [c.get_text(separator=" ", strip=True) for c in cells]
                    lines.append("| " + " | ".join(cell_texts) + " |")
                    if i == 0:
                        lines.append("| " + " | ".join(["---"] * len(cell_texts)) + " |")
            elif tag == "hr":
                lines.append("\n---\n")
            elif tag == "br":
                lines.append("\n")
            else:
                _walk(child, list_depth)
    
    _walk(body)
    result = "\n".join(lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def parse_page(url_str, html_content=None, page_id=None, site_domain=None,
               page_type="", category_id=None, category_name="Algemeen",
               scrape_instructions="", openai_model="gpt-4o-mini",
               openai_api_key=None, progress_callback=None, enable_ai=True):
    """
    Parse a webpage:
    - Captures full-page screenshot using Playwright
    - Extracts hierarchical content blocks
    - Extracts all real images (lazy-loaded, srcset, background-images, dynamic DOM)
    - Extracts CTAs and links
    - Classifies semantics with AI (optional) or fast heuristics
    """
    if not html_content:
        try:
            scraper = _get_scraper()
            response = scraper.get(url_str, timeout=20)
            response.raise_for_status()
            html_content = response.text
        except Exception as e:
            return {"error": str(e)}

    # 1. Capture Full-Page Screenshot & Live DOM media
    if progress_callback:
        progress_callback("screenshot", 0, 0, "Capturing full-page screenshot & rendering lazy images...")

    screenshot_result = capture_page_screenshot_and_media(url_str, page_id, site_domain)
    screenshot_url = screenshot_result.get("screenshot_url")
    playwright_imgs = screenshot_result.get("rendered_images", [])

    soup = BeautifulSoup(html_content, "lxml")

    # 2. Metadata
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    
    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if meta_tag and meta_tag.get("content"):
        meta_desc = meta_tag["content"].strip()

    blocks = []
    raw_images_to_process = []
    raw_links_to_process = []
    order_counter = 0

    # 3. Extract DOM tree & content blocks
    def process_node(node, parent_id, current_heading_level, heading_path_parts):
        nonlocal order_counter

        if not hasattr(node, "name") or not node.name:
            return

        tag = node.name
        if tag in SKIP_TAGS:
            return

        is_block_tag = tag in ALL_BLOCK_TAGS

        if tag == "div":
            div_attrs = node.attrs
            has_semantic_hint = (
                div_attrs.get("id") or 
                div_attrs.get("role") or
                any(cls for cls in (div_attrs.get("class") or []) 
                    if any(kw in cls.lower() for kw in 
                           ["hero", "banner", "feature", "pricing", "testimonial",
                            "cta", "content", "section", "about", "contact",
                            "service", "team", "faq", "benefit", "gallery"]))
            )
            if not has_semantic_hint:
                for child in node.children:
                    process_node(child, parent_id, current_heading_level, heading_path_parts)
                return
            else:
                is_block_tag = True

        if not is_block_tag:
            for child in node.children:
                process_node(child, parent_id, current_heading_level, heading_path_parts)
            return

        block_id = str(uuid.uuid4())
        block_type = _classify_tag(tag) if tag != "div" else "section"
        
        new_heading_path = list(heading_path_parts)
        new_heading_level = current_heading_level
        
        if tag in HEADING_TAGS:
            h_level = _heading_level(tag)
            new_heading_level = h_level
            heading_text = _get_full_text(node)[:80]
            if heading_text:
                new_heading_path = [p for i, p in enumerate(heading_path_parts) if i < h_level - 1]
                new_heading_path.append(heading_text)

        section_path = " > ".join(new_heading_path) if new_heading_path else ""

        container_types = SECTION_TAGS | LIST_TAGS | TABLE_TAGS | {"div"}
        if tag in container_types:
            content = _get_direct_text(node)
        else:
            content = _get_full_text(node)

        attrs = _extract_attributes(node)
        hierarchy_level = new_heading_level if tag in HEADING_TAGS else (current_heading_level + 1)
        
        block = {
            "id": block_id,
            "page_id": page_id,
            "category_id": category_id,
            "block_type": block_type,
            "section_type": None,
            "tag_name": tag,
            "content": content,
            "attributes": attrs if attrs else None,
            "hierarchy_level": hierarchy_level,
            "parent_block_id": parent_id,
            "order_index": order_counter,
            "section_path": section_path,
        }
        blocks.append(block)
        order_counter += 1

        # Check for images (with lazy loading & srcset support)
        if tag == "img":
            img_src, img_alt = resolve_image_source(node, url_str)
            if img_src:
                raw_images_to_process.append({
                    "src": img_src,
                    "alt": img_alt,
                    "section_context": section_path,
                    "block_id": block_id
                })

        # Check for background images on sections / divs
        if tag in ["div", "section", "header", "main"] and attrs:
            bg_style = attrs.get("style", "")
            if "background" in bg_style and "url(" in bg_style:
                bg_match = re.search(r'url\([\'"]?([^\'")]+)[\'"]?\)', bg_style)
                if bg_match:
                    bg_url = bg_match.group(1)
                    if not bg_url.startswith("data:"):
                        full_bg = urljoin(url_str, bg_url)
                        raw_images_to_process.append({
                            "src": full_bg,
                            "alt": f"Background: {section_path or tag}",
                            "section_context": section_path,
                            "block_id": block_id
                        })

        # Check for links and CTA buttons
        if tag == "a":
            href = attrs.get("href", "")
            link_text = _get_full_text(node)
            if href and link_text:
                raw_links_to_process.append({
                    "id": str(uuid.uuid4()),
                    "url": href,
                    "text": link_text[:120],
                    "section_context": section_path
                })

        # Recursively process children
        for child in node.children:
            process_node(child, block_id, new_heading_level, new_heading_path)

    body = soup.find("body")
    if body:
        for child in body.children:
            process_node(child, None, 0, [])

    # 4. Integrate Playwright Real DOM Images (lazy-loaded & dynamic)
    seen_rendered = set()
    for pw_img in playwright_imgs:
        src = pw_img["src"]
        if src in seen_rendered:
            continue
        seen_rendered.add(src)
        raw_images_to_process.append({
            "src": src,
            "alt": pw_img.get("alt", ""),
            "section_context": "Main Content",
            "block_id": None,
            "dims": (pw_img["width"], pw_img["height"])
        })

    # 5. Process & Upload Images to Supabase Storage
    processed_images = []
    seen_img_urls = set()

    if progress_callback:
        progress_callback("images", 0, len(raw_images_to_process), f"Processing {len(raw_images_to_process)} images...")

    for raw_img in raw_images_to_process[:25]:
        src = raw_img["src"]
        if src in seen_img_urls:
            continue
        seen_img_urls.add(src)

        img_record = process_and_upload_image(
            img_url=src,
            base_url=url_str,
            page_id=page_id,
            site_domain=site_domain or "site",
            alt_text=raw_img.get("alt", ""),
            section_context=raw_img.get("section_context", ""),
            block_id=raw_img.get("block_id"),
            predefined_dims=raw_img.get("dims")
        )
        if img_record:
            img_record["category_id"] = category_id
            processed_images.append(img_record)

    # 6. Prepare Page Links / CTAs
    processed_links = []
    seen_link_pairs = set()
    for raw_link in raw_links_to_process:
        key = (raw_link["text"], raw_link["url"])
        if key in seen_link_pairs:
            continue
        seen_link_pairs.add(key)
        
        processed_links.append({
            "id": raw_link["id"],
            "page_id": page_id,
            "link_type": "internal_link" if not raw_link["url"].startswith("http") or (site_domain and site_domain in raw_link["url"]) else "external_link",
            "text": raw_link["text"],
            "url": raw_link["url"],
            "section_context": raw_link["section_context"],
            "is_primary": False
        })

    # 7. Semantic Classification (AI or Instant Heuristic)
    has_api_key = bool(openai_api_key or os.environ.get("OPENAI_API_KEY"))
    if enable_ai and has_api_key:
        if progress_callback:
            progress_callback("ai", 0, 0, f"AI Semantic Analysis for {category_name}...")

        ai_results = classify_page_semantics(
            page_url=url_str,
            page_title=title,
            page_type=page_type,
            scrape_instructions=scrape_instructions,
            sections_data=blocks,
            images_data=processed_images,
            links_data=processed_links,
            category_name=category_name,
            model=openai_model,
            api_key=openai_api_key
        )
    else:
        if progress_callback:
            progress_callback("heuristic", 0, 0, f"Heuristic layout classification for {category_name}...")
        ai_results = _heuristic_classification(blocks, processed_images, processed_links)

    section_class_map = {item["block_id"]: item.get("section_type") for item in ai_results.get("sections", [])}
    for b in blocks:
        if b["id"] in section_class_map:
            b["section_type"] = section_class_map[b["id"]]

    img_class_map = {item["image_id"]: item.get("image_type") for item in ai_results.get("images", [])}
    for img in processed_images:
        if img["id"] in img_class_map:
            img["image_type"] = img_class_map[img["id"]]

    link_class_map = {item["link_id"]: item for item in ai_results.get("links", [])}
    for link in processed_links:
        if link["id"] in link_class_map:
            link_info = link_class_map[link["id"]]
            link["link_type"] = link_info.get("link_type", link["link_type"])
            link["is_primary"] = link_info.get("is_primary", False)

    # 8. Raw markdown
    markdown_soup = BeautifulSoup(html_content, "lxml")
    raw_markdown = html_to_markdown(markdown_soup.find("body"))

    return {
        "title": title,
        "meta_description": meta_desc,
        "screenshot_url": screenshot_url,
        "blocks": blocks,
        "images": processed_images,
        "links": processed_links,
        "raw_markdown": raw_markdown,
        "html_content": html_content
    }
