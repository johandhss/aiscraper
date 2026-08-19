import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

url: str = os.environ.get("SUPABASE_URL", "")
key: str = os.environ.get("SUPABASE_KEY", "")

supabase: Client = None
if url and key:
    try:
        supabase = create_client(url, key)
    except Exception as e:
        print(f"Failed to initialize Supabase client: {e}")
else:
    print("Warning: Supabase credentials not found in environment.")

STORAGE_BUCKET = "website-images"


def get_all_sites():
    if not supabase: return []
    try:
        response = supabase.table("sites").select("*").order("created_at", desc=True).execute()
        return response.data or []
    except Exception as e:
        print(f"Error fetching sites: {e}")
        return []


def upsert_site(domain, name, openai_model="gpt-5.4-nano", business_context="", predefined_categories=None):
    if not supabase: return None
    data = {
        "domain": domain,
        "name": name,
        "openai_model": openai_model,
        "business_context": business_context or "",
        "predefined_categories": predefined_categories or []
    }
    
    def _clean_site(d):
        d_copy = dict(d)
        d_copy.pop("business_context", None)
        d_copy.pop("predefined_categories", None)
        d_copy.pop("openai_model", None)
        return d_copy

    try:
        existing = supabase.table("sites").select("id").eq("domain", domain).execute()
        if existing.data and len(existing.data) > 0:
            data["id"] = existing.data[0]["id"]
            try:
                response = supabase.table("sites").update(data).eq("id", existing.data[0]["id"]).execute()
            except Exception:
                data = _clean_site(data)
                response = supabase.table("sites").update(data).eq("id", existing.data[0]["id"]).execute()
        else:
            try:
                response = supabase.table("sites").insert(data).execute()
            except Exception:
                data = _clean_site(data)
                response = supabase.table("sites").insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error upserting site: {e}")
        return None


