import io
import re
import uuid
import mimetypes
from urllib.parse import urljoin, urlparse
from PIL import Image
import cloudscraper
from scraper.db import upload_image_to_storage

_scraper = None

def _get_scraper():
    global _scraper
    if _scraper is None:
        _scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "darwin", "mobile": False}
        )
    return _scraper


def extract_best_url_from_srcset(srcset_str, base_url):
    """Pick the highest resolution image URL from a srcset attribute."""
    if not srcset_str:
        return None
    candidates = []
    for entry in srcset_str.split(","):
        parts = entry.strip().split()
        if not parts:
            continue
        url = parts[0]
        if url.startswith("data:"):
            continue
        width = 0
        if len(parts) > 1:
            m = re.search(r"(\d+)w", parts[1])
            if m:
                width = int(m.group(1))
        candidates.append((width, url))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return urljoin(base_url, candidates[0][1])
    return None


def resolve_image_source(img_element, base_url):
    """
    Examine all possible image source attributes in order of quality & lazy-load presence:
    data-lazy-srcset, srcset, data-lazy-src, data-src, data-original, data-full-url, src
    """
    if not img_element:
        return None, ""

    attrs = img_element.attrs if hasattr(img_element, "attrs") else img_element

    # 1. Check high-res srcsets
    for attr_name in ["data-lazy-srcset", "data-srcset", "srcset"]:
        srcset = attrs.get(attr_name)
        if srcset:
            best_url = extract_best_url_from_srcset(srcset, base_url)
            if best_url:
                return best_url, attrs.get("alt", "")

    # 2. Check direct high-res / lazy attributes
    for attr_name in ["data-lazy-src", "data-src", "data-original", "data-full-url", "data-hi-res-src", "src"]:
        src = attrs.get(attr_name)
        if src and isinstance(src, str) and not src.strip().startswith("data:"):
            full_url = urljoin(base_url, src.strip())
            return full_url, attrs.get("alt", "")

    return None, attrs.get("alt", "")


def process_and_upload_image(img_url, base_url, page_id, site_domain, alt_text="", section_context="", block_id=None, predefined_dims=None, upload_to_storage=True):
    """
    Download image, extract dimensions, upload to Supabase Storage (if requested), and return image metadata record.
    """
    if not img_url:
        return None

    full_url = urljoin(base_url, img_url).split("#")[0]
    
    if full_url.startswith("data:") or (len(full_url) < 200 and "svg" in full_url):
        return None

    image_id = str(uuid.uuid4())
    width = predefined_dims[0] if predefined_dims and predefined_dims[0] else None
    height = predefined_dims[1] if predefined_dims and predefined_dims[1] else None
    file_size = None
    public_url = full_url
    storage_path = None

    if upload_to_storage:
        try:
            scraper = _get_scraper()
            res = scraper.get(full_url, timeout=4)
            if res.status_code == 200 and len(res.content) > 0:
                file_bytes = res.content
                file_size = len(file_bytes)
                content_type = res.headers.get("Content-Type", "image/jpeg").split(";")[0]

                # Try to get dimensions with Pillow
                try:
                    with Image.open(io.BytesIO(file_bytes)) as pil_img:
                        width, height = pil_img.size
                        img_format = (pil_img.format or "JPEG").lower()
                        if not content_type or "octet" in content_type:
                            content_type = f"image/{img_format}"
                except Exception:
                    pass

                ext = mimetypes.guess_extension(content_type) or ".jpg"
                if ext == ".jpe": ext = ".jpg"

                storage_path = f"{site_domain}/{page_id}/{image_id}{ext}"
                
                uploaded_url = upload_image_to_storage(file_bytes, storage_path, content_type)
                if uploaded_url:
                    public_url = uploaded_url

        except Exception as e:
            pass

    return {
        "id": image_id,
        "page_id": page_id,
        "block_id": block_id,
        "original_url": full_url,
        "storage_path": storage_path,
        "public_url": public_url,
        "alt_text": alt_text or "",
        "image_type": "content_image",
        "width": width,
        "height": height,
        "file_size": file_size,
        "section_context": section_context or ""
    }
