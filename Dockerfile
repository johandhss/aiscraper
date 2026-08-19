# ==============================================================================
# Production Dockerfile for Website Scraper & MCP Server
# Optimized for Google Cloud Run (Multi-vCPU, Playwright Chromium, Non-Root)
# ==============================================================================

FROM python:3.11-slim-bookworm

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PORT=8080

WORKDIR /app

# Install system dependencies, curl, and build libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    fonts-liberation \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium with system dependencies
RUN mkdir -p /ms-playwright && \
    playwright install --with-deps chromium

# Copy application source code
COPY . .

# Create non-root user for Cloud Run security compliance
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /ms-playwright

USER appuser

# Expose default Cloud Run port
EXPOSE 8080

# Run Gunicorn production server with dynamic Cloud Run configuration
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
