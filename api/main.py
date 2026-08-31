"""HTTP Server for ESG Evidence View (Pure Python Standard Library).

Runs natively without third-party framework version mismatches.
Serves REST API endpoints and static frontend files with year filter & cache control.
"""

import json
import os
import sys
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from api.evidence_service import get_companies, get_evidence

FRONTEND_DIR = REPO_ROOT / "frontend"

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class ESGEvidenceHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, file_path: Path):
        if not file_path.is_file():
            self.send_error(404, "File Not Found")
            return
        
        ext = file_path.suffix.lower()
        mime = MIME_TYPES.get(ext, "application/octet-stream")
        
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Internal Error: {e}")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/companies":
            q_val = query.get("q", [""])[0]
            companies = get_companies(q_val)
            self.send_json(companies)
            return

        if path.startswith("/api/evidence/"):
            ticker = path.split("/api/evidence/")[1].strip()
            year_val = query.get("year", [None])[0]
            evidence = get_evidence(ticker, selected_year=year_val)
            self.send_json(evidence)
            return

        if path.startswith("/static/"):
            rel_path = path[len("/static/"):]
            file_path = FRONTEND_DIR / rel_path
            self.send_file(file_path)
            return

        if path in ("/", "/index.html"):
            self.send_file(FRONTEND_DIR / "index.html")
            return

        target_file = FRONTEND_DIR / path.lstrip("/")
        if target_file.is_file():
            self.send_file(target_file)
        else:
            self.send_error(404, "Not Found")


def run(port: int = 8000):
    server_address = ("", port)
    httpd = HTTPServer(server_address, ESGEvidenceHandler)
    print(f"ESG Evidence View Server running at http://localhost:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    run(8000)
