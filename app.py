import os
import re
import time
import json
import uuid as uuid_lib
import threading
import concurrent.futures
from urllib.parse import urlparse
from flask import Flask, render_template, request, redirect, url_for, flash, Response, jsonify
from dotenv import load_dotenv, set_key

from scraper.db import (
    get_all_sites, upsert_site, upsert_page,
    get_site_pages, get_page_blocks, delete_site,
    insert_content_blocks, delete_page_blocks, get_site, get_page,
    insert_images, delete_page_images, get_page_images,
    upsert_navigation, get_site_navigation,
    insert_page_links, delete_page_links, get_page_links,
    upsert_category, get_site_categories, update_category_synthesis
)
from scraper.crawler import crawl_site, guess_page_type
from scraper.parser import parse_page
from scraper.nav_extractor import extract_site_navigation
from scraper.ai_labeler import get_available_models, match_pages_to_categories, generate_category_synthesis
from scraper.page_structure import generate_page_structure, generate_page_structure_compact

load_dotenv()

import tempfile

app = Flask(__name__)
app.secret_key = "scraper-secure-session-key"

scrape_jobs = {}
job_lock = threading.Lock()
JOB_DIR = os.path.join(tempfile.gettempdir(), "aiscraper_jobs")
os.makedirs(JOB_DIR, exist_ok=True)


def _get_job_file(job_id):
    return os.path.join(JOB_DIR, f"{job_id}.json")


def _load_job(job_id):
    """Load job from shared tmpfs file or in-memory dict."""
    fpath = _get_job_file(job_id)
    if os.path.exists(fpath):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    with job_lock:
        return scrape_jobs.get(job_id)


def _save_job(job_id, job_data):
    """Save job state to both in-memory dict and shared tmpfs file for multi-worker access."""
    with job_lock:
        scrape_jobs[job_id] = job_data
    try:
        fpath = _get_job_file(job_id)
        tmp_fpath = f"{fpath}.tmp"
        with open(tmp_fpath, "w", encoding="utf-8") as f:
            json.dump(job_data, f)
        os.replace(tmp_fpath, fpath)
    except Exception as e:
        print(f"Error persisting job file: {e}")


def get_max_concurrent_scrapers():
    """Calculate dynamic worker count based on vCPUs / env var for Cloud Run."""
    env_val = os.environ.get("MAX_CONCURRENT_SCRAPERS")
    if env_val:
        try:
            return max(1, int(env_val))
        except ValueError:
            pass
    cpu_count = os.cpu_count() or 2
    # Cloud Run rule of thumb: 2 browser workers per vCPU, capped between 2 and 16
    return max(2, min(cpu_count * 2, 16))




def _slugify(text):
    text = re.sub(r"[^\w\s-]", "", text.lower().strip())
    return re.sub(r"[-\s]+", "-", text) or "category"


@app.route("/")
def index():
    sites = get_all_sites()
    has_openai_key = bool(os.environ.get("OPENAI_API_KEY"))
    models = get_available_models()
    return render_template("index.html", sites=sites, has_openai_key=has_openai_key, models=models)


@app.route("/settings/api-key", methods=["POST"])
def save_api_key():
    key = request.form.get("openai_api_key", "").strip()
    if key:
        os.environ["OPENAI_API_KEY"] = key
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        try:
            set_key(env_path, "OPENAI_API_KEY", key)
            flash("OpenAI API Key saved successfully!", "success")
        except Exception as e:
            flash(f"Key active for current session ({e})", "warning")
    return redirect(url_for("index"))


