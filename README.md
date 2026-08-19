# 🕷️ AI Website Scraper & LLM Knowledge Architecture Engine

A high-performance, structured website scraper and LLM blueprint engine. It extracts hierarchical DOM structures, full-page visual screenshots via Playwright, media assets into Supabase Storage, and semantically classifies pages with OpenAI into business categories.

Equipped with a built-in **Model Context Protocol (MCP) server** for direct integration with **Claude Code**, **Cursor**, and **Claude Desktop**, plus full optimization for **Google Cloud Run** with multi-vCPU parallel scraping.

---

## ✨ Features

- **⚡ Multi-vCPU Parallel Scraping**: High-throughput multi-worker concurrent scraping engine (`ThreadPoolExecutor`). Automatically scales concurrency based on available CPU cores.
- **📸 Full-Page Visual Screenshots**: Headless Playwright Chromium captures high-res full-page screenshots with lazy-load trigger scrolling and uploads directly to Supabase Storage CDN.
- **🌲 Semantic Page Hierarchy**: Preserves DOM parent-child nesting, breadcrumb section paths, headings (`H1`-`H6`), images, buttons, and call-to-actions (CTAs).
- **📐 Compact Page Structure Generator**: Outputs a clean, hierarchical layout description designed specifically for LLMs.
- **⚡ LLM Rebuild Blueprint Hub**: Generates 1-click Master Prompts for Cursor / Claude / GPT / v0 / Bolt.new in Next.js 14, Astro, React, Nuxt, and HTML5.
- **🔌 Built-in MCP Server (11 Tools)**: Allows Claude Code and Cursor to query websites, page structures, content blocks, and media via JSON-RPC with Bearer token authentication.
- **☁️ Google Cloud Run Ready**: Multi-stage production `Dockerfile`, Gunicorn WSGI multi-threading config, and 1-click `deploy-cloudrun.sh` script.

---

## 🚀 Quick Start (Local)

### 1. Prerequisites
- Python 3.10+ (or Python 3.9+)
- Chromium for Playwright

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/johandhss/aiscraper.git
cd aiscraper

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright Chromium
playwright install chromium
```

### 3. Environment Variables
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-service-role-key
OPENAI_API_KEY=sk-proj-...
MCP_API_KEY=your-secure-mcp-token
```

### 4. Database Setup
Run the SQL queries in `supabase_schema.sql` inside your Supabase SQL Editor to create the required tables and storage buckets.

### 5. Run the Application
```bash
# Start Flask web server (port 5000)
python3 app.py

# (Optional) Start standalone MCP HTTP server (port 8808)
python3 mcp_server.py --http 8808
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

---

## 🔌 MCP Integration (Claude Code & Cursor)

This scraper exposes 11 tools over the Model Context Protocol (MCP) for direct consumption by AI agents.

### Cursor / Claude Code Configuration (`mcp_config.json`):
```json
{
  "mcpServers": {
    "website-scraper-http": {
      "url": "http://localhost:8808",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_API_KEY"
      }
    },
    "website-scraper-stdio": {
      "command": "python3",
      "args": ["/absolute/path/to/aiscraper/mcp_server.py"],
      "env": {
        "MCP_API_KEY": "YOUR_MCP_API_KEY"
      }
    }
  }
}
```

### Available MCP Tools:
| Tool | Description |
|------|-------------|
| `list_sites` | List all scraped websites and metadata |
| `get_site_overview` | Complete overview of pages, business pillars, and navigation |
| `get_page_structure` | Hierarchical layout description for LLMs (`full` or `compact`) |
| `get_page_content` | Structured content blocks with DOM nesting |
| `get_page_markdown` | Raw markdown content of a page |
| `get_page_images` | All page images with dimensions and CDN URLs |
| `get_page_screenshot` | Full-page visual screenshot URL |
| `generate_rebuild_prompt` | Master prompt for full site rebuild in chosen framework |
| `generate_page_rebuild_prompt` | Focused single-page rebuild prompt |
| `get_site_blueprint_json` | Complete machine-readable JSON knowledge tree |
| `search_content` | Search across all scraped content blocks |

---

## ☁️ Deployment to Google Cloud Run

Deploy as a serverless container with scale-to-zero capability:

```bash
# 1-Click deploy
./deploy-cloudrun.sh

# Or with custom vCPU / RAM sizing
CPU=4 MEMORY=4Gi ./deploy-cloudrun.sh
```

---

## 📄 License
MIT License.
