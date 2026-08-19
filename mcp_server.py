#!/usr/bin/env python3
"""
MCP (Model Context Protocol) Server for the Website Scraper.

Provides LLM-accessible tools to query scraped website data, page structures,
blueprints, and screenshots via the standard MCP JSON-RPC protocol over stdio.

Compatible with: Claude Desktop, Cursor, Claude Code, Windsurf, Cline, and any MCP client.

Authentication:
  Set MCP_API_KEY in .env (auto-generated on first run if missing).
  - HTTP mode:  Send `Authorization: Bearer <key>` header with every request.
  - stdio mode: Pass `{"auth": {"api_key": "<key>"}}` in the initialize params,
                OR set MCP_API_KEY env var in the MCP client config.

Usage:
  python3 mcp_server.py              # Runs in stdio mode (for MCP clients)
  python3 mcp_server.py --http 8808  # Runs HTTP mode (for Claude Code connector / testing)

Configuration for Claude Code / Cursor (mcp_config.json):
{
  "mcpServers": {
    "website-scraper": {
      "command": "python3",
      "args": ["/Users/johanvanderwijk/Documents/Scraper/mcp_server.py"],
      "env": {
        "MCP_API_KEY": "<your-key-here>"
      }
    }
  }
}
"""

import os
import sys
import json
import traceback

# Ensure project root is on path so scraper.* imports work
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from scraper.db import (
    get_all_sites, get_site, get_site_pages, get_site_categories,
    get_site_navigation, get_page, get_page_blocks, get_page_images,
    get_page_links
)
from scraper.blueprint_generator import (
    build_site_knowledge_tree, generate_llm_master_prompt, generate_single_page_prompt
)
from scraper.page_structure import (
    generate_page_structure, generate_page_structure_compact
)


# ── MCP Protocol Constants ────────────────────────────────────────────

SERVER_NAME = "website-scraper"
SERVER_VERSION = "1.1.0"
PROTOCOL_VERSION = "2024-11-05"

# ── Authentication ────────────────────────────────────────────────────

MCP_API_KEY = os.environ.get("MCP_API_KEY", "")

if not MCP_API_KEY:
    # Auto-generate a key and append to .env if missing
    import secrets
    MCP_API_KEY = secrets.token_urlsafe(32)
    env_path = os.path.join(PROJECT_ROOT, ".env")
    try:
        with open(env_path, "a") as f:
            f.write(f"\nMCP_API_KEY={MCP_API_KEY}\n")
        sys.stderr.write(f"[MCP] ⚠️  No MCP_API_KEY found. Auto-generated and saved to .env\n")
        sys.stderr.write(f"[MCP] 🔑 Your API key: {MCP_API_KEY}\n")
    except Exception:
        sys.stderr.write(f"[MCP] ⚠️  Auto-generated API key (not saved): {MCP_API_KEY}\n")
    sys.stderr.flush()

import hmac

def validate_api_key(provided_key):
    """Safely validate the provided token/key with constant-time comparison."""
    if not MCP_API_KEY:
        return True
    if not provided_key:
        return False
    return hmac.compare_digest(str(provided_key).strip(), str(MCP_API_KEY).strip())


# ── Tool Definitions ──────────────────────────────────────────────────

