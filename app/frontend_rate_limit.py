"""Durable sliding-window quotas for production frontend questions."""
from __future__ import annotations

import math
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path


WINDOWS = ((60, 3), (30 * 60, 10), (60 * 60, 15), (24 * 60 * 60, 25))


def reserve_request(ip: str, *, path: Path | None = None, now_ms: int | None = None) -> int | None:
    """Record an accepted request; return retry-after seconds when any quota is full."""
    if now_ms is None:
        now_ms = time.time_ns() // 1_000_000
    if path is None:
        path = Path(os.getenv("EXPERIMENT_DATA_DIR", "./data")) / "frontend-rate-limits.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=30, isolation_level=None)) as db:
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("CREATE TABLE IF NOT EXISTS requests (ip TEXT NOT NULL, at_ms INTEGER NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS requests_ip_at ON requests(ip, at_ms)")
        db.execute("CREATE INDEX IF NOT EXISTS requests_at ON requests(at_ms)")
        db.execute("BEGIN IMMEDIATE")
        try:
            oldest = now_ms - WINDOWS[-1][0] * 1000
            db.execute("DELETE FROM requests WHERE at_ms <= ?", (oldest,))
            stamps = [row[0] for row in db.execute(
                "SELECT at_ms FROM requests WHERE ip = ? ORDER BY at_ms", (ip,)
            )]
            retry_ms = 0
            for seconds, maximum in WINDOWS:
                recent = [stamp for stamp in stamps if stamp > now_ms - seconds * 1000]
                if len(recent) >= maximum:
                    retry_ms = max(retry_ms, recent[len(recent) - maximum] + seconds * 1000 - now_ms)
            if retry_ms:
                db.execute("COMMIT")
                return max(1, math.ceil(retry_ms / 1000))
            db.execute("INSERT INTO requests(ip, at_ms) VALUES(?, ?)", (ip, now_ms))
            db.execute("COMMIT")
            return None
        except BaseException:
            db.execute("ROLLBACK")
            raise
