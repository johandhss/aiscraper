"""
Page Structure Generator — creates compact, hierarchical layout descriptions
for LLMs so they understand exactly how a page is built: which text belongs
to which heading/image, and how sections relate to each other.

Two output modes:
- generate_page_structure(page_id)          → full (includes paragraph text)
- generate_page_structure_compact(page_id)  → compact (headings + images + CTAs only)
"""

import json
from scraper.db import get_page, get_page_blocks, get_page_images, get_page_links


def generate_page_structure(page_id):
    """Full structure with paragraph text included."""
    return _generate_structure(page_id, compact=False)


def generate_page_structure_compact(page_id):
    """Compact skeleton: headings + images + CTAs only, no paragraph text."""
    return _generate_structure(page_id, compact=True)


def _truncate(text, max_len=120):
    if not text:
        return ""
    text = str(text).replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len - 3] + "..."
    return text


def _parse_attrs(b):
    attrs = b.get("attributes")
    if not attrs:
        return {}
    if isinstance(attrs, str):
        try:
            return json.loads(attrs)
        except Exception:
            return {}
    return attrs


def _extract_filename(src):
    """Get a readable filename from a URL, filtering out SVG placeholders."""
    if not src:
        return None
    if "svg" in src and ("data:" in src or "%3E" in src.lower() or "%3C" in src.lower()):
        return None
    if src.startswith("data:"):
        return None
    filename = src.split("/")[-1].split("?")[0]
    if not filename or filename in ("", "svg%3E", "%3E"):
        return None
    return filename


def _format_image(attrs, img_data=None):
    """Format an image reference for the structure output."""
    src = attrs.get("src", "")
    filename = _extract_filename(src)
    if not filename:
        return None

    alt = attrs.get("alt", "")
    width = attrs.get("width", "")
    height = attrs.get("height", "")

    if img_data:
        width = img_data.get("width") or width
        height = img_data.get("height") or height

    dims = f" ({width}×{height})" if width and height else ""
    alt_text = f' alt="{_truncate(alt, 40)}"' if alt else ""
    return f"IMG: {_truncate(filename, 50)}{dims}{alt_text}"


def _build_ancestor_set(blocks, root_block_id):
    """Find all block IDs that are descendants of root_block_id."""
    block_by_id = {b["id"]: b for b in blocks if b.get("id")}
    descendants = set()
    descendants.add(root_block_id)
    # Simple BFS: find all blocks whose parent is in the set
    changed = True
    while changed:
        changed = False
        for b in blocks:
            bid = b.get("id")
            pid = b.get("parent_block_id")
            if bid and pid and pid in descendants and bid not in descendants:
                descendants.add(bid)
                changed = True
    return descendants


