import os
import time
import threading
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

url: str = os.environ.get("SUPABASE_URL", "")
key: str = os.environ.get("SUPABASE_KEY", "")

_thread_local = threading.local()


def get_supabase() -> Client:
    """Return a thread-isolated Supabase client to prevent SSL socket collisions across parallel workers."""
    if not hasattr(_thread_local, "client") or _thread_local.client is None:
        supabase_url = os.environ.get("SUPABASE_URL") or url
        supabase_key = os.environ.get("SUPABASE_KEY") or key
        if not supabase_url or not supabase_key:
            load_dotenv(override=True)
            supabase_url = os.environ.get("SUPABASE_URL", "")
            supabase_key = os.environ.get("SUPABASE_KEY", "")

        if supabase_url and supabase_key:
            try:
                _thread_local.client = create_client(supabase_url, supabase_key)
            except Exception as e:
                print(f"Failed to create thread Supabase client: {e}", flush=True)
                return None
        else:
            print("ERROR: SUPABASE_URL or SUPABASE_KEY missing in runtime environment!", flush=True)
            return None
    return _thread_local.client


class _SupabaseProxy:
    """Proxy so all existing 'supabase.table(...)' or 'supabase.storage' calls automatically use thread-local client."""
    def __getattr__(self, name):
        client = get_supabase()
        if client is None:
            return None
        return getattr(client, name)


supabase = _SupabaseProxy()
STORAGE_BUCKET = "website-images"


def _safe_exec(query_builder, max_retries=3):
    """Execute query with automatic retry on SSL/connection drops across threads."""
    for attempt in range(max_retries):
        try:
            return query_builder.execute()
        except Exception as e:
            err_str = str(e).lower()
            if "ssl" in err_str or "eof" in err_str or "closed" in err_str or "connection" in err_str:
                if attempt < max_retries - 1:
                    # Reset thread client for a clean socket
                    _thread_local.client = None
                    time.sleep(0.4 * (attempt + 1))
                    continue
            raise e


# --- Sites ---
def get_all_sites():
    client = get_supabase()
    if not client: return []
    try:
        response = _safe_exec(client.table("sites").select("*").order("created_at", desc=True))
        return response.data or []
    except Exception as e:
        print(f"Error fetching sites: {e}")
        return []


def upsert_site(domain, name, openai_model="gpt-5.4-nano", business_context="", predefined_categories=None):
    client = get_supabase()
    if not client: return None
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
        existing = _safe_exec(client.table("sites").select("id").eq("domain", domain))
        if existing.data and len(existing.data) > 0:
            data["id"] = existing.data[0]["id"]
            try:
                response = _safe_exec(client.table("sites").update(data).eq("id", existing.data[0]["id"]))
            except Exception:
                data = _clean_site(data)
                response = _safe_exec(client.table("sites").update(data).eq("id", existing.data[0]["id"]))
        else:
            try:
                response = _safe_exec(client.table("sites").insert(data))
            except Exception:
                data = _clean_site(data)
                response = _safe_exec(client.table("sites").insert(data))
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error upserting site: {e}")
        return None


def get_site(site_id):
    client = get_supabase()
    if not client: return None
    try:
        response = _safe_exec(client.table("sites").select("*").eq("id", site_id))
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error fetching site: {e}")
        return None


def delete_site(site_id):
    client = get_supabase()
    if not client: return False
    try:
        _safe_exec(client.table("sites").delete().eq("id", site_id))
        return True
    except Exception as e:
        print(f"Error deleting site: {e}")
        return False


# --- Categories ---
def upsert_category(site_id, name, slug, description="", summary="", target_audience="", usps=None, order_index=0):
    client = get_supabase()
    if not client: return None
    data = {
        "site_id": site_id,
        "name": name,
        "slug": slug,
        "description": description,
        "order_index": order_index
    }
    if summary: data["summary"] = summary
    if target_audience: data["target_audience"] = target_audience
    if usps: data["usps"] = usps

    try:
        existing = _safe_exec(client.table("categories").select("id").eq("site_id", site_id).eq("name", name))
        if existing.data and len(existing.data) > 0:
            data["id"] = existing.data[0]["id"]
            response = _safe_exec(client.table("categories").update(data).eq("id", existing.data[0]["id"]))
        else:
            response = _safe_exec(client.table("categories").insert(data))
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error upserting category ({name}): {e}")
        return None