TOOLS = [
    {
        "name": "list_sites",
        "description": "List all scraped websites with their domain, name, business context, and category count.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_site_overview",
        "description": "Get a detailed overview of a scraped website including all pages, categories, and navigation structure. Use the site_id from list_sites.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "string",
                    "description": "UUID of the site (get from list_sites)"
                }
            },
            "required": ["site_id"]
        }
    },
    {
        "name": "get_page_structure",
        "description": "Get a compact, hierarchical layout description of a web page showing how it's built — which headings, images, CTAs, and text sections exist and how they relate to each other. Perfect for understanding page layout before rebuilding.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "UUID of the page (get from get_site_overview)"
                },
                "mode": {
                    "type": "string",
                    "enum": ["full", "compact"],
                    "description": "full = includes paragraph text, compact = headings + images + CTAs only. Default: full"
                }
            },
            "required": ["page_id"]
        }
    },
    {
        "name": "get_page_content",
        "description": "Get the full structured content blocks of a page, including all text, headings, images, links, and their hierarchy.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "UUID of the page"
                }
            },
            "required": ["page_id"]
        }
    },
    {
        "name": "get_page_markdown",
        "description": "Get the raw markdown content of a scraped page — useful for quick content extraction.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "UUID of the page"
                }
            },
            "required": ["page_id"]
        }
    },
    {
        "name": "get_page_images",
        "description": "Get all images found on a page with their URLs, alt text, dimensions, and types.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "UUID of the page"
                }
            },
            "required": ["page_id"]
        }
    },
    {
        "name": "get_page_screenshot",
        "description": "Get the full-page screenshot URL for a page. Returns a public Supabase Storage CDN URL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "UUID of the page"
                }
            },
            "required": ["page_id"]
        }
    },
    {
        "name": "generate_rebuild_prompt",
        "description": "Generate a complete LLM master prompt to rebuild the entire website in a specific framework. Returns a detailed markdown specification with all pages, content, images, and CTAs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "string",
                    "description": "UUID of the site"
                },
                "framework": {
                    "type": "string",
                    "enum": [
                        "Next.js 14 (App Router) + Tailwind CSS",
                        "Astro + Tailwind CSS",
                        "React (Vite) + Tailwind CSS",
                        "Nuxt 3 (Vue) + Tailwind CSS",
                        "HTML5 + CSS3 (Vanilla)"
                    ],
                    "description": "Target frontend framework for the rebuild"
                }
            },
            "required": ["site_id", "framework"]
        }
    },
    {
        "name": "generate_page_rebuild_prompt",
        "description": "Generate an LLM prompt to rebuild a single specific page. Useful for iterative, route-by-route development.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "UUID of the page"
                },
                "framework": {
                    "type": "string",
                    "description": "Target framework (e.g. 'Next.js 14 + Tailwind CSS')"
                }
            },
            "required": ["page_id"]
        }
    },
    {
        "name": "get_site_blueprint_json",
        "description": "Get the complete structured JSON blueprint of a website — the full knowledge tree with all pages, sections, images, CTAs, categories, and navigation. Machine-readable format.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "string",
                    "description": "UUID of the site"
                }
            },
            "required": ["site_id"]
        }
    },
    {
        "name": "search_content",
        "description": "Search across all scraped content blocks for specific text. Useful for finding where specific copy, features, or mentions exist across the site.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_id": {
                    "type": "string",
                    "description": "UUID of the site to search within"
                },
                "query": {
                    "type": "string",
                    "description": "Text to search for (case-insensitive)"
                }
            },
            "required": ["site_id", "query"]
        }
    }
]


# ── Tool Handlers ─────────────────────────────────────────────────────

def handle_list_sites(args):
    sites = get_all_sites()
    if not sites:
        return "No scraped websites found. Use the web UI at http://localhost:5000 to scrape a website first."

    lines = [f"# Scraped Websites ({len(sites)} total)\n"]
    for s in sites:
        lines.append(f"## {s.get('name') or s.get('domain')}")
        lines.append(f"- **Site ID:** `{s['id']}`")
        lines.append(f"- **Domain:** {s.get('domain')}")
        lines.append(f"- **Business Context:** {s.get('business_context') or 'Not set'}")
        lines.append(f"- **Created:** {s.get('created_at', '')[:10]}")
        lines.append("")
    return "\n".join(lines)


