"""Loopback bridge from the app container to the host's authenticated Codex CLI."""
from __future__ import annotations

import json
import logging
import select
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from .evaluation import _codex_chat
except ImportError:
    from evaluation import _codex_chat


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/judge":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 100_000:
                raise ValueError("request size out of range")
            payload = json.loads(self.rfile.read(length))
            if payload.get("model") != "gpt-5.6-luna":
                raise ValueError("unsupported evaluator model")
            quota_before = read_quota()
            output, usage = _codex_chat(payload["messages"], payload["model"], payload["schema"])
            quota_after = read_quota()
            if quota_before is not None:
                usage["five_hour_used_percent_before"] = quota_before["used_percent"]
            if quota_after is not None:
                usage["five_hour_used_percent_after"] = quota_after["used_percent"]
                usage["five_hour_resets_at"] = quota_after["resets_at"]
            body = json.dumps({"output": output, "usage": usage}).encode()
            self.send_response(200)
        except Exception as exc:
            logging.exception("Codex judge request failed")
            body = json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode()
            self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def read_quota() -> dict | None:
    """Read the account's five hour Codex quota without starting a model turn."""
    process = subprocess.Popen(["codex", "app-server", "--stdio"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    try:
        requests = [
            {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "millennium-judge", "version": "1"}, "capabilities": None}},
            {"method": "initialized", "params": {}},
            {"id": 2, "method": "account/rateLimits/read", "params": {"excludeResetCreditDetails": True}},
        ]
        for request in requests:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], 1)
            if not ready:
                continue
            line = process.stdout.readline()
            if not line:
                break
            message = json.loads(line)
            if message.get("id") != 2:
                continue
            result = message.get("result") or {}
            limits = result.get("rateLimitsByLimitId") or {}
            snapshot = limits.get("codex") or result.get("rateLimits") or {}
            primary = snapshot.get("primary") or {}
            if primary.get("windowDurationMins") == 300 and isinstance(primary.get("usedPercent"), (int, float)):
                return {"used_percent": primary["usedPercent"], "resets_at": primary.get("resetsAt")}
            return None
    except (OSError, ValueError, BrokenPipeError):
        logging.exception("Codex quota read failed")
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
    return None


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 4097), Handler).serve_forever()