# --- STEP 1: CRAWL, URL DISCOVERY & CATEGORY MAPPING ---
@app.route("/crawl", methods=["POST"])
def crawl():
    url = request.form.get("url", "").strip()
    max_pages = request.form.get("max_pages", "30")
    openai_model = request.form.get("openai_model", "gpt-5.4-nano")
    categories_input = request.form.get("categories", "").strip()
    business_context = request.form.get("business_context", "").strip()

    if not url:
        flash("Website URL is required", "error")
        return redirect(url_for("index"))

    if not url.startswith("http"):
        url = "https://" + url

    try:
        max_pages = int(max_pages)
        max_pages = min(max(max_pages, 1), 100)
    except ValueError:
        max_pages = 30

    domain = urlparse(url).netloc
    if not domain:
        flash("Invalid URL domain", "error")
        return redirect(url_for("index"))

    # Parse predefined categories
    category_list = []
    if categories_input:
        for part in re.split(r"[,;\n]+", categories_input):
            p = part.strip()
            if p and p not in category_list:
                category_list.append(p)

    if not category_list:
        category_list = ["Hoofdaanbod", "Algemeen"]

    # Discover URLs on website with page titles and H1s
    pages_preview = crawl_site(url, max_pages=max_pages)
    if not pages_preview:
        flash(f"Could not discover any pages on {domain}. Please verify the URL.", "error")
        return redirect(url_for("index"))

    # AI category matching with mini-analysis
    category_matches = match_pages_to_categories(
        pages_list=pages_preview,
        predefined_categories=category_list,
        business_context=business_context,
        model=openai_model
    )

    for p in pages_preview:
        p["assigned_category"] = category_matches.get(p["url"], category_list[0])

    models = get_available_models()
    has_openai_key = bool(os.environ.get("OPENAI_API_KEY"))

    return render_template(
        "configure.html",
        start_url=url,
        domain=domain,
        pages=pages_preview,
        categories=category_list,
        business_context=business_context,
        models=models,
        selected_model=openai_model,
        has_openai_key=has_openai_key
    )


# --- STEP 2: EXECUTE FULL SCRAPE & CATEGORY SYNTHESIS ---
@app.route("/scrape/execute", methods=["POST"])
def scrape_execute():
    start_url = request.form.get("start_url", "").strip()
    domain = request.form.get("domain", "").strip()
    openai_model = request.form.get("openai_model", "gpt-5.4-nano")
    business_context = request.form.get("business_context", "").strip()
    global_instructions = request.form.get("global_instructions", "").strip()
    all_categories_str = request.form.get("all_categories", "").strip()

    # Collect categories
    categories_set = []
    if all_categories_str:
        try:
            categories_set = json.loads(all_categories_str)
        except Exception:
            categories_set = [c.strip() for c in all_categories_str.split(",") if c.strip()]

    # Collect page configurations
    pages_to_scrape = []
    for key, value in request.form.items():
        if key.startswith("page_include_"):
            idx = key.replace("page_include_", "")
            page_url = request.form.get(f"page_url_{idx}")
            page_path = request.form.get(f"page_path_{idx}")
            page_type = request.form.get(f"page_type_{idx}")
            page_category = request.form.get(f"page_category_{idx}", "").strip() or "Algemeen"
            instructions = request.form.get(f"page_instructions_{idx}", "").strip()

            if page_category and page_category not in categories_set:
                categories_set.append(page_category)

            combined_instructions = global_instructions
            if instructions:
                combined_instructions = f"{global_instructions} | {instructions}" if global_instructions else instructions

            if page_url:
                pages_to_scrape.append({
                    "url": page_url,
                    "path": page_path or "/",
                    "page_type": page_type or "general_page",
                    "category_name": page_category,
                    "instructions": combined_instructions
                })

    if not pages_to_scrape:
        flash("No pages selected for scraping.", "error")
        return redirect(url_for("index"))

    job_id = str(uuid_lib.uuid4())[:8]
    _save_job(job_id, {"events": [], "done": False, "result": {}})

    thread = threading.Thread(
        target=_run_full_scrape_job,
        args=(job_id, start_url, domain, pages_to_scrape, categories_set, business_context, openai_model),
        daemon=True
    )
    thread.start()

    return render_template("progress.html", job_id=job_id, domain=domain, total_pages=len(pages_to_scrape))


