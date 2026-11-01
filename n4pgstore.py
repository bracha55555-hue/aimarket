"""Durable N4 records in a PostgreSQL database. No payment or custody data."""
import math
import time
import psycopg
from n4store import encode, decode

class N4PostgresStore:
    def __init__(self, dsn):
        if not isinstance(dsn, str) or not dsn.startswith(("postgresql://", "postgres://")):
            raise ValueError("AIMARKET_N4_DATABASE_URL must be a PostgreSQL connection URL")
        self._dsn = dsn
        with self._connect() as db:
            with db.cursor() as cur:
                cur.execute("""CREATE TABLE IF NOT EXISTS n4_entries (
                    kind TEXT NOT NULL, id TEXT NOT NULL,
                    dimension_a TEXT NOT NULL, dimension_b TEXT NOT NULL,
                    expires_at DOUBLE PRECISION NOT NULL, payload BYTEA NOT NULL,
                    PRIMARY KEY (kind, id))""")
                cur.execute("""CREATE INDEX IF NOT EXISTS n4_entries_dimensions
                    ON n4_entries(kind,dimension_a,dimension_b,expires_at)""")

    def _connect(self):
        return psycopg.connect(self._dsn, connect_timeout=10)

    def put(self, kind, id, record, dimension_a="", dimension_b="", expires_at=0):
        if kind not in ("need", "offer", "intent") or not isinstance(id, str) or not id or len(id) > 128:
            raise ValueError("Invalid record identity")
        if any(not isinstance(x, str) or len(x) > 128 for x in (dimension_a, dimension_b)):
            raise ValueError("Invalid dimensions")
        expiry = float(expires_at)
        if not math.isfinite(expiry):
            raise ValueError("Invalid expiry")
        payload = encode(record)
        with self._connect() as db:
            with db.cursor() as cur:
                cur.execute("""INSERT INTO n4_entries
                    (kind,id,dimension_a,dimension_b,expires_at,payload)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (kind,id) DO UPDATE SET
                    dimension_a=EXCLUDED.dimension_a,
                    dimension_b=EXCLUDED.dimension_b,
                    expires_at=EXCLUDED.expires_at,
                    payload=EXCLUDED.payload""",
                    (kind, id, dimension_a, dimension_b, expiry, payload))

    def delete(self, kind, id):
        with self._connect() as db:
            with db.cursor() as cur:
                cur.execute("DELETE FROM n4_entries WHERE kind=%s AND id=%s", (kind, id))

    def scan(self, kind, dimension_a=None, dimension_b=None, now=None):
        current = time.time() if now is None else float(now)
        query = "SELECT id,payload FROM n4_entries WHERE kind=%s AND expires_at>%s"
        args = [kind, current]
        if dimension_a is not None:
            query += " AND dimension_a=%s"
            args.append(dimension_a)
        if dimension_b is not None:
            query += " AND dimension_b=%s"
            args.append(dimension_b)
        with self._connect() as db:
            with db.cursor() as cur:
                cur.execute(query, args)
                return {key: decode(bytes(blob)) for key, blob in cur.fetchall()}

    def purge(self, now=None):
        current = time.time() if now is None else float(now)
        with self._connect() as db:
            with db.cursor() as cur:
                cur.execute("DELETE FROM n4_entries WHERE expires_at<=%s", (current,))
                return cur.rowcount

    def count(self, kind, now=None):
        current = time.time() if now is None else float(now)
        with self._connect() as db:
            with db.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM n4_entries WHERE kind=%s AND expires_at>%s",
                            (kind, current))
                return cur.fetchone()[0]

    def close(self):
        pass