def _generate_structure(page_id, compact):
    page = get_page(page_id)
    if not page:
        return "Page not found."

    blocks = get_page_blocks(page_id)
    images = get_page_images(page_id)
    links = get_page_links(page_id)

    # Build image lookup
    image_map = {}
    for img in images:
        for key in ["original_url", "public_url", "url", "src"]:
            src = img.get(key)
            if src:
                image_map[src] = img

    path = page.get("path", "/")
    title = page.get("title", "")
    page_type = page.get("page_type", "unknown")
    meta_desc = page.get("meta_description", "")
    screenshot = page.get("screenshot_url", "")

    cat_name = "Algemeen"
    cats = page.get("categories")
    if isinstance(cats, dict):
        cat_name = cats.get("name", "Algemeen")

    # ── Identify header/nav and footer block IDs to skip their children ──
    header_block_ids = set()
    footer_block_ids = set()
    nav_items = []  # Collect (label, href) for compact nav display
    footer_start_index = None

    for i, b in enumerate(blocks):
        tag = (b.get("tag_name") or "").lower()
        bid = b.get("id")

        if tag in ("header", "nav") and bid:
            # Find all descendants of this header/nav block
            desc = _build_ancestor_set(blocks, bid)
            header_block_ids.update(desc)

            # Extract nav links from descendants
            for child_b in blocks:
                if child_b.get("id") in desc and (child_b.get("tag_name") or "").lower() == "a":
                    child_attrs = _parse_attrs(child_b)
                    href = child_attrs.get("href", "")
                    label = (child_b.get("content") or "").strip()
                    if label and href and href != "#" and len(label) < 40:
                        if (label, href) not in nav_items:
                            nav_items.append((label, href))

        if tag == "footer" and bid:
            footer_start_index = i
            desc = _build_ancestor_set(blocks, bid)
            footer_block_ids.update(desc)

    # ── Build output ──
    out = []
    out.append(f"## Page Structure: {path} ({title})")
    out.append(f"Type: {page_type} | Category: {cat_name}")
    if meta_desc:
        out.append(f"Meta: {_truncate(meta_desc, 160)}")
    if screenshot:
        out.append(f"Screenshot: {screenshot}")
    out.append("")

    # Navigation summary (deduplicated, compact)
    if nav_items:
        out.append("[HEADER/NAV]")
        # Show logo if there's an img in header
        for b in blocks:
            if b.get("id") in header_block_ids and (b.get("tag_name") or "").lower() == "img":
                attrs = _parse_attrs(b)
                fn = _extract_filename(attrs.get("src", ""))
                if fn:
                    out.append(f"  Logo: {fn}")
                    break

        # Deduplicate nav items and show compactly
        seen_labels = set()
        top_nav = []
        for label, href in nav_items:
            label_key = label.strip().lower()
            if label_key not in seen_labels:
                seen_labels.add(label_key)
                top_nav.append(f"{label}")
        out.append(f"  Nav: {' | '.join(top_nav[:15])}")
        out.append("")

    # ── Main content (skip header and footer descendants) ──
    has_hero = False
    skip_ids = header_block_ids  # Don't skip footer yet, handle separately

    for i, b in enumerate(blocks):
        bid = b.get("id")
        tag = (b.get("tag_name") or "").lower()
        content = (b.get("content") or "").strip()
        attrs = _parse_attrs(b)

        # Skip header/nav descendants (already shown compactly)
        if bid and bid in skip_ids:
            continue

        # Skip footer descendants (will show footer separately)
        if bid and bid in footer_block_ids:
            continue

        # Skip structural/wrapper tags with no real content
        if tag in ("header", "nav", "footer", "main", "article", "aside"):
            continue
        if tag == "div" and (not content or content.startswith("#") or content.startswith(".") or content.startswith("ast-")):
            continue
        if tag == "section" and not content:
            continue

        # Determine indent based on hierarchy
        level = b.get("hierarchy_level", 0)
        indent = "  " * max(0, min(level - 1, 3))

        # ── Headings ──
        if tag == "h1":
            if not has_hero:
                has_hero = True
                out.append(f"[HERO]")
            out.append(f"{indent}  H1: \"{_truncate(content)}\"")
            continue

        if tag in ("h2", "h3"):
            heading_text = _truncate(content, 50)
            if heading_text:
                marker = "SECTION" if tag == "h2" else "SUB"
                out.append(f"\n[{marker}: {heading_text}]")
                out.append(f"  {tag.upper()}: \"{_truncate(content)}\"")
            continue

        if tag in ("h4", "h5", "h6") and content:
            out.append(f"  {tag.upper()}: \"{_truncate(content, 60)}\"")
            continue

        # ── Images ──
        if tag == "img":
            img_data = image_map.get(attrs.get("src"))
            img_text = _format_image(attrs, img_data)
            if img_text:
                out.append(f"  {img_text}")
            continue

        if tag == "video":
            poster = attrs.get("poster", "")
            if poster:
                fn = _extract_filename(poster)
                out.append(f"  VIDEO: poster={fn or poster[:40]}")
            else:
                out.append(f"  VIDEO")
            continue

        # ── Forms ──
        if tag == "form":
            action = attrs.get("action", "")
            out.append(f"\n[FORM: {action or 'submit'}]")
            continue

        # ── Links / CTAs ──
        if tag == "a" and content:
            href = attrs.get("href", "")
            if href and href not in ("#", ""):
                classes = attrs.get("class", "")
                if isinstance(classes, list):
                    classes = " ".join(classes)
                is_button = any(kw in str(classes).lower() for kw in ["btn", "button", "cta", "elementor-button"])
                prefix = "CTA" if is_button else "LINK"
                out.append(f"  {prefix}: \"{_truncate(content, 40)}\" → {href}")
            continue

        # ── Lists ──
        if tag in ("ul", "ol"):
            continue
        if tag == "li" and content:
            out.append(f"  - \"{_truncate(content, 80)}\"")
            continue

        # ── Paragraphs ──
        if tag in ("p", "blockquote", "span") and content and len(content) > 3:
            if not compact:
                if not (content.startswith(".") or content.startswith("#") or content.startswith("ast-")):
                    out.append(f"  P: \"{_truncate(content)}\"")
            continue

    # ── Footer section ──
    if footer_block_ids:
        out.append(f"\n[FOOTER]")
        for b in blocks:
            bid = b.get("id")
            if not bid or bid not in footer_block_ids:
                continue
            tag = (b.get("tag_name") or "").lower()
            content = (b.get("content") or "").strip()
            attrs = _parse_attrs(b)

            if tag == "footer":
                continue

            if tag in ("h2", "h3") and content:
                out.append(f"\n  [{tag.upper()}: {_truncate(content, 40)}]")
                continue
            if tag == "p" and content and not compact:
                if not (content.startswith("©") and len(content) < 5):
                    out.append(f"  P: \"{_truncate(content, 100)}\"")
                continue
            if tag == "a" and content:
                href = attrs.get("href", "")
                if href and href != "#":
                    out.append(f"  LINK: \"{_truncate(content, 30)}\" → {href}")
                continue

    # ── Primary CTAs from links table ──
    primary_ctas = [l for l in links if l.get("is_primary")]
    if primary_ctas:
        out.append("\n[PRIMARY CTAs]")
        for cta in primary_ctas:
            out.append(f"  🔥 \"{cta.get('text', '?')}\" → {cta.get('url', '?')}")

    return "\n".join(out)
