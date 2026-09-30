"""Small PostgreSQL release-compatibility fixture. Intentionally not production code."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg
from psycopg.rows import dict_row

RELEASE = os.environ["RELEASE"]
DSN = os.environ["DATABASE_URL"]


def connect():
    return psycopg.connect(DSN, autocommit=True, row_factory=dict_row)


with connect() as db:
    db.execute(
        "CREATE TABLE IF NOT EXISTS orders "
        "(id SERIAL PRIMARY KEY, status TEXT NOT NULL, amount INTEGER NOT NULL)"
    )
    db.execute("CREATE TABLE IF NOT EXISTS notes (id SERIAL PRIMARY KEY, text TEXT)")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self.reply(200, {"version": RELEASE})
        if self.path == "/orders":
            with connect() as db:
                rows = db.execute("SELECT * FROM orders ORDER BY id").fetchall()
            if RELEASE == "old" and any(row["status"] == "partially_refunded" for row in rows):
                return self.reply(500, {"error": "unsupported status"})
            return self.reply(200, rows)
        return self.reply(404, {"error": "not found"})

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(size)) if size else {}
            with connect() as db:
                if self.path == "/orders":
                    row = db.execute(
                        "INSERT INTO orders(status, amount) VALUES (%s, %s) RETURNING id",
                        ("pending", data.get("amount", 100)),
                    ).fetchone()
                    return self.reply(201, row)
                if self.path == "/notes":
                    db.execute("INSERT INTO notes(text) VALUES (%s)", (data.get("text", ""),))
                    return self.reply(201, {"saved": True})
                parts = self.path.strip("/").split("/")
                if len(parts) == 3 and parts[0] == "orders":
                    row = db.execute("SELECT * FROM orders WHERE id = %s", (parts[1],)).fetchone()
                    if not row:
                        return self.reply(404, {"error": "missing order"})
                    if parts[2] == "pay":
                        db.execute("UPDATE orders SET status = 'paid' WHERE id = %s", (parts[1],))
                        return self.reply(200, {"status": "paid"})
                    if parts[2] == "refund":
                        if RELEASE == "old" or row["status"] != "paid":
                            return self.reply(409, {"error": "paid order required"})
                        db.execute(
                            "UPDATE orders SET status = 'partially_refunded' WHERE id = %s",
                            (parts[1],),
                        )
                        return self.reply(200, {"status": "partially_refunded"})
        except (ValueError, TypeError):
            return self.reply(400, {"error": "invalid request"})
        return self.reply(404, {"error": "not found"})


ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