def _add_event(job_id, phase, current, total, url, message=""):
    event = {
        "phase": phase,
        "current": current,
        "total": total,
        "url": url,
        "message": message,
        "timestamp": time.time()
    }
    job = _load_job(job_id) or {"events": [], "done": False, "result": {}}
    job["events"].append(event)
    _save_job(job_id, job)



def _scrape_single_page_worker(p_info, site_id, domain, category_map, openai_model, job_id, total_pages, shared_state):
    """Worker task to scrape a single page concurrently with thread-safe progress reporting."""
    page_url = p_info["url"]
    path = p_info["path"]
    page_type = p_info["page_type"]
    cat_name = p_info["category_name"]
    cat_id = category_map.get(cat_name)
    instructions = p_info["instructions"]

    _add_event(job_id, "scrape", shared_state["completed_count"], total_pages, page_url, f"Scraping [{cat_name}] {path}")

    # Create or update page in DB (initial pending record)
    page = upsert_page(
        site_id=site_id,
        url_str=page_url,
        path=path,
        page_type=page_type,
        category_id=cat_id,
        scrape_instructions=instructions,
        status="pending"
    )
    if not page:
        with job_lock:
            shared_state["error_count"] += 1
            shared_state["completed_count"] += 1
            _add_event(job_id, "page_error", shared_state["completed_count"], total_pages, page_url, f"Database error creating page for {path}")
        return None

    page_id = page["id"]

    def page_progress_callback(sub_phase, cur, tot, msg):
        _add_event(job_id, "scrape_sub", shared_state["completed_count"], total_pages, page_url, f"[{path}] {msg}")

    try:
        parsed_data = parse_page(
            url_str=page_url,
            page_id=page_id,
            site_domain=domain,
            page_type=page_type,
            category_id=cat_id,
            category_name=cat_name,
            scrape_instructions=instructions,
            openai_model=openai_model,
            progress_callback=page_progress_callback
        )
    except Exception as e:
        parsed_data = {"error": str(e)}

    if "error" in parsed_data:
        upsert_page(site_id, page_url, path, status="error")
        with job_lock:
            shared_state["error_count"] += 1
            shared_state["completed_count"] += 1
            _add_event(job_id, "page_error", shared_state["completed_count"], total_pages, page_url, f"Error on {path}: {parsed_data['error'][:120]}")
        return None

    # Extract Site Navigation (thread-safe one-time execution)
    with job_lock:
        if not shared_state["nav_extracted"] and parsed_data.get("html_content"):
            try:
                nav_data = extract_site_navigation(parsed_data["html_content"], page_url)
                for menu_type, items in nav_data.items():
                    upsert_navigation(site_id, menu_type, items)
                shared_state["nav_extracted"] = True
            except Exception as e:
                print(f"Error extracting navigation: {e}")

    # Update page details with screenshot
    upsert_page(
        site_id=site_id,
        url_str=page_url,
        path=path,
        title=parsed_data.get("title", ""),
        meta_description=parsed_data.get("meta_description", ""),
        page_type=page_type,
        category_id=cat_id,
        scrape_instructions=instructions,
        status="scraped",
        raw_markdown=parsed_data.get("raw_markdown", ""),
        screenshot_url=parsed_data.get("screenshot_url")
    )

    # Insert Content Blocks
    blocks = parsed_data.get("blocks", [])
    if blocks:
        for b in blocks:
            b["page_id"] = page_id
            b["category_id"] = cat_id
        delete_page_blocks(page_id)
        insert_content_blocks(blocks)

    # Insert Images
    images = parsed_data.get("images", [])
    if images:
        for img in images:
            img["category_id"] = cat_id
        delete_page_images(page_id)
        insert_images(images)

    # Insert Links
    links = parsed_data.get("links", [])
    if links:
        delete_page_links(page_id)
        insert_page_links(links)

    with job_lock:
        shared_state["scraped_count"] += 1
        shared_state["completed_count"] += 1
        if cat_name in shared_state["scraped_pages_by_category"]:
            shared_state["scraped_pages_by_category"][cat_name].append({
                "title": parsed_data.get("title", ""),
                "path": path,
                "raw_markdown": parsed_data.get("raw_markdown", "")
            })

        _add_event(
            job_id, "page_done", shared_state["completed_count"], total_pages, page_url,
            f"✓ ({shared_state['completed_count']}/{total_pages}) {path} [{cat_name}] — {len(blocks)} blocks, {len(images)} images, {len(links)} CTAs"
        )

    return parsed_data


