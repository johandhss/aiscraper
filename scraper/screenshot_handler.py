import time
import re
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
from scraper.db import upload_image_to_storage


def capture_page_screenshot_and_media(page_url, page_id, site_domain):
    """
    Use Playwright to:
    1. Render the live page with full JavaScript execution.
    2. Deep-scroll the entire page to trigger ALL lazy-loaded images, animations & infinite scroll.
    3. Wait for images to fully load after scrolling.
    4. Capture a high-res full-page screenshot and upload to Supabase Storage.
    5. Extract all resolved, rendered <img> and background-image URLs from the live DOM.
    """
    screenshot_url = None
    rendered_images = []
    html_content = ""
    browser = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-zygote",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--disable-sync",
                    "--js-flags=--max-old-space-size=256"
                ]
            )
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                locale="nl-NL",
                timezone_id="Europe/Amsterdam",
                extra_http_headers={
                    "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7"
                }
            )
            page = context.new_page()

            # Anti-detection stealth script (removes navigator.webdriver)
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['nl-NL', 'nl', 'en-US', 'en'] });
            """)

            # Navigate with retry and wait for full CSS/image loading
            for nav_attempt in range(3):
                try:
                    page.goto(page_url, wait_until="load", timeout=25000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        pass
                    time.sleep(1.0)
                    
                    # Detect Cloudflare Rate Limit 1015
                    title_text = page.title() or ""
                    body_text = page.inner_text("body") if page.query_selector("body") else ""
                    if "Error 1015" in title_text or "Error 1015" in body_text or "You are being rate limited" in body_text:
                        wait_sec = 6 + nav_attempt * 4
                        print(f"[Cloudflare 1015] Rate limit detected on {page_url}. Backing off {wait_sec}s (attempt {nav_attempt+1}/3)...", flush=True)
                        time.sleep(wait_sec)
                        continue
                    break
                except Exception as e:
                    print(f"[Screenshot] Navigation issue on {page_url} (attempt {nav_attempt+1}): {e}", flush=True)
                    time.sleep(2)

            # Smooth scroll to trigger lazy-loaded images without stalling
            try:
                page.evaluate("""async () => {
                    await new Promise((resolve) => {
                        let totalHeight = 0;
                        const distance = 600;
                        const maxScrolls = 20;
                        let count = 0;
                        const timer = setInterval(() => {
                            const scrollHeight = document.body.scrollHeight;
                            window.scrollBy(0, distance);
                            totalHeight += distance;
                            count++;
                            if(totalHeight >= scrollHeight || count >= maxScrolls){
                                clearInterval(timer);
                                resolve();
                            }
                        }, 60);
                    });
                }""")
                time.sleep(1.0)
                page.evaluate("window.scrollTo(0, 0)")
                time.sleep(1.0)
            except Exception:
                pass

            # 1. Capture Full Page Screenshot
            try:
                screenshot_bytes = page.screenshot(full_page=True, type="jpeg", quality=80, timeout=15000)
                if screenshot_bytes and len(screenshot_bytes) > 0:
                    storage_path = f"{site_domain}/{page_id}/screenshot.jpg"
                    print(f"[Screenshot] Uploading screenshot ({len(screenshot_bytes)} bytes) to {storage_path}", flush=True)
                    screenshot_url = upload_image_to_storage(
                        file_bytes=screenshot_bytes,
                        storage_path=storage_path,
                        content_type="image/jpeg"
                    )
                    if screenshot_url:
                        print(f"[Screenshot] ✅ Uploaded: {screenshot_url[:80]}...", flush=True)
                    else:
                        print(f"[Screenshot] ❌ Upload returned None for {page_url}", flush=True)
            except Exception as e:
                print(f"[Screenshot] Error capturing full-page screenshot ({page_url}): {e}", flush=True)

            # 2. Extract All Rendered Images from Live DOM
            try:
                raw_dom_imgs = page.evaluate("""() => {
                    const results = [];
                    const seen = new Set();

                    // All <img> elements — check multiple source attributes
                    document.querySelectorAll('img').forEach(img => {
                        // Prefer currentSrc (actual rendered source, includes srcset resolution)
                        const candidates = [
                            img.currentSrc,
                            img.src,
                            img.getAttribute('data-lazy-src'),
                            img.getAttribute('data-lazy-srcset'),
                            img.getAttribute('data-src'),
                            img.getAttribute('data-original'),
                            img.getAttribute('data-bg'),
                            img.getAttribute('data-bg-src')
                        ];
                        
                        for (const src of candidates) {
                            if (src && !src.startsWith('data:') && !src.includes('data:image') && !seen.has(src)) {
                                // For srcset values, take the first/largest URL
                                const cleanSrc = src.split(',')[0].trim().split(' ')[0];
                                if (cleanSrc && !seen.has(cleanSrc)) {
                                    seen.add(cleanSrc);
                                    results.push({
                                        src: cleanSrc,
                                        alt: img.alt || '',
                                        width: img.naturalWidth || img.width || 0,
                                        height: img.naturalHeight || img.height || 0
                                    });
                                }
                                break;
                            }
                        }
                    });

                    // <source> inside <picture> elements
                    document.querySelectorAll('picture source').forEach(source => {
                        const srcset = source.getAttribute('srcset');
                        if (srcset) {
                            const src = srcset.split(',')[0].trim().split(' ')[0];
                            if (src && !src.startsWith('data:') && !seen.has(src)) {
                                seen.add(src);
                                results.push({
                                    src: src,
                                    alt: 'Picture source',
                                    width: 0,
                                    height: 0
                                });
                            }
                        }
                    });

                    // <video> poster images
                    document.querySelectorAll('video[poster]').forEach(video => {
                        const poster = video.getAttribute('poster');
                        if (poster && !poster.startsWith('data:') && !seen.has(poster)) {
                            seen.add(poster);
                            results.push({
                                src: poster,
                                alt: 'Video poster',
                                width: video.clientWidth || 0,
                                height: video.clientHeight || 0
                            });
                        }
                    });

                    // Background images (CSS) — only scan elements likely to have backgrounds
                    const bgSelectors = 'section, div, header, footer, main, article, aside, span, a, [style*="background"]';
                    document.querySelectorAll(bgSelectors).forEach(el => {
                        const bg = window.getComputedStyle(el).backgroundImage;
                        if (bg && bg !== 'none') {
                            // Can contain multiple backgrounds: url(...), url(...)
                            const matches = bg.matchAll(/url\\(['"]?(.*?)['"]?\\)/g);
                            for (const match of matches) {
                                const src = match[1];
                                if (src && !src.startsWith('data:') && !src.includes('data:image') && !seen.has(src)) {
                                    seen.add(src);
                                    results.push({
                                        src: src,
                                        alt: 'Background Image',
                                        width: el.clientWidth || 0,
                                        height: el.clientHeight || 0
                                    });
                                }
                            }
                        }
                    });

                    // SVG <image> elements
                    document.querySelectorAll('svg image').forEach(img => {
                        const href = img.getAttribute('href') || img.getAttribute('xlink:href');
                        if (href && !href.startsWith('data:') && !seen.has(href)) {
                            seen.add(href);
                            results.push({
                                src: href,
                                alt: 'SVG image',
                                width: parseInt(img.getAttribute('width')) || 0,
                                height: parseInt(img.getAttribute('height')) || 0
                            });
                        }
                    });

                    return results;
                }""")

                for item in raw_dom_imgs:
                    src = item.get("src", "")
                    if src and not src.startswith("data:"):
                        full_src = urljoin(page_url, src)
                        rendered_images.append({
                            "src": full_src,
                            "alt": item.get("alt", ""),
                            "width": item.get("width", 0),
                            "height": item.get("height", 0)
                        })

                print(f"[Screenshot] Found {len(rendered_images)} rendered images on {page_url}", flush=True)

            except Exception as e:
                print(f"[Screenshot] Error extracting DOM images ({page_url}): {e}", flush=True)

            # 3. Extract Full Rendered HTML directly from Playwright
            try:
                html_content = page.content()
            except Exception as e:
                print(f"[Screenshot] Error extracting page HTML ({page_url}): {e}", flush=True)

            try:
                browser.close()
                browser = None
            except Exception:
                pass

    except Exception as e:
        print(f"[Screenshot] Playwright error on {page_url}: {e}", flush=True)
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass

    return {
        "screenshot_url": screenshot_url,
        "rendered_images": rendered_images,
        "html_content": html_content
    }