def update_category_synthesis(category_id, summary, target_audience, usps):
    client = get_supabase()
    if not client: return None
    data = {
        "summary": summary,
        "target_audience": target_audience,
        "usps": usps or []
    }
    try:
        response = _safe_exec(client.table("categories").update(data).eq("id", category_id))
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error updating category synthesis: {e}")
        return None


def get_site_categories(site_id):
    client = get_supabase()
    if not client: return []
    try:
        response = _safe_exec(client.table("categories").select("*").eq("site_id", site_id).order("order_index"))
        return response.data or []
    except Exception as e:
        print(f"Error fetching categories: {e}")
        return []


def get_category(category_id):
    client = get_supabase()
    if not client: return None
    try:
        response = _safe_exec(client.table("categories").select("*").eq("id", category_id))
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error fetching category: {e}")
        return None


# --- Pages ---
def upsert_page(site_id, url_str, path, title="", meta_description="", page_type="", category_id=None, scrape_instructions="", status="pending", raw_markdown="", screenshot_url=None):
    client = get_supabase()
    if not client: return None
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
        existing = _safe_exec(client.table("pages").select("id").eq("site_id", site_id).eq("url", url_str))
        if existing.data and len(existing.data) > 0:
            data["id"] = existing.data[0]["id"]
            try:
                response = _safe_exec(client.table("pages").update(data).eq("id", existing.data[0]["id"]))
            except Exception:
                data = _clean_page_data(data)
                response = _safe_exec(client.table("pages").update(data).eq("id", existing.data[0]["id"]))
        else:
            try:
                response = _safe_exec(client.table("pages").insert(data))
            except Exception:
                data = _clean_page_data(data)
                response = _safe_exec(client.table("pages").insert(data))
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error upserting page ({path}): {e}")
        return None


def get_page(page_id):
    client = get_supabase()
    if not client: return None
    try:
        try:
            response = _safe_exec(client.table("pages").select("*, categories(name, slug)").eq("id", page_id))
            return response.data[0] if response.data else None
        except Exception:
            response = _safe_exec(client.table("pages").select("*").eq("id", page_id))
            return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error fetching page: {e}")
        return None


def get_site_pages(site_id):
    client = get_supabase()
    if not client: return []
    try:
        try:
            response = _safe_exec(client.table("pages").select("*, categories(name, slug)").eq("site_id", site_id).order("path"))
            return response.data or []
        except Exception:
            response = _safe_exec(client.table("pages").select("*").eq("site_id", site_id).order("path"))
            return response.data or []
    except Exception as e:
        print(f"Error fetching site pages: {e}")
        return []


# --- Content Blocks ---
def delete_page_blocks(page_id):
    client = get_supabase()
    if not client: return False
    try:
        _safe_exec(client.table("content_blocks").delete().eq("page_id", page_id))
        return True
    except Exception as e:
        print(f"Error deleting blocks: {e}")
        return False


def insert_content_blocks(blocks):
    client = get_supabase()
    if not client or not blocks: return []
    chunk_size = 50
    for i in range(0, len(blocks), chunk_size):
        chunk = blocks[i:i + chunk_size]
        try:
            _safe_exec(client.table("content_blocks").insert(chunk))
        except Exception:
            cleaned_chunk = [{k: v for k, v in b.items() if k not in ["category_id", "section_type"]} for b in chunk]
            try:
                _safe_exec(client.table("content_blocks").insert(cleaned_chunk))
            except Exception as e2:
                print(f"Error inserting block chunk: {e2}")
    return blocks


def get_page_blocks(page_id):
    client = get_supabase()
    if not client: return []
    try:
        response = _safe_exec(client.table("content_blocks").select("*").eq("page_id", page_id).order("order_index"))
        return response.data or []
    except Exception as e:
        print(f"Error fetching blocks: {e}")
        return []


