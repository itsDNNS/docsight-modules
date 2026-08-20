"""Storage for FritzBox DoT Guard historical data."""

import logging
import sqlite3

from app.storage.sqlite import connect_sqlite

log = logging.getLogger("docsis.storage.fritzdotguard")


class FritzDoTGuardStorage:
    """Standalone DoT Guard storage for historical DoT status snapshots."""

    def __init__(self, db_path):
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self):
        with connect_sqlite(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS fritzdotguard_status ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  timestamp TEXT NOT NULL,"
                "  dot_ok INTEGER NOT NULL,"
                "  details TEXT,"
                "  event_type TEXT,"
                "  is_demo INTEGER NOT NULL DEFAULT 0"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fritzdotguard_ts "
                "ON fritzdotguard_status(timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fritzdotguard_ok "
                "ON fritzdotguard_status(dot_ok)"
            )

    def save_status(self, timestamp, dot_ok, details, event_type=None, is_demo=False):
        with connect_sqlite(self.db_path) as conn:
            conn.execute(
                "INSERT INTO fritzdotguard_status "
                "(timestamp, dot_ok, details, event_type, is_demo) "
                "VALUES (?, ?, ?, ?, ?)",
                (timestamp, 1 if dot_ok else 0, details, event_type,
                 1 if is_demo else 0),
            )

    def save_status_batch(self, records):
        with connect_sqlite(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO fritzdotguard_status "
                "(timestamp, dot_ok, details, event_type, is_demo) "
                "VALUES (?, ?, ?, ?, ?)",
                [(r["timestamp"], 1 if r["dot_ok"] else 0,
                  r.get("details"), r.get("event_type"),
                  1 if r.get("is_demo") else 0) for r in records],
            )

    def get_status_range(self, start_ts, end_ts):
        with connect_sqlite(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT timestamp, dot_ok, details, event_type "
                "FROM fritzdotguard_status "
                "WHERE timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp ASC",
                (start_ts, end_ts),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_recent_status(self, limit=100):
        with connect_sqlite(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT timestamp, dot_ok, details, event_type "
                "FROM fritzdotguard_status "
                "ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_outage_count_since(self, since_ts):
        with connect_sqlite(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM fritzdotguard_status "
                "WHERE dot_ok = 0 AND timestamp >= ?",
                (since_ts,),
            ).fetchone()
            return row[0] if row else 0

    def get_last_outage_time(self):
        with connect_sqlite(self.db_path) as conn:
            row = conn.execute(
                "SELECT timestamp FROM fritzdotguard_status "
                "WHERE dot_ok = 0 ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None

    def cleanup_old(self, days=90):
        with connect_sqlite(self.db_path) as conn:
            conn.execute(
                "DELETE FROM fritzdotguard_status "
                "WHERE timestamp < datetime('now', ? || ' days')",
                (f"-{days}",),
            )