def handle_get_site_overview(args):
    site_id = args["site_id"]
    site = get_site(site_id)
    if not site:
        return f"Site with ID `{site_id}` not found."

    pages = get_site_pages(site_id)
    categories = get_site_categories(site_id)
    nav = get_site_navigation(site_id)

    lines = [
        f"# Site Overview: {site.get('domain')}",
        f"**Business Context:** {site.get('business_context') or 'Not set'}",
        f"**Total Pages:** {len(pages)}",
        f"**Categories:** {len(categories)}",
        ""
    ]

    if categories:
        lines.append("## Categories / Business Pillars")
        for c in categories:
            lines.append(f"- **{c.get('name')}** (`{c.get('slug')}`): {c.get('summary') or 'No summary'}")
        lines.append("")

    if nav:
        lines.append("## Navigation")
        for menu in nav:
            lines.append(f"### {menu.get('menu_type', 'Menu')}")
            for item in (menu.get("items") or []):
                lines.append(f"  - {item.get('label', '?')} → {item.get('url', '?')}")
        lines.append("")

    lines.append("## Pages")
    for p in pages:
        cat_info = ""
        if p.get("categories") and isinstance(p["categories"], dict):
            cat_info = f" | 📁 {p['categories']['name']}"
        screenshot = " 📸" if p.get("screenshot_url") else ""
        lines.append(
            f"- `{p.get('path')}` — **{p.get('title') or 'Untitled'}** "
            f"(type: {p.get('page_type', '?')}{cat_info}{screenshot})"
        )
        lines.append(f"  Page ID: `{p['id']}`")

    return "\n".join(lines)


def handle_get_page_structure(args):
    page_id = args["page_id"]
    mode = args.get("mode", "full")
    if mode == "compact":
        return generate_page_structure_compact(page_id)
    return generate_page_structure(page_id)


def handle_get_page_content(args):
    page_id = args["page_id"]
    page = get_page(page_id)
    if not page:
        return f"Page `{page_id}` not found."

    blocks = get_page_blocks(page_id)
    lines = [
        f"# Page Content: {page.get('title') or page.get('path')}",
        f"**URL:** {page.get('url')}",
        f"**Type:** {page.get('page_type', 'unknown')}",
        f"**Meta:** {page.get('meta_description') or 'None'}",
        f"**Content Blocks:** {len(blocks)}",
        ""
    ]

    for b in blocks:
        tag = b.get("tag_name", "")
        content = (b.get("content") or "").strip()
        level = b.get("hierarchy_level", 0)
        indent = "  " * min(level, 4)
        section_path = b.get("section_path") or ""

        if tag in ["h1", "h2", "h3", "h4"]:
            lines.append(f"\n{indent}{'#' * int(tag[1:])} {content}")
        elif tag == "img":
            attrs = b.get("attributes") or {}
            if isinstance(attrs, str):
                try:
                    attrs = json.loads(attrs)
                except:
                    attrs = {}
            lines.append(f"{indent}![{attrs.get('alt', '')}]({attrs.get('src', '')})")
        elif tag == "a":
            attrs = b.get("attributes") or {}
            if isinstance(attrs, str):
                try:
                    attrs = json.loads(attrs)
                except:
                    attrs = {}
            lines.append(f"{indent}[{content}]({attrs.get('href', '')})")
        elif content:
            lines.append(f"{indent}{content}")

    return "\n".join(lines)


def handle_get_page_markdown(args):
    page_id = args["page_id"]
    page = get_page(page_id)
    if not page:
        return f"Page `{page_id}` not found."
    return page.get("raw_markdown") or "No markdown content available for this page."


def handle_get_page_images(args):
    page_id = args["page_id"]
    page = get_page(page_id)
    if not page:
        return f"Page `{page_id}` not found."

    images = get_page_images(page_id)
    if not images:
        return f"No images found for page `{page.get('title') or page.get('path')}`."

    lines = [f"# Images on: {page.get('title') or page.get('path')} ({len(images)} total)\n"]
    for img in images:
        url = img.get("public_url") or img.get("original_url") or "?"
        alt = img.get("alt_text") or ""
        w = img.get("width") or "?"
        h = img.get("height") or "?"
        itype = img.get("image_type") or "unknown"
        lines.append(f"- **{alt or 'Image'}** ({w}×{h}) — type: `{itype}`")
        lines.append(f"  URL: {url}")
    return "\n".join(lines)


