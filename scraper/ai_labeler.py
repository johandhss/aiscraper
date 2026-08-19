import os
import json
import re
import sys
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


def get_openai_client(api_key=None):
    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return None
    try:
        # Strict 15s timeout and max 1 retry to prevent infinite hanging
        return OpenAI(api_key=key, timeout=15.0, max_retries=1)
    except Exception as e:
        print(f"[AI] Error creating OpenAI client: {e}", flush=True)
        return None


def get_available_models(api_key=None):
    default_models = [
        {"id": "gpt-5.4-nano", "name": "GPT-5.4 Nano (Next-Gen Ultra-Fast & Efficient)"},
        {"id": "gpt-5-nano", "name": "GPT-5 Nano"},
        {"id": "gpt-5-mini", "name": "GPT-5 Mini"},
        {"id": "gpt-5", "name": "GPT-5 (Flagship Reasoning & Layout Analysis)"},
        {"id": "gpt-5-turbo", "name": "GPT-5 Turbo"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini (Recommended Default)"},
        {"id": "gpt-4o", "name": "GPT-4o"},
        {"id": "gpt-4.5-preview", "name": "GPT-4.5 Preview"},
        {"id": "o3-mini", "name": "o3-mini (High Reasoning)"},
        {"id": "o1-mini", "name": "o1-mini"},
        {"id": "gpt-4.1-turbo", "name": "GPT-4.1 Turbo"},
        {"id": "gpt-4-turbo", "name": "GPT-4 Turbo"},
    ]

    client = get_openai_client(api_key)
    if not client:
        return default_models

    try:
        models_response = client.models.list(timeout=8.0)
        all_ids = [m.id for m in models_response.data]
        
        matching = []
        priority_prefixes = [
            "gpt-5.4", "gpt-5", "gpt-5-nano", "gpt-5-mini", "gpt-5-turbo",
            "gpt-4o-mini", "gpt-4o", "gpt-4.5", "o3-mini", "o3", "o1-mini", "o1",
            "gpt-4.1", "gpt-4-turbo", "gpt-3.5-turbo"
        ]
        added = set()
        
        for dm in default_models:
            if dm["id"] in all_ids:
                matching.append(dm)
                added.add(dm["id"])

        for pref in priority_prefixes:
            for mid in all_ids:
                if mid.startswith(pref) and mid not in added:
                    matching.append({"id": mid, "name": mid})
                    added.add(mid)

        for dm in default_models:
            if dm["id"] not in added:
                matching.append(dm)
                added.add(dm["id"])

        if matching:
            return matching
        return default_models
    except Exception as e:
        print(f"[AI] Error fetching OpenAI models: {e}", flush=True)
        return default_models


def _heuristic_match_categories(pages_list, predefined_categories):
    synonym_map = {
        "event": ["event", "events", "evenement", "evenementen", "feest", "feesten", "congres", "vergader", "vergaderen", "workshop", "workshops", "bijeenkomst", "party", "meeting", "bruiloft", "trouw", "borrel", "diner"],
        "evenement": ["event", "events", "evenement", "evenementen", "feest", "feesten", "congres", "vergader", "vergaderen", "workshop", "workshops", "bijeenkomst", "party", "meeting", "bruiloft", "trouw", "borrel", "diner"],
        "studio": ["studio", "studios", "studio's", "bandstudio", "foyer", "zaal", "opname", "opnamestudio", "fotostudio", "filmstudio", "repetitieruimte", "oefenruimte", "alle-studios"],
        "dienst": ["dienst", "diensten", "service", "services", "wat-we-doen", "aanbod", "oplossingen", "solutions"],
        "portfolio": ["portfolio", "project", "projecten", "cases", "werk", "impressie", "galerij", "gallery", "foto's"],
        "over ons": ["over", "about", "over-ons", "wie-zijn-wij", "team", "ons-verhaal", "geschiedenis", "mestudio"],
        "contact": ["contact", "offerte", "afspraak", "route", "locatie", "bereikbaarheid", "tarieven", "prijzen"],
        "blog": ["blog", "blogs", "nieuws", "updates", "artikelen", "kennisbank"]
    }

    matches = {}
    for p in pages_list:
        combined = f"{p.get('path', '')} {p.get('title', '')} {p.get('h1', '')}".lower()
        
        path_clean = p.get("path", "").strip("/")
        if not path_clean:
            for c in predefined_categories:
                if c.lower() in ["hoofdpagina", "home", "homepage", "algemeen"]:
                    matches[p["url"]] = c
                    break
            if p["url"] in matches:
                continue

        best_cat = None
        highest_score = 0

        for cat in predefined_categories:
            cat_lower = cat.lower().strip()
            score = 0

            for word in re.findall(r"\w+", cat_lower):
                if len(word) > 2 and word in combined:
                    score += 5

            for key, syns in synonym_map.items():
                if key in cat_lower or any(s == cat_lower for s in syns):
                    for syn in syns:
                        if syn in combined:
                            score += 3

            if score > highest_score:
                highest_score = score
                best_cat = cat

        if best_cat and highest_score > 0:
            matches[p["url"]] = best_cat
        else:
            matches[p["url"]] = predefined_categories[0]

    return matches


def match_pages_to_categories(pages_list, predefined_categories, business_context="", model="gpt-5.4-nano", api_key=None):
    if not predefined_categories:
        return {p["url"]: "Algemeen" for p in pages_list}

    client = get_openai_client(api_key)
    if not client:
        return _heuristic_match_categories(pages_list, predefined_categories)

    system_prompt = f"""You are an expert website taxonomist. The website belongs to a business with these core categories/pillars:
{json.dumps(predefined_categories)}

Business Context: {business_context or "Not specified"}

For each page, look at its path, title, and H1, and assign the single best matching category from the predefined list above.
Return JSON:
{{"matches": [{{"url": "...", "category": "..."}}]}}
"""

    payload = [
        {
            "url": p["url"],
            "path": p.get("path", ""),
            "title": p.get("title", ""),
            "h1": p.get("h1", "")
        }
        for p in pages_list[:40]
    ]

    target_model = model or "gpt-4o-mini"

    def _call_openai(mod):
        res = client.chat.completions.create(
            model=mod,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload)}
            ],
            temperature=0.1,
            timeout=12.0
        )
        res_data = json.loads(res.choices[0].message.content)
        return {item["url"]: item["category"] for item in res_data.get("matches", [])}

    try:
        return _call_openai(target_model)
    except Exception as e:
        print(f"[AI Match] Fallback to gpt-4o-mini due to {e}", flush=True)
        try:
            return _call_openai("gpt-4o-mini")
        except Exception as e2:
            print(f"[AI Match] Fallback to heuristics due to {e2}", flush=True)
            return _heuristic_match_categories(pages_list, predefined_categories)


