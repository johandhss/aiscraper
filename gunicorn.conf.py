import os
import multiprocessing

# Cloud Run dynamic port binding
port = os.environ.get("PORT", "8080")
bind = f"0.0.0.0:{port}"

# Concurrency & Worker model
# Using gthread for high-efficiency I/O, SSE progress streaming, and background scraping
cpu_cores = multiprocessing.cpu_count()
workers = int(os.environ.get("WEB_CONCURRENCY", max(1, min(cpu_cores, 4))))
threads = int(os.environ.get("GUNICORN_THREADS", 4))
worker_class = "gthread"

# Timeouts & Keep-alive (Cloud Run supports up to 3600s request timeout)
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 600))
keepalive = 120
graceful_timeout = 30

# Logging to stdout/stderr for Cloud Run Log Viewer
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# Performance tuning
worker_tmp_dir = "/dev/shm"
max_requests = 1000
max_requests_jitter = 100
preload_app = False