def handle_get_page_screenshot(args):
    page_id = args["page_id"]
    page = get_page(page_id)
    if not page:
        return f"Page `{page_id}` not found."

    screenshot_url = page.get("screenshot_url")
    if screenshot_url:
        return f"Screenshot for **{page.get('title') or page.get('path')}**:\n\n{screenshot_url}"
    return f"No screenshot available for page `{page.get('title') or page.get('path')}`. Re-scrape the page to generate one."


def handle_generate_rebuild_prompt(args):
    site_id = args["site_id"]
    framework = args.get("framework", "Next.js 14 (App Router) + Tailwind CSS")
    return generate_llm_master_prompt(site_id, framework)


def handle_generate_page_rebuild_prompt(args):
    page_id = args["page_id"]
    framework = args.get("framework", "Next.js 14 + Tailwind CSS")
    return generate_single_page_prompt(page_id, framework)


def handle_get_site_blueprint_json(args):
    site_id = args["site_id"]
    blueprint = build_site_knowledge_tree(site_id)
    if not blueprint:
        return f"Site `{site_id}` not found or has no data."
    return json.dumps(blueprint, indent=2, default=str)


def handle_search_content(args):
    site_id = args["site_id"]
    query = args["query"].lower()
    pages = get_site_pages(site_id)

    if not pages:
        return f"No pages found for site `{site_id}`."

    results = []
    for p in pages:
        blocks = get_page_blocks(p["id"])
        for b in blocks:
            content = (b.get("content") or "").lower()
            if query in content:
                results.append({
                    "page": p.get("title") or p.get("path"),
                    "page_id": p["id"],
                    "path": p.get("path"),
                    "tag": b.get("tag_name"),
                    "section": b.get("section_path") or "",
                    "match": (b.get("content") or "")[:200]
                })

        # Also search markdown
        md = (p.get("raw_markdown") or "").lower()
        if query in md and not any(r["page_id"] == p["id"] for r in results):
            idx = md.index(query)
            snippet_start = max(0, idx - 50)
            snippet_end = min(len(md), idx + len(query) + 100)
            results.append({
                "page": p.get("title") or p.get("path"),
                "page_id": p["id"],
                "path": p.get("path"),
                "tag": "markdown",
                "section": "",
                "match": md[snippet_start:snippet_end]
            })

    if not results:
        return f"No matches found for \"{args['query']}\" across the site."

    lines = [f"# Search Results for \"{args['query']}\" ({len(results)} matches)\n"]
    for r in results[:30]:  # Cap at 30
        lines.append(f"- **{r['page']}** (`{r['path']}`) — `<{r['tag']}>` in `{r['section']}`")
        lines.append(f"  > {r['match'][:150]}")
        lines.append(f"  Page ID: `{r['page_id']}`")
    return "\n".join(lines)


# ── Tool Dispatcher ───────────────────────────────────────────────────

TOOL_HANDLERS = {
    "list_sites": handle_list_sites,
    "get_site_overview": handle_get_site_overview,
    "get_page_structure": handle_get_page_structure,
    "get_page_content": handle_get_page_content,
    "get_page_markdown": handle_get_page_markdown,
    "get_page_images": handle_get_page_images,
    "get_page_screenshot": handle_get_page_screenshot,
    "generate_rebuild_prompt": handle_generate_rebuild_prompt,
    "generate_page_rebuild_prompt": handle_generate_page_rebuild_prompt,
    "get_site_blueprint_json": handle_get_site_blueprint_json,
    "search_content": handle_search_content,
}


# ── MCP JSON-RPC Protocol (stdio mode) ───────────────────────────────

def make_response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_request(msg):
    """Process a single MCP JSON-RPC request."""
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params", {})

    # ── Initialize handshake
    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False}
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION
            }
        })

    # ── Notifications (no response needed)
    if method == "notifications/initialized":
        return None  # No response for notifications

    if method == "notifications/cancelled":
        return None

    # ── List tools
    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    # ── Call tool
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        handler = TOOL_HANDLERS.get(tool_name)
        if not handler:
            return make_response(req_id, {
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                "isError": True
            })

        try:
            result_text = handler(arguments)
            return make_response(req_id, {
                "content": [{"type": "text", "text": result_text}]
            })
        except Exception as e:
            tb = traceback.format_exc()
            return make_response(req_id, {
                "content": [{"type": "text", "text": f"Error executing {tool_name}: {str(e)}\n{tb}"}],
                "isError": True
            })

    # ── Ping
    if method == "ping":
        return make_response(req_id, {})

    # ── Unknown method
    return make_error(req_id, -32601, f"Method not found: {method}")