def get_site(site_id):
    if not supabase: return None
    try:
        response = supabase.table("sites").select("*").eq("id", site_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error fetching site: {e}")
        return None


def delete_site(site_id):
    if not supabase: return False
    try:
        supabase.table("sites").delete().eq("id", site_id).execute()
        return True
    except Exception as e:
        print(f"Error deleting site: {e}")
        return False


# --- Categories ---
def upsert_category(site_id, name, slug, description="", summary="", target_audience="", usps=None, order_index=0):
    if not supabase: return None
    data = {
        "site_id": site_id,
        "name": name,
        "slug": slug,
        "description": description or "",
        "summary": summary or "",
        "target_audience": target_audience or "",
        "usps": usps or [],
        "order_index": order_index
    }
    try:
        existing = supabase.table("categories").select("id").eq("site_id", site_id).eq("name", name).execute()
        if existing.data and len(existing.data) > 0:
            data["id"] = existing.data[0]["id"]
            response = supabase.table("categories").update(data).eq("id", existing.data[0]["id"]).execute()
        else:
            response = supabase.table("categories").insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error upserting category ({name}): {e}")
        return None


def update_category_synthesis(category_id, summary, target_audience="", usps=None):
    if not supabase or not category_id: return None
    data = {
        "summary": summary or "",
        "target_audience": target_audience or "",
        "usps": usps or []
    }
    try:
        response = supabase.table("categories").update(data).eq("id", category_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error updating category synthesis ({category_id}): {e}")
        return None


def get_site_categories(site_id):
    if not supabase: return []
    try:
        response = supabase.table("categories").select("*").eq("site_id", site_id).order("order_index").execute()
        return response.data or []
    except Exception as e:
        print(f"Error fetching categories: {e}")
        return []


def get_category(category_id):
    if not supabase or not category_id: return None
    try:
        response = supabase.table("categories").select("*").eq("id", category_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error fetching category: {e}")
        return None


def upsert_page(site_id, url_str, path, title="", meta_description="", page_type="", category_id=None, scrape_instructions="", status="pending", raw_markdown="", screenshot_url=None):
    if not supabase: return None
    data = {
        "site_id": site_id,
        "url": url_str,
        "path": path,
        "status": status,
    }
    if title is not None: data["title"] = title
    if meta_description is not None: data["meta_description"] = meta_description
    if page_type is not None: data["page_type"] = page_type
    if category_id is not None: data["category_id"] = category_id
    if scrape_instructions is not None: data["scrape_instructions"] = scrape_instructions
    if raw_markdown is not None: data["raw_markdown"] = raw_markdown
    if screenshot_url is not None: data["screenshot_url"] = screenshot_url

    def _clean_page_data(d):
        d_copy = dict(d)
        d_copy.pop("page_type", None)
        d_copy.pop("category_id", None)
        d_copy.pop("scrape_instructions", None)
        return d_copy

    try:
        existing = supabase.table("pages").select("id").eq("site_id", site_id).eq("url", url_str).execute()
        if existing.data and len(existing.data) > 0:
            data["id"] = existing.data[0]["id"]
            try:
                response = supabase.table("pages").update(data).eq("id", existing.data[0]["id"]).execute()
            except Exception:
                data = _clean_page_data(data)
                response = supabase.table("pages").update(data).eq("id", existing.data[0]["id"]).execute()
        else:
            try:
                response = supabase.table("pages").insert(data).execute()
            except Exception:
                data = _clean_page_data(data)
                response = supabase.table("pages").insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error upserting page: {e}")
        return None


def get_page(page_id):
    if not supabase: return None
    try:
        response = supabase.table("pages").select("*, categories(name, slug)").eq("id", page_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        # Fallback without join
        try:
            response = supabase.table("pages").select("*").eq("id", page_id).execute()
            return response.data[0] if response.data else None
        except Exception:
            return None


def get_site_pages(site_id):
    if not supabase: return []
    try:
        response = supabase.table("pages").select("*, categories(name, slug)").eq("site_id", site_id).order("path").execute()
        return response.data or []
    except Exception as e:
        try:
            response = supabase.table("pages").select("*").eq("site_id", site_id).order("path").execute()
            return response.data or []
        except Exception:
            return []


# --- Content Blocks ---
def delete_page_blocks(page_id):
    if not supabase: return False
    try:
        supabase.table("content_blocks").delete().eq("page_id", page_id).execute()
        return True
    except Exception as e:
        print(f"Error deleting blocks: {e}")
        return False


def insert_content_blocks(blocks):
    if not supabase or not blocks: return []
    chunk_size = 100
    for i in range(0, len(blocks), chunk_size):
        chunk = blocks[i:i + chunk_size]
        try:
            supabase.table("content_blocks").insert(chunk).execute()
        except Exception as e:
            # Fallback if category_id or section_type missing
            cleaned_chunk = [{k: v for k, v in b.items() if k not in ["category_id", "section_type"]} for b in chunk]
            try:
                supabase.table("content_blocks").insert(cleaned_chunk).execute()
            except Exception as e2:
                print(f"Error inserting content blocks chunk: {e2}")
    return blocks


def get_page_blocks(page_id):
    if not supabase: return []
    try:
        response = supabase.table("content_blocks").select("*").eq("page_id", page_id).order("order_index").execute()
        return response.data or []
    except Exception as e:
        print(f"Error fetching blocks: {e}")
        return []


# --- Images ---
def delete_page_images(page_id):
    if not supabase: return False
    try:
        supabase.table("images").delete().eq("page_id", page_id).execute()
        return True
    except Exception as e:
        print(f"Error deleting images: {e}")
        return False


def insert_images(images):
    if not supabase or not images: return []
    chunk_size = 50
    for i in range(0, len(images), chunk_size):
        chunk = images[i:i + chunk_size]
        try:
            supabase.table("images").insert(chunk).execute()
        except Exception as e:
            cleaned_chunk = [{k: v for k, v in img.items() if k != "category_id"} for img in chunk]
            try:
                supabase.table("images").insert(cleaned_chunk).execute()
            except Exception as e2:
                print(f"Error inserting images chunk: {e2}")
    return images


def get_page_images(page_id):
    if not supabase: return []
    try:
        response = supabase.table("images").select("*").eq("page_id", page_id).execute()
        return response.data or []
    except Exception as e:
        print(f"Error fetching images: {e}")
        return []


# --- Navigation ---
def upsert_navigation(site_id, menu_type, items):
    if not supabase: return None
    try:
        existing = supabase.table("navigation").select("id").eq("site_id", site_id).eq("menu_type", menu_type).execute()
        data = {"site_id": site_id, "menu_type": menu_type, "items": items}
        if existing.data and len(existing.data) > 0:
            response = supabase.table("navigation").update(data).eq("id", existing.data[0]["id"]).execute()
        else:
            response = supabase.table("navigation").insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error upserting navigation: {e}")
        return None


def get_site_navigation(site_id):
    if not supabase: return []
    try:
        response = supabase.table("navigation").select("*").eq("site_id", site_id).execute()
        return response.data or []
    except Exception as e:
        print(f"Error fetching navigation: {e}")
        return []


# --- Page Links / CTAs ---
def delete_page_links(page_id):
    if not supabase: return False
    try:
        supabase.table("page_links").delete().eq("page_id", page_id).execute()
        return True
    except Exception as e:
        print(f"Error deleting links: {e}")
        return False


def insert_page_links(links):
    if not supabase or not links: return []
    chunk_size = 50
    for i in range(0, len(links), chunk_size):
        chunk = links[i:i + chunk_size]
        try:
            supabase.table("page_links").insert(chunk).execute()
        except Exception as e:
            print(f"Error inserting page links chunk: {e}")
    return links


def get_page_links(page_id):
    if not supabase: return []
    try:
        response = supabase.table("page_links").select("*").eq("page_id", page_id).execute()
        return response.data or []
    except Exception as e:
        print(f"Error fetching page links: {e}")
        return []


# --- Supabase Storage Image Upload ---
_bucket_ensured = False

def ensure_storage_bucket():
    global _bucket_ensured
    if _bucket_ensured or not supabase:
        return
    try:
        buckets = supabase.storage.list_buckets()
        existing_names = [b.name for b in buckets] if buckets else []
        if STORAGE_BUCKET not in existing_names:
            supabase.storage.create_bucket(STORAGE_BUCKET, options={"public": True})
        _bucket_ensured = True
    except Exception as e:
        _bucket_ensured = True
        pass


def upload_image_to_storage(file_bytes, storage_path, content_type="image/jpeg"):
    if not supabase or not file_bytes:
        return None
    ensure_storage_bucket()
    try:
        supabase.storage.from_(STORAGE_BUCKET).upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        public_url = supabase.storage.from_(STORAGE_BUCKET).get_public_url(storage_path)
        return public_url
    except Exception as e:
        print(f"Error uploading image to Supabase Storage ({storage_path}): {e}")
        return None