def _run_full_scrape_job(job_id, start_url, domain, pages_to_scrape, categories_list, business_context, openai_model):
    try:
        total_pages = len(pages_to_scrape)
        concurrency = get_max_concurrent_scrapers()
        _add_event(job_id, "init", 0, total_pages, start_url, f"Initializing parallel scrape engine for {domain} ({concurrency} workers across {os.cpu_count() or 'auto'} vCPUs)...")

        # 1. Upsert Site record
        site = upsert_site(
            domain=domain,
            name=domain,
            openai_model=openai_model,
            business_context=business_context,
            predefined_categories=categories_list
        )
        if not site:
            _add_event(job_id, "error", 0, 0, start_url, "Failed to create site in Supabase.")
            with job_lock:
                scrape_jobs[job_id]["done"] = True
                scrape_jobs[job_id]["result"] = {"success": False, "message": "Database connection failed"}
            return

        site_id = site["id"]

        # 2. Upsert Category records
        category_map = {}  # name -> id
        for order_idx, cat_name in enumerate(categories_list):
            cat_slug = _slugify(cat_name)
            cat_rec = upsert_category(
                site_id=site_id,
                name=cat_name,
                slug=cat_slug,
                description=f"Bedrijfspijler: {cat_name}",
                order_index=order_idx
            )
            if cat_rec:
                category_map[cat_name] = cat_rec["id"]

        shared_state = {
            "completed_count": 0,
            "scraped_count": 0,
            "error_count": 0,
            "nav_extracted": False,
            "scraped_pages_by_category": {cat_name: [] for cat_name in categories_list}
        }

        # 3. Parallel Multi-Worker Scraping
        _add_event(job_id, "parallel_start", 0, total_pages, start_url, f"⚡ Launched {concurrency} parallel scraping workers...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(
                    _scrape_single_page_worker,
                    p_info, site_id, domain, category_map, openai_model, job_id, total_pages, shared_state
                )
                for p_info in pages_to_scrape
            ]
            concurrent.futures.wait(futures)

        scraped_count = shared_state["scraped_count"]
        error_count = shared_state["error_count"]

        # 4. Post-scrape: Category AI Synthesis
        _add_event(job_id, "synthesis", total_pages, total_pages, start_url, "Synthesizing business category overviews & USPs...")
        for cat_name, cat_pages in shared_state["scraped_pages_by_category"].items():
            cat_id = category_map.get(cat_name)
            if cat_id and cat_pages:
                synthesis = generate_category_synthesis(
                    category_name=cat_name,
                    category_content_list=cat_pages,
                    business_context=business_context,
                    model=openai_model
                )
                update_category_synthesis(
                    category_id=cat_id,
                    summary=synthesis.get("summary", ""),
                    target_audience=synthesis.get("target_audience", ""),
                    usps=synthesis.get("usps", [])
                )

        msg = f"Successfully scraped {scraped_count} pages across {len(categories_list)} business categories from {domain}"
        if error_count > 0:
            msg += f" ({error_count} errors)"

        _add_event(job_id, "done", total_pages, total_pages, start_url, msg)
        job = _load_job(job_id) or {"events": []}
        job["done"] = True
        job["result"] = {
            "success": True,
            "site_id": site_id,
            "scraped": scraped_count,
            "errors": error_count,
            "concurrency": concurrency,
            "message": msg
        }
        _save_job(job_id, job)

    except Exception as e:
        _add_event(job_id, "error", 0, 0, start_url, f"Unexpected error: {str(e)}")
        job = _load_job(job_id) or {"events": []}
        job["done"] = True
        job["result"] = {"success": False, "message": str(e)}
        _save_job(job_id, job)