def run_stdio():
    """Run the MCP server in stdio mode (standard for Claude Desktop / Cursor)."""
    sys.stderr.write(f"[MCP] {SERVER_NAME} v{SERVER_VERSION} starting in stdio mode...\n")
    sys.stderr.flush()

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break  # EOF

            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                sys.stderr.write(f"[MCP] Invalid JSON: {e}\n")
                sys.stderr.flush()
                continue

            response = handle_request(msg)

            if response is not None:
                response_str = json.dumps(response)
                sys.stdout.write(response_str + "\n")
                sys.stdout.flush()

        except KeyboardInterrupt:
            break
        except Exception as e:
            sys.stderr.write(f"[MCP] Error: {e}\n{traceback.format_exc()}")
            sys.stderr.flush()

    sys.stderr.write("[MCP] Server stopped.\n")
    sys.stderr.flush()


# ── HTTP/SSE Mode (for testing & remote connectors) ──────────────────

def run_http(port=8808):
    """Run an authenticated HTTP server for Claude Code and other MCP connectors."""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs

    class MCPHandler(BaseHTTPRequestHandler):
        def _send_cors_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-API-Key, Accept")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def _is_authenticated(self):
            # Check 1: Authorization Header (Bearer <token>)
            auth_header = self.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()
                if validate_api_key(token):
                    return True

            # Check 2: X-API-Key header
            x_api_key = self.headers.get("X-API-Key", "").strip()
            if x_api_key and validate_api_key(x_api_key):
                return True

            # Check 3: Query parameter (?api_key=... or ?token=...)
            parsed_url = urlparse(self.path)
            query_params = parse_qs(parsed_url.query)
            for param in ("api_key", "token", "apiKey"):
                if param in query_params and query_params[param]:
                    if validate_api_key(query_params[param][0]):
                        return True

            return False

        def do_OPTIONS(self):
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()

        def do_GET(self):
            parsed_url = urlparse(self.path)
            path = parsed_url.path

            if path in ("/", "/health", "/status"):
                authenticated = self._is_authenticated()
                res = {
                    "status": "ok",
                    "server": SERVER_NAME,
                    "version": SERVER_VERSION,
                    "protocolVersion": PROTOCOL_VERSION,
                    "auth_required": bool(MCP_API_KEY),
                    "authenticated": authenticated
                }
                body = json.dumps(res, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()

        def do_POST(self):
            # Enforce authentication
            if not self._is_authenticated():
                err = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32000,
                        "message": "Unauthorized. Please supply a valid MCP_API_KEY via 'Authorization: Bearer <key>' or 'X-API-Key: <key>' header."
                    }
                }
                body = json.dumps(err).encode("utf-8")
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")

            try:
                msg = json.loads(body)
                response = handle_request(msg)
                if response is None:
                    self.send_response(204)
                    self._send_cors_headers()
                    self.end_headers()
                    return

                response_bytes = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_bytes)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(response_bytes)
            except Exception as e:
                error_response = json.dumps(make_error(None, -32700, str(e))).encode("utf-8")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(error_response)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(error_response)

        def log_message(self, format, *args):
            sys.stderr.write(f"[MCP-HTTP] {args[0]} {args[1]} {args[2]}\n")

    server = HTTPServer(("0.0.0.0", port), MCPHandler)
    print(f"[MCP] HTTP server listening on http://localhost:{port}", flush=True)
    print(f"[MCP] Test with: curl -X POST http://localhost:{port} -H 'Content-Type: application/json' -d '{{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}}'", flush=True)
    server.serve_forever()


# ── Main ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--http" in sys.argv:
        port = 8808
        idx = sys.argv.index("--http")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])
        run_http(port)
    else:
        run_stdio()
