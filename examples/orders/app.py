"""Intentionally incompatible releases. Stdlib only; never use as a production service."""

import argparse
import json
import os
import sqlite3
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--version", choices=["old", "new", "compatible"], default="old")
parser.add_argument("--damage", action="store_true")
args = parser.parse_args()
database = Path(os.environ["UNDOCI_TRIAL_DIR"]) / "orders.sqlite"


@contextmanager
def connect():
    connection = sqlite3.connect(database, timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


with connect() as db:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS orders (
      id INTEGER PRIMARY KEY, status TEXT NOT NULL, amount INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, text TEXT);
    CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, payload TEXT, done INTEGER DEFAULT 0);
    """)
    if args.damage:
        db.execute("UPDATE orders SET amount = 0")

if args.damage:
    raise SystemExit(0)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        with connect() as db:
            if self.path == "/health":
                return self.reply(200, {"version": args.version})
            if self.path == "/orders":
                rows = [dict(row) for row in db.execute("SELECT * FROM orders ORDER BY id")]
                if args.version == "old" and any(
                    row["status"] not in {"pending", "paid"} for row in rows
                ):
                    return self.reply(500, {"error": "unknown order status"})
                return self.reply(200, rows)
            if self.path == "/jobs":
                rows = [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY id")]
                return self.reply(200, rows)
        return self.reply(404, {"error": "not found"})

    def do_POST(self):
        size = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(size)) if size else {}
            with connect() as db:
                if self.path == "/orders":
                    cursor = db.execute(
                        "INSERT INTO orders(status, amount) VALUES (?, ?)",
                        ("pending", data.get("amount", 100)),
                    )
                    return self.reply(201, {"id": cursor.lastrowid})
                if self.path == "/notes":
                    db.execute("INSERT INTO notes(text) VALUES (?)", (data.get("text", ""),))
                    return self.reply(201, {"saved": True})
                if self.path == "/jobs":
                    field = "recipient" if args.version == "new" else "email"
                    payload = json.dumps({field: "demo@example.test"})
                    db.execute("INSERT INTO jobs(payload) VALUES (?)", (payload,))
                    return self.reply(201, {"queued": True})
                if self.path == "/drain":
                    for row in db.execute("SELECT * FROM jobs WHERE done = 0"):
                        payload = json.loads(row["payload"])
                        if args.version == "old" and "email" not in payload:
                            return self.reply(500, {"error": "old worker needs email"})
                    db.execute("UPDATE jobs SET done = 1")
                    return self.reply(200, {"drained": True})
                parts = self.path.strip("/").split("/")
                if len(parts) == 3 and parts[0] == "orders":
                    row = db.execute("SELECT * FROM orders WHERE id = ?", (parts[1],)).fetchone()
                    if row is None:
                        return self.reply(404, {"error": "order missing"})
                    if parts[2] == "pay":
                        db.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (parts[1],))
                        return self.reply(200, {"status": "paid"})
                    if parts[2] == "refund":
                        if args.version == "old" or row["status"] != "paid":
                            return self.reply(409, {"error": "paid order on new release required"})
                        db.execute(
                            "UPDATE orders SET status = 'partially_refunded' WHERE id = ?",
                            (parts[1],),
                        )
                        return self.reply(200, {"status": "partially_refunded"})
        except (ValueError, TypeError):
            return self.reply(400, {"error": "invalid payload"})
        return self.reply(404, {"error": "not found"})


ThreadingHTTPServer(("127.0.0.1", int(os.environ["UNDOCI_PORT"])), Handler).serve_forever()
