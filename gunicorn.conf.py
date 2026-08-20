import os
import multiprocessing

# Cloud Run dynamic port binding
port = os.environ.get("PORT", "8080")
bind = f"0.0.0.0:{port}"

# Concurrency & Worker model
# On Cloud Run, 1 worker process with multi-threading (gthread) guarantees shared memory,
# thread-safe background scraping jobs, and seamless SSE progress streaming.
workers = 1
threads = int(os.environ.get("GUNICORN_THREADS", 16))
worker_class = "gthread"

# Timeouts & Keep-alive (Cloud Run supports up to 3600s request timeout)
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 1800))
keepalive = 120
graceful_timeout = 30

# Logging to stdout/stderr for Cloud Run Log Viewer
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# Performance tuning
worker_tmp_dir = "/dev/shm"
max_requests = 2000
max_requests_jitter = 200
preload_app = False
