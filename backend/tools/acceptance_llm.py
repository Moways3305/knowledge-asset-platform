"""Deterministic, isolated LLM stand-in; never used in production."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if os.environ.get("KAP_ACCEPTANCE_ISOLATED") != "1":
    raise RuntimeError("Test environment only")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        content = {
            "topic": "Acceptance document",
            "one_liner": "Synthetic acceptance material",
            "detailed": "Synthetic content used only to exercise concurrent ingestion.",
            "key_points": ["Synthetic", "No real customer data"],
            "tags": ["acceptance"],
            "confidentiality_level": "L2",
            "confidentiality_confidence": "high",
            "version": "V1",
            "version_confidence": "high",
            "inferred_fields": [],
        }
        payload = json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 9000), Handler).serve_forever()
