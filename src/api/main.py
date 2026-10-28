"""FastAPI and Standalone HTTP Application Server (Requirements F1, A4, A8, D3)."""

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from src.api.rate_limiter import rate_limiter
from src.api.routes import (
    handle_get_feedback_summary,
    handle_get_health,
    handle_get_metrics,
    handle_get_quarantine,
    handle_get_run_status,
    handle_get_run_trace,
    handle_post_complaint,
    handle_post_feedback,
    handle_toggle_circuit_breaker,
)
from src.config import settings
from src.observability.logging import get_logger
from src.retrieval.indexer import vector_index

logger = get_logger("api.server")

# Try importing FastAPI if available in environment
try:
    from fastapi import FastAPI, Header, HTTPException, Request, Response, status
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(
        title="Securities Investor Grievance Routing Service",
        description="Multi-agent regulatory triage, jurisdiction mapping, and SCORES/RBI routing service.",
        version="1.0.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def on_startup():
        logger.info("Initializing vector index on service startup...")
        if not vector_index.chunks:
            vector_index.build_or_update()

    @app.post("/api/v1/complaints", status_code=202)
    async def create_complaint(request: Request, x_correlation_id: str = Header(default=None)):
        client_ip = request.client.host if request.client else "127.0.0.1"
        if not rate_limiter.is_allowed(client_ip):
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Please back off.")
        payload = await request.json()
        code, resp = handle_post_complaint(payload, client_ip=client_ip, correlation_id=x_correlation_id)
        if code == 422:
            return JSONResponse(status_code=422, content=resp)
        return JSONResponse(status_code=code, content=resp)

    @app.get("/api/v1/runs/{run_id}")
    async def get_run(run_id: str):
        code, resp = handle_get_run_status(run_id)
        if code == 404:
            raise HTTPException(status_code=404, detail=resp["error"])
        return resp

    @app.get("/api/v1/runs/{run_id}/trace")
    async def get_trace(run_id: str):
        code, resp = handle_get_run_trace(run_id)
        if code == 404:
            raise HTTPException(status_code=404, detail=resp["error"])
        return resp

    @app.post("/api/v1/runs/{run_id}/feedback", status_code=201)
    async def submit_feedback(run_id: str, request: Request):
        payload = await request.json()
        code, resp = handle_post_feedback(run_id, payload)
        return JSONResponse(status_code=code, content=resp)

    @app.get("/api/v1/feedback/summary")
    async def feedback_summary():
        _, resp = handle_get_feedback_summary()
        return resp

    @app.get("/api/v1/quarantine")
    async def get_quarantined():
        _, resp = handle_get_quarantine()
        return resp

    @app.get("/health")
    async def health():
        code, resp = handle_get_health()
        return resp

    @app.get("/metrics")
    async def metrics():
        return PlainTextResponse(content=handle_get_metrics())

    @app.post("/api/v1/admin/toggle-circuit-breaker")
    async def admin_breaker(request: Request):
        payload = await request.json()
        force = bool(payload.get("force_fail", True))
        msg = payload.get("message")
        code, resp = handle_toggle_circuit_breaker(force, msg)
        return resp

    # Serve static web client
    web_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "web")
    if os.path.exists(web_dir):
        app.mount("/static", StaticFiles(directory=web_dir), name="static")

        @app.get("/", response_class=HTMLResponse)
        async def serve_index():
            index_path = os.path.join(web_dir, "index.html")
            with open(index_path, "r", encoding="utf-8") as f:
                return f.read()

except ImportError:
    app = None


# Pure-Python Standalone HTTP Server for Zero-Dependency Execution
class StandaloneHTTPRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Delegate to structured logger
        logger.info(f"{self.command} {self.path} - {args[1] if len(args) > 1 else ''}")

    def _set_headers(self, status_code: int = 200, content_type: str = "application/json"):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Correlation-ID")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(200)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/health":
            code, resp = handle_get_health()
            self._set_headers(code)
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        elif path == "/metrics":
            text = handle_get_metrics()
            self._set_headers(200, "text/plain; version=0.0.4")
            self.wfile.write(text.encode("utf-8"))

        elif path == "/api/v1/quarantine":
            code, resp = handle_get_quarantine()
            self._set_headers(code)
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        elif path == "/api/v1/feedback/summary":
            code, resp = handle_get_feedback_summary()
            self._set_headers(code)
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        elif path.startswith("/api/v1/runs/"):
            parts = path.strip("/").split("/")
            run_id = parts[3] if len(parts) > 3 else ""
            if len(parts) == 5 and parts[4] == "trace":
                code, resp = handle_get_run_trace(run_id)
            else:
                code, resp = handle_get_run_status(run_id)
            self._set_headers(code)
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        elif path in ["/", "/index.html", "/web/index.html"]:
            self._serve_web_file("index.html", "text/html")

        elif path.endswith(".css"):
            self._serve_web_file("style.css", "text/css")

        elif path.endswith(".js"):
            self._serve_web_file("app.js", "application/javascript")

        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode("utf-8"))

    def do_POST(self):
        client_ip = self.client_address[0]
        if not rate_limiter.is_allowed(client_ip):
            self._set_headers(429)
            self.wfile.write(json.dumps({"error": "Rate limit exceeded"}).encode("utf-8"))
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        payload = json.loads(body) if body else {}

        parsed = urlparse(self.path)
        path = parsed.path
        corr_id = self.headers.get("X-Correlation-ID")

        if path == "/api/v1/complaints":
            code, resp = handle_post_complaint(payload, client_ip=client_ip, correlation_id=corr_id)
            self._set_headers(code)
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        elif path.startswith("/api/v1/runs/") and path.endswith("/feedback"):
            parts = path.strip("/").split("/")
            run_id = parts[3]
            code, resp = handle_post_feedback(run_id, payload)
            self._set_headers(code)
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        elif path == "/api/v1/admin/toggle-circuit-breaker":
            force = bool(payload.get("force_fail", True))
            msg = payload.get("message")
            code, resp = handle_toggle_circuit_breaker(force, msg)
            self._set_headers(code)
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode("utf-8"))

    def _serve_web_file(self, filename: str, content_type: str):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        file_path = os.path.join(os.path.dirname(base_dir), "web", filename)
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                content = f.read()
            self._set_headers(200, content_type)
            self.wfile.write(content)
        else:
            self._set_headers(404)
            self.wfile.write(b"File not found")


def run_standalone_server(host: str = "0.0.0.0", port: int = 8000):
    if not vector_index.chunks:
        logger.info("Building initial vector index...")
        vector_index.build_or_update()

    server_address = (host, port)
    httpd = HTTPServer(server_address, StandaloneHTTPRequestHandler)
    logger.info(f"🚀 Securities Grievance Routing Service listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server shutting down gracefully.")
        httpd.server_close()


if __name__ == "__main__":
    host = settings.HOST
    port = settings.PORT
    run_standalone_server(host=host, port=port)
