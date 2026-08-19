import json
from scraper.db import (
    get_site, get_site_pages, get_site_categories, get_site_navigation,
    get_page, get_page_blocks, get_page_images, get_page_links
)


def build_site_knowledge_tree(site_id):
    """
    Extract and assemble the complete, high-density structured JSON specification
    for an entire website, including categories, navigation, pages, sections, media, and CTAs.
    """
    site = get_site(site_id)
    if not site:
        return None

    categories = get_site_categories(site_id)
    pages = get_site_pages(site_id)
    nav_menus = get_site_navigation(site_id)

    # Build category lookup
    cat_by_id = {c["id"]: c for c in categories}
    cat_pages_map = {c["name"]: [] for c in categories}

    pages_detail = []
    all_media_catalog = []

    for p in pages:
        p_id = p["id"]
        blocks = get_page_blocks(p_id)
        images = get_page_images(p_id)
        links = get_page_links(p_id)

        cat_info = cat_by_id.get(p.get("category_id"), {})
        cat_name = cat_info.get("name", "Algemeen")

        if cat_name in cat_pages_map:
            cat_pages_map[cat_name].append({
                "title": p.get("title") or p.get("path"),
                "path": p.get("path"),
                "type": p.get("page_type")
            })

        # Group content blocks by logical section
        sections = []
        current_section = None

        for b in blocks:
            stype = b.get("section_type") or "content"
            path_str = b.get("section_path") or ""
            
            # Start new section if heading or distinct section tag
            if b.get("tag_name") in ["h1", "h2", "section", "article", "header", "footer", "nav"] or current_section is None:
                if current_section:
                    sections.append(current_section)
                current_section = {
                    "section_type": stype,
                    "section_path": path_str,
                    "heading": b.get("content") if b.get("tag_name") in ["h1", "h2", "h3"] else "",
                    "content_blocks": [],
                    "images": [],
                    "ctas": []
                }
            
            if current_section:
                if b.get("content") and b.get("tag_name") not in ["h1", "h2"]:
                    current_section["content_blocks"].append({
                        "tag": b.get("tag_name"),
                        "text": b.get("content")
                    })

        if current_section:
            sections.append(current_section)

        # Match images to sections
        for img in images:
            img_entry = {
                "url": img.get("public_url") or img.get("original_url"),
                "original_url": img.get("original_url"),
                "alt": img.get("alt_text") or "",
                "type": img.get("image_type") or "content_image",
                "width": img.get("width"),
                "height": img.get("height"),
                "section_context": img.get("section_context") or "",
                "page_path": p.get("path")
            }
            all_media_catalog.append(img_entry)

        # Format links
        page_ctas = [
            {
                "label": l.get("text"),
                "url": l.get("url"),
                "is_primary": l.get("is_primary", False),
                "type": l.get("link_type")
            }
            for l in links
        ]

        pages_detail.append({
            "id": p_id,
            "path": p.get("path"),
            "url": p.get("url"),
            "title": p.get("title") or p.get("path"),
            "meta_description": p.get("meta_description") or "",
            "page_type": p.get("page_type") or "general_page",
            "category": cat_name,
            "screenshot_url": p.get("screenshot_url"),
            "scrape_instructions": p.get("scrape_instructions"),
            "sections_count": len(sections),
            "sections": sections,
            "images_count": len(images),
            "images": [
                {
                    "url": img.get("public_url") or img.get("original_url"),
                    "alt": img.get("alt_text"),
                    "type": img.get("image_type"),
                    "dimensions": f"{img.get('width')}x{img.get('height')}" if img.get("width") else None
                }
                for img in images
            ],
            "ctas": page_ctas,
            "raw_markdown_snippet": (p.get("raw_markdown") or "")[:2000]
        })

    # Assemble complete blueprint specification
    blueprint = {
        "meta": {
            "domain": site.get("domain"),
            "business_context": site.get("business_context") or "Not provided",
            "scraped_at": site.get("updated_at") or site.get("created_at"),
            "total_pages": len(pages),
            "total_images": len(all_media_catalog),
            "total_categories": len(categories)
        },
        "business_taxonomy": [
            {
                "name": c.get("name"),
                "slug": c.get("slug"),
                "summary": c.get("summary") or "",
                "target_audience": c.get("target_audience") or "",
                "usps": c.get("usps") or [],
                "pages": cat_pages_map.get(c.get("name"), [])
            }
            for c in categories
        ],
        "navigation_architecture": {
            menu.get("menu_type"): menu.get("items")
            for menu in nav_menus
        },
        "pages": pages_detail,
        "media_catalog": all_media_catalog
    }

    return blueprint