@app.route("/scrape/progress/<job_id>")
def scrape_progress(job_id):
    def generate():
        # Wait up to 5 seconds for the job to register across threads/processes
        job = None
        for _ in range(20):
            job = _load_job(job_id)
            if job and len(job.get("events", [])) > 0:
                break
            time.sleep(0.25)

        if not job:
            # Fallback: Check if the site was already scraped in Supabase
            try:
                sites = get_all_sites()
                if sites:
                    latest_site = sites[0]
                    pages = get_site_pages(latest_site["id"])
                    scraped_pages = [p for p in pages if p.get("status") == "scraped"]
                    if scraped_pages:
                        site_domain = latest_site.get("domain", "")
                        payload = {
                            "phase": "complete",
                            "result": {
                                "success": True,
                                "site_id": latest_site["id"],
                                "message": f"Site {site_domain} ready in database"
                            }
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
                        return
            except Exception:
                pass

            err_payload = {
                "phase": "error",
                "message": "Job session expired or server reloaded. Please refresh or re-start crawl."
            }
            yield f"data: {json.dumps(err_payload)}\n\n"
            return

        last_index = 0
        while True:
            job = _load_job(job_id)
            if not job:
                time.sleep(0.3)
                continue

            events = job.get("events", [])
            is_done = job.get("done", False)
            result = job.get("result", {})

            while last_index < len(events):
                event = events[last_index]
                yield f"data: {json.dumps(event)}\n\n"
                last_index += 1

            if is_done:
                yield f"data: {json.dumps({'phase': 'complete', 'result': result})}\n\n"
                break

            time.sleep(0.3)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/sites/<site_id>")
def site_detail(site_id):
    site = get_site(site_id)
    if not site:
        flash("Site not found", "error")
        return redirect(url_for("index"))
    pages = get_site_pages(site_id)
    categories = get_site_categories(site_id)
    nav_menus = get_site_navigation(site_id)
    return render_template("site.html", site=site, pages=pages, categories=categories, nav_menus=nav_menus)


@app.route("/pages/<page_id>")
def page_detail(page_id):
    page = get_page(page_id)
    if not page:
        flash("Page not found", "error")
        return redirect(url_for("index"))

    blocks = get_page_blocks(page_id)
    images = get_page_images(page_id)
    links = get_page_links(page_id)

    block_map = {b["id"]: b for b in blocks}
    root_blocks = []

    for b in blocks:
        b["children"] = []

    for b in blocks:
        parent_id = b.get("parent_block_id")
        if parent_id and parent_id in block_map:
            block_map[parent_id]["children"].append(b)
        else:
            root_blocks.append(b)

    return render_template(
        "page.html",
        page=page,
        root_blocks=root_blocks,
        images=images,
        links=links
    )


@app.route("/sites/<site_id>/blueprint")
def site_blueprint(site_id):
    from scraper.blueprint_generator import build_site_knowledge_tree, generate_llm_master_prompt
    site = get_site(site_id)
    if not site:
        flash("Site not found", "error")
        return redirect(url_for("index"))

    blueprint = build_site_knowledge_tree(site_id)
    master_prompt = generate_llm_master_prompt(site_id, "Next.js 14 (App Router) + Tailwind CSS")
    blueprint_json = json.dumps(blueprint, indent=2)

    return render_template(
        "blueprint.html",
        site=site,
        blueprint=blueprint,
        master_prompt=master_prompt,
        blueprint_json=blueprint_json
    )


@app.route("/sites/<site_id>/blueprint/download-json")
def site_blueprint_download_json(site_id):
    from scraper.blueprint_generator import build_site_knowledge_tree
    site = get_site(site_id)
    if not site:
        return "Site not found", 404

    blueprint = build_site_knowledge_tree(site_id)
    filename = f"{site.get('domain', 'site')}_rebuild_blueprint.json"
    
    return Response(
        json.dumps(blueprint, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )


@app.route("/sites/<site_id>/blueprint/prompt-text")
def site_blueprint_prompt_text(site_id):
    from scraper.blueprint_generator import generate_llm_master_prompt
    framework = request.args.get("framework", "Next.js 14 (App Router) + Tailwind CSS")
    prompt = generate_llm_master_prompt(site_id, framework)
    return Response(prompt, mimetype="text/plain")


@app.route("/pages/<page_id>/blueprint-prompt")
def page_blueprint_prompt(page_id):
    from scraper.blueprint_generator import generate_single_page_prompt
    framework = request.args.get("framework", "Next.js 14 + Tailwind CSS")
    prompt = generate_single_page_prompt(page_id, framework)
    return Response(prompt, mimetype="text/plain")


@app.route('/pages/<page_id>/structure')
def page_structure(page_id):
    mode = request.args.get('mode', 'full')  # 'full' or 'compact'
    if mode == 'compact':
        text = generate_page_structure_compact(page_id)
    else:
        text = generate_page_structure(page_id)
    return text, 200, {'Content-Type': 'text/plain; charset=utf-8'}


@app.route("/sites/<site_id>/delete", methods=["POST"])
def site_delete(site_id):
    if delete_site(site_id):
        flash("Site deleted successfully", "success")
    else:
        flash("Failed to delete site", "error")
    return redirect(url_for("index"))


# ── MCP API Endpoint (for Claude Code / remote connectors) ────────────

@app.route("/api/mcp", methods=["GET", "POST", "OPTIONS"])
def api_mcp():
    from mcp_server import handle_request, validate_api_key, SERVER_NAME, SERVER_VERSION, PROTOCOL_VERSION, MCP_API_KEY
    
    if request.method == "OPTIONS":
        res = Response(status=204)
        res.headers["Access-Control-Allow-Origin"] = "*"
        res.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-API-Key, Accept"
        res.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return res

    # Auth check helper
    def is_auth():
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            if validate_api_key(auth_header[7:].strip()):
                return True
        x_key = request.headers.get("X-API-Key", "").strip()
        if x_key and validate_api_key(x_key):
            return True
        q_key = request.args.get("api_key") or request.args.get("token")
        if q_key and validate_api_key(q_key):
            return True
        return False

    if request.method == "GET":
        auth_ok = is_auth()
        resp = jsonify({
            "status": "ok",
            "server": SERVER_NAME,
            "version": SERVER_VERSION,
            "protocolVersion": PROTOCOL_VERSION,
            "auth_required": bool(MCP_API_KEY),
            "authenticated": auth_ok
        })
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    # POST JSON-RPC
    if not is_auth():
        err_resp = jsonify({
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32000,
                "message": "Unauthorized. Please provide valid MCP_API_KEY via Authorization: Bearer <key> header."
            }
        })
        err_resp.headers["Access-Control-Allow-Origin"] = "*"
        return err_resp, 401

    try:
        msg = request.get_json(force=True)
        response_data = handle_request(msg)
        if response_data is None:
            resp = Response(status=204)
            resp.headers["Access-Control-Allow-Origin"] = "*"
            return resp
        resp = jsonify(response_data)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
    except Exception as e:
        err_resp = jsonify({
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": str(e)}
        })
        err_resp.headers["Access-Control-Allow-Origin"] = "*"
        return err_resp, 400


if __name__ == "__main__":
    app.run(debug=True, port=5000)