def generate_category_synthesis(category_name, category_content_list, business_context="", model="gpt-5.4-nano", api_key=None):
    client = get_openai_client(api_key)
    if not client or not category_content_list:
        return {
            "summary": f"Overzicht en content voor {category_name}.",
            "target_audience": "Bezoekers en potentiële klanten geïnteresseerd in " + category_name,
            "usps": [f"Gespecialiseerd aanbod binnen {category_name}"]
        }

    system_prompt = f"""You are a senior business analyst and content architect.
Analyze all scraped webpage contents that belong to the business category: '{category_name}'.
Business Context: {business_context or "Not specified"}

Create a structured overview of this business pillar so another LLM can build a brand new website for it.
Include:
1. 'summary': 2 paragraph synthesis of offerings & specifications.
2. 'target_audience': Clear description of target group.
3. 'usps': Array of 4 key highlights/USPs.

Return JSON:
{{
  "summary": "...",
  "target_audience": "...",
  "usps": ["USP 1", "USP 2", "USP 3", "USP 4"]
}}
"""

    snippets = []
    for p in category_content_list[:5]:
        snippets.append(f"Page [{p.get('title', '')}] ({p.get('path', '')}):\n{(p.get('raw_markdown', '') or '')[:800]}")

    combined_text = "\n\n---\n\n".join(snippets)
    target_model = model or "gpt-4o-mini"

    def _call_synthesis(mod):
        response = client.chat.completions.create(
            model=mod,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": combined_text[:6000]}
            ],
            temperature=0.2,
            timeout=14.0
        )
        return json.loads(response.choices[0].message.content)

    try:
        return _call_synthesis(target_model)
    except Exception as e:
        print(f"[AI Synthesis] Fallback to gpt-4o-mini: {e}", flush=True)
        try:
            return _call_synthesis("gpt-4o-mini")
        except Exception:
            return {
                "summary": f"Aanbod en specificaties voor {category_name}.",
                "target_audience": "Klanten van " + category_name,
                "usps": ["Kwalitatief aanbod", "Professionele service", "Moderne faciliteiten"]
            }