def generate_llm_master_prompt(site_id, framework="Next.js 14 (App Router) + Tailwind CSS"):
    """
    Generate an exhaustive, highly structured Master Prompt for Cursor / Claude 3.5 Sonnet / GPT-4o
    to rebuild the entire website using the selected frontend framework.
    """
    blueprint = build_site_knowledge_tree(site_id)
    if not blueprint:
        return "Site data not found."

    domain = blueprint["meta"]["domain"]
    business_context = blueprint["meta"]["business_context"]
    taxonomy = blueprint["business_taxonomy"]
    nav = blueprint["navigation_architecture"]
    pages = blueprint["pages"]
    media = blueprint["media_catalog"]

    prompt_lines = [
        f"# Master Website Rebuild Specification: `{domain}`",
        "",
        "## 1. System Role & Goal",
        f"You are an elite Lead Frontend Engineer and UX Architect. Your mission is to build a brand-new, production-ready, ultra-modern web application in **{framework}** for **{domain}**.",
        "You have been provided with the complete, structured content tree, media catalog (hosted on Supabase Storage CDN), navigation hierarchy, and business pillars extracted from the original website.",
        "",
        "## 2. Business Context & Taxonomy",
        f"**Business Context:** {business_context}",
        "",
        "### Core Business Pillars:",
    ]

    for cat in taxonomy:
        prompt_lines.append(f"#### 📁 {cat['name']} (`{cat['slug']}`)")
        if cat['summary']:
            prompt_lines.append(f"- **Summary:** {cat['summary']}")
        if cat['target_audience']:
            prompt_lines.append(f"- **Target Audience:** {cat['target_audience']}")
        if cat['usps']:
            prompt_lines.append(f"- **Key USPs:** {', '.join(cat['usps'])}")
        page_list_str = ", ".join([f"`{p['path']}`" for p in cat.get('pages', [])])
        prompt_lines.append(f"- **Assigned Routes:** {page_list_str or 'None'}")
        prompt_lines.append("")

    prompt_lines.extend([
        "## 3. Site Navigation & Routing Architecture",
        "Build the navigation components (Header navbar, dropdowns, and Footer) adhering to this hierarchy:",
        "```json",
        json.dumps(nav, indent=2),
        "```",
        "",
        "## 4. Complete Page-by-Page Specifications & Content Copy",
        "Rebuild each of the following routes with responsive, beautifully styled UI sections, exact copy, real CDN images, and interactive CTA buttons:",
        ""
    ])

    for p in pages:
        prompt_lines.append(f"### Route: `{p['path']}` ({p['title']})")
        prompt_lines.append(f"- **Page Type:** `{p['page_type']}` | **Category:** `{p['category']}`")
        if p['meta_description']:
            prompt_lines.append(f"- **Meta Description:** {p['meta_description']}")
        if p['screenshot_url']:
            prompt_lines.append(f"- **Visual Reference Screenshot:** [View Full-Page Capture]({p['screenshot_url']})")
        if p['scrape_instructions']:
            prompt_lines.append(f"- **Special Instructions:** {p['scrape_instructions']}")
        
        prompt_lines.append("\n**Key CTAs & Links:**")
        if p['ctas']:
            for cta in p['ctas']:
                primary_flag = "🔥 [PRIMARY CTA]" if cta.get('is_primary') else ""
                prompt_lines.append(f"- {primary_flag} Label: `\"{cta['label']}\"` &rarr; Target: `{cta['url']}` ({cta['type']})")
        else:
            prompt_lines.append("- Standard layout CTAs")

        prompt_lines.append("\n**Media / Images for this Page:**")
        if p['images']:
            for img in p['images']:
                dim_str = f" ({img['dimensions']})" if img.get('dimensions') else ""
                prompt_lines.append(f"- `![{img['alt'] or 'Image'}]({img['url']})`{dim_str} &mdash; Type: `{img['type']}`")
        else:
            prompt_lines.append("- No specific images recorded.")

        prompt_lines.append("\n**Extracted Sections & Copy:**")
        for s in p['sections']:
            stype = s['section_type']
            heading = s['heading'] or s['section_path'] or 'Content Section'
            prompt_lines.append(f"\n##### Section: `{stype}` &mdash; {heading}")
            for cb in s['content_blocks'][:6]:
                txt = cb['text'].replace("\n", " ").strip()
                if txt:
                    prompt_lines.append(f"> <{cb['tag']}> {txt[:200]}")

        prompt_lines.append("\n---\n")

    prompt_lines.extend([
        "## 5. Architectural & Design Guidelines",
        "1. **Modern UI/UX**: Use Tailwind CSS with modern dark/light styling, clean typography, glassmorphism accents, and responsive flex/grid layouts.",
        "2. **Real Assets**: Use the exact Supabase CDN image URLs listed above for all `<img>` tags and background banners.",
        "3. **Component Modularity**: Separate into reusable components (e.g. `Navbar`, `Footer`, `HeroSection`, `ServiceCard`, `CtaBanner`, `ImageGallery`, `ContactForm`).",
        "4. **SEO & Metadata**: Implement title, OpenGraph tags, and meta descriptions per route.",
        "",
        "Start by creating the project structure and scaffold all routes!"
    ])

    return "\n".join(prompt_lines)


def generate_single_page_prompt(page_id, framework="Next.js 14 + Tailwind CSS"):
    """Generate a single modular page rebuild prompt for focused, iterative development."""
    page = get_page(page_id)
    if not page:
        return "Page not found."

    blocks = get_page_blocks(page_id)
    images = get_page_images(page_id)
    links = get_page_links(page_id)

    title = page.get("title") or page.get("path")
    path = page.get("path")

    prompt = [
        f"# Page Rebuild Specification: `{path}` ({title})",
        f"**Target Framework:** {framework}",
        f"**Page Type:** {page.get('page_type', 'general_page')}",
        "",
        "## 1. Visual Reference",
        f"Screenshot Preview: {page.get('screenshot_url') or 'None'}",
        f"Meta Description: {page.get('meta_description') or 'None'}",
        "",
        "## 2. CTAs and Actions",
    ]

    for l in links:
        primary = "🔥 PRIMARY" if l.get("is_primary") else "LINK"
        prompt.append(f"- [{primary}] \"{l.get('text')}\" &rarr; `{l.get('url')}`")

    prompt.append("\n## 3. Images to Embed")
    for img in images:
        prompt.append(f"- `![{img.get('alt_text') or 'Image'}]({img.get('public_url') or img.get('original_url')})` ({img.get('image_type')})")

    prompt.append("\n## 4. Content Copy & Sections")
    prompt.append(page.get("raw_markdown") or "No raw markdown.")

    return "\n".join(prompt)