# --- Images ---
def delete_page_images(page_id):
    client = get_supabase()
    if not client: return False
    try:
        _safe_exec(client.table("images").delete().eq("page_id", page_id))
        return True
    except Exception as e:
        print(f"Error deleting images: {e}")
        return False


def insert_images(images):
    client = get_supabase()
    if not client or not images: return []
    chunk_size = 50
    for i in range(0, len(images), chunk_size):
        chunk = images[i:i + chunk_size]
        try:
            _safe_exec(client.table("images").insert(chunk))
        except Exception:
            cleaned_chunk = [{k: v for k, v in img.items() if k != "category_id"} for img in chunk]
            try:
                _safe_exec(client.table("images").insert(cleaned_chunk))
            except Exception as e2:
                print(f"Error inserting images: {e2}")
    return images


def get_page_images(page_id):
    client = get_supabase()
    if not client: return []
    try:
        response = _safe_exec(client.table("images").select("*").eq("page_id", page_id))
        return response.data or []
    except Exception as e:
        print(f"Error fetching images: {e}")
        return []


# --- Navigation ---
def upsert_navigation(site_id, menu_type, items):
    client = get_supabase()
    if not client: return None
    data = {
        "site_id": site_id,
        "menu_type": menu_type,
        "items": items or []
    }
    try:
        existing = _safe_exec(client.table("navigation").select("id").eq("site_id", site_id).eq("menu_type", menu_type))
        if existing.data and len(existing.data) > 0:
            response = _safe_exec(client.table("navigation").update(data).eq("id", existing.data[0]["id"]))
        else:
            response = _safe_exec(client.table("navigation").insert(data))
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error upserting navigation: {e}")
        return None


def get_site_navigation(site_id):
    client = get_supabase()
    if not client: return []
    try:
        response = _safe_exec(client.table("navigation").select("*").eq("site_id", site_id))
        return response.data or []
    except Exception as e:
        print(f"Error fetching navigation: {e}")
        return []


# --- Page Links ---
def delete_page_links(page_id):
    client = get_supabase()
    if not client: return False
    try:
        _safe_exec(client.table("page_links").delete().eq("page_id", page_id))
        return True
    except Exception as e:
        print(f"Error deleting page links: {e}")
        return False


def insert_page_links(links):
    client = get_supabase()
    if not client or not links: return []
    chunk_size = 50
    for i in range(0, len(links), chunk_size):
        chunk = links[i:i + chunk_size]
        try:
            _safe_exec(client.table("page_links").insert(chunk))
        except Exception as e:
            print(f"Error inserting page links: {e}")
    return links


def get_page_links(page_id):
    client = get_supabase()
    if not client: return []
    try:
        response = _safe_exec(client.table("page_links").select("*").eq("page_id", page_id))
        return response.data or []
    except Exception as e:
        print(f"Error fetching page links: {e}")
        return []


# --- Supabase Storage for Images & Screenshots ---
_bucket_checked = False

def ensure_storage_bucket():
    global _bucket_checked
    if _bucket_checked:
        return True
    client = get_supabase()
    if not client: return False
    try:
        buckets = _safe_exec(client.storage.list_buckets())
        bucket_names = [b.name for b in buckets] if buckets else []
        if STORAGE_BUCKET not in bucket_names:
            client.storage.create_bucket(STORAGE_BUCKET, options={"public": True})
        _bucket_checked = True
        return True
    except Exception:
        _bucket_checked = True
        return True


def upload_image_to_storage(file_bytes, storage_path, content_type="image/jpeg"):
    client = get_supabase()
    if not client or not file_bytes:
        return None
    ensure_storage_bucket()
    try:
        client.storage.from_(STORAGE_BUCKET).upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        public_url = client.storage.from_(STORAGE_BUCKET).get_public_url(storage_path)
        return public_url
    except Exception as e:
        print(f"Error uploading image to Supabase Storage ({storage_path}): {e}")
        return None
