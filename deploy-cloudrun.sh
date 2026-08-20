#!/usr/bin/env bash
# ==============================================================================
# 🚀 1-Click Deploy Script for Google Cloud Run
# Deploys Website Scraper & MCP Server with Multi-vCPU Parallel Processing
# ==============================================================================

set -e

SERVICE_NAME="${SERVICE_NAME:-aiscraper}"
REGION="${REGION:-europe-west4}"
CPU="${CPU:-2}"
MEMORY="${MEMORY:-4Gi}"
TIMEOUT="${TIMEOUT:-600}"
MAX_INSTANCES="${MAX_INSTANCES:-5}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"
CONCURRENCY="${CONCURRENCY:-40}"

echo "=================================================================="
echo "⚡ Deploying '${SERVICE_NAME}' to Google Cloud Run"
echo "   Region:      ${REGION}"
echo "   vCPUs:       ${CPU}"
echo "   Memory:      ${MEMORY}"
echo "   Timeout:     ${TIMEOUT}s"
echo "=================================================================="

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "❌ Error: 'gcloud' CLI is not installed."
    echo "   Install Google Cloud SDK: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Load local .env if present to extract required keys
ENV_FILE=".env"
if [ -f "$ENV_FILE" ]; then
    echo "📄 Reading credentials from local .env file..."
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

# Validate required environment variables
if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_KEY" ]; then
    echo "❌ Error: SUPABASE_URL and SUPABASE_KEY must be set in .env or exported."
    exit 1
fi

if [ -z "$OPENAI_API_KEY" ]; then
    echo "⚠️ Warning: OPENAI_API_KEY is not set. Semantic analysis will use heuristic fallback."
fi

if [ -z "$MCP_API_KEY" ]; then
    echo "⚠️ Warning: MCP_API_KEY is not set. Generating a random key..."
    MCP_API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
fi

MAX_CONCURRENT_SCRAPERS="${MAX_CONCURRENT_SCRAPERS:-2}"

echo ""
echo "📦 Building container image & deploying to Cloud Run..."
echo ""

gcloud run deploy "$SERVICE_NAME" \
    --source . \
    --region "$REGION" \
    --platform managed \
    --allow-unauthenticated \
    --cpu "$CPU" \
    --memory "$MEMORY" \
    --timeout "$TIMEOUT" \
    --concurrency "$CONCURRENCY" \
    --min-instances "$MIN_INSTANCES" \
    --max-instances "$MAX_INSTANCES" \
    --no-cpu-throttling \
    --set-env-vars "SUPABASE_URL=${SUPABASE_URL},SUPABASE_KEY=${SUPABASE_KEY},OPENAI_API_KEY=${OPENAI_API_KEY},MCP_API_KEY=${MCP_API_KEY},MAX_CONCURRENT_SCRAPERS=${MAX_CONCURRENT_SCRAPERS},PORT=8080"

echo ""
echo "=================================================================="
echo "✅ Deployment complete!"
echo "   MCP API Endpoint:    https://<YOUR-CLOUD-RUN-URL>/api/mcp"
echo "   MCP API Key:         ${MCP_API_KEY}"
echo "   Parallel Workers:    ${MAX_CONCURRENT_SCRAPERS} concurrent browser scrapers"
echo "=================================================================="