def classify_page_semantics(page_url, page_title, page_type, scrape_instructions,
                            sections_data, images_data, links_data, category_name="Algemeen",
                            model="gpt-5.4-nano", api_key=None):
    client = get_openai_client(api_key)
    if not client:
        return _heuristic_classification(sections_data, images_data, links_data)

    # Filter to most significant sections to keep prompt lightweight & fast
    significant_sections = []
    for s in sections_data:
        tag = (s.get("tag_name") or "").lower()
        if tag in ["header", "nav", "footer", "section", "article", "main", "h1", "h2", "h3"] or len(s.get("content") or "") > 20:
            significant_sections.append({
                "block_id": s.get("id"),
                "tag": s.get("tag_name"),
                "path": s.get("section_path"),
                "snippet": (s.get("content") or "")[:120]
            })
            if len(significant_sections) >= 25:
                break

    prompt_payload = {
        "url": page_url,
        "title": page_title,
        "category": category_name,
        "type": page_type or "general",
        "instructions": scrape_instructions or "None",
        "sections": significant_sections,
        "images": [
            {
                "id": img.get("id"),
                "alt": img.get("alt_text", "")[:60],
                "url": img.get("original_url", "")[-40:],
                "ctx": img.get("section_context", "")[:40]
            }
            for img in images_data[:15]
        ],
        "links": [
            {
                "id": l.get("id"),
                "text": l.get("text", "")[:40],
                "url": l.get("url", "")[-40:]
            }
            for l in links_data[:20]
        ]
    }

    system_prompt = """You are a web semantics classifier. Classify sections, images, and CTAs.
section_types: ['hero', 'services', 'about', 'pricing', 'testimonials', 'contact', 'cta', 'faq', 'team', 'portfolio', 'header', 'nav', 'footer', 'content']
image_types: ['hero_image', 'logo', 'team_photo', 'icon', 'portfolio_item', 'background', 'content_image']

Return JSON:
{
  "sections": [{"block_id": "uuid", "section_type": "hero"}],
  "images": [{"image_id": "uuid", "image_type": "hero_image"}],
  "links": [{"link_id": "uuid", "link_type": "cta_button", "is_primary": true}]
}"""

    target_model = model or "gpt-4o-mini"

    def _call_classify(mod):
        response = client.chat.completions.create(
            model=mod,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(prompt_payload)}
            ],
            temperature=0.1,
            timeout=12.0
        )
        return json.loads(response.choices[0].message.content)

    try:
        return _call_classify(target_model)
    except Exception as e:
        print(f"[AI Classify] Direct model failed ({e}), trying gpt-4o-mini...", flush=True)
        try:
            return _call_classify("gpt-4o-mini")
        except Exception as e2:
            print(f"[AI Classify] Falling back to heuristics ({e2})", flush=True)
            return _heuristic_classification(sections_data, images_data, links_data)


def _heuristic_classification(sections_data, images_data, links_data):
    section_map = []
    for s in sections_data:
        bid = s.get("id")
        tag = (s.get("tag_name") or "").lower()
        path = (s.get("section_path") or "").lower()
        content = (s.get("content") or "").lower()
        attrs = str(s.get("attributes") or "").lower()

        stype = "content"
        combined = f"{path} {content} {attrs}"

        if tag == "header" or "header" in attrs:
            stype = "header"
        elif tag == "nav" or "nav" in attrs or "menu" in attrs:
            stype = "nav"
        elif tag == "footer" or "footer" in attrs:
            stype = "footer"
        elif "hero" in combined or "banner" in combined or s.get("order_index", 999) <= 2 and tag in ["h1", "section"]:
            stype = "hero"
        elif any(k in combined for k in ["service", "dienst", "wat we doen", "what we do", "studio", "evenement", "event"]):
            stype = "services"
        elif any(k in combined for k in ["about", "over ons", "wie zijn wij", "team", "ons verhaal"]):
            stype = "about"
        elif any(k in combined for k in ["pricing", "prijzen", "tarieven", "kosten"]):
            stype = "pricing"
        elif any(k in combined for k in ["review", "testimonial", "ervaring", "klanten"]):
            stype = "testimonials"
        elif any(k in combined for k in ["contact", "neem contact", "bel ons", "offerte"]):
            stype = "contact"
        elif any(k in combined for k in ["faq", "veelgestelde", "vragen"]):
            stype = "faq"
        elif any(k in combined for k in ["portfolio", "projecten", "cases", "werk", "galerij", "impressie"]):
            stype = "portfolio"
        elif any(k in combined for k in ["cta", "call to action", "aanmelden", "start nu", "reserveren", "boeken"]):
            stype = "cta"

        section_map.append({"block_id": bid, "section_type": stype})

    image_map = []
    for img in images_data:
        iid = img.get("id")
        url = (img.get("original_url") or "").lower()
        alt = (img.get("alt_text") or "").lower()
        context = (img.get("section_context") or "").lower()
        w = img.get("width") or 0
        h = img.get("height") or 0

        itype = "content_image"
        if "logo" in url or "logo" in alt:
            itype = "logo"
        elif "icon" in url or "icon" in alt or (w > 0 and w <= 48 and h > 0 and h <= 48):
            itype = "icon"
        elif "hero" in url or "hero" in alt or "banner" in context or "hero" in context:
            itype = "hero_image"
        elif any(k in url or k in alt or k in context for k in ["team", "avatar", "person", "medewerker", "foto"]):
            itype = "team_photo"
        elif any(k in url or k in alt or k in context for k in ["portfolio", "project", "case", "galerij", "impressie"]):
            itype = "portfolio_item"

        image_map.append({"image_id": iid, "image_type": itype})

    link_map = []
    for l in links_data:
        lid = l.get("id")
        text = (l.get("text") or "").lower()
        url = (l.get("url") or "").lower()
        
        is_primary = False
        ltype = "internal_link"
        
        if url.startswith("http") and not url.startswith("/"):
            ltype = "external_link"
            
        if any(k in text for k in ["contact", "offerte", "afspraak", "start", "bel", "nu", "aanvragen", "koop", "order", "reserveren", "boeken"]):
            is_primary = True
            ltype = "cta_button"

        link_map.append({"link_id": lid, "link_type": ltype, "is_primary": is_primary})

    return {
        "sections": section_map,
        "images": image_map,
        "links": link_map
    }
