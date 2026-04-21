"""FRITZ!Box WAN bandwidth — standalone time-series storage."""

from __future__ import annotations

import logging
import sqlite3

log = logging.getLogger("docsight.fritzbox_wan_bandwidth.storage")


class FbwbStorage:
    """Persists bandwidth samples into the shared DOCSight SQLite file.

    Each sample captures the instantaneous byte rates returned by the FRITZ!Box
    TR-064 ``GetAddonInfos`` action plus the reported max link rates and
    monotonic totals for graphing and long-term correlation.
    """

    BUSY_TIMEOUT_MS = 5000

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={self.BUSY_TIMEOUT_MS}")
        return conn

    def _ensure_table(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS fbwb_samples ("
                "  timestamp TEXT PRIMARY KEY,"
                "  rx_bps INTEGER,"           # downstream byte rate (B/s)
                "  tx_bps INTEGER,"           # upstream byte rate (B/s)
                "  rx_total INTEGER,"         # counter (bytes)
                "  tx_total INTEGER,"         # counter (bytes)
                "  max_down_bps INTEGER,"     # layer-1 downstream max (bit/s)
                "  max_up_bps INTEGER"        # layer-1 upstream max (bit/s)
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fbwb_samples_ts "
                "ON fbwb_samples(timestamp)"
            )

    def save_sample(self, sample: dict) -> None:
        """Insert a single sample; silently ignore duplicate timestamps."""
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO fbwb_samples "
                    "(timestamp, rx_bps, tx_bps, rx_total, tx_total, "
                    "max_down_bps, max_up_bps) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        sample["timestamp"],
                        sample.get("rx_bps"),
                        sample.get("tx_bps"),
                        sample.get("rx_total"),
                        sample.get("tx_total"),
                        sample.get("max_down_bps"),
                        sample.get("max_up_bps"),
                    ),
                )
        except Exception as e:  # noqa: BLE001
            log.warning("fbwb: failed to save sample: %s", e)

    def get_latest(self) -> dict | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT timestamp, rx_bps, tx_bps, rx_total, tx_total, "
                "max_down_bps, max_up_bps FROM fbwb_samples "
                "ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def get_range(self, start_ts: str, end_ts: str, limit: int = 5000) -> list[dict]:
        """Return samples within [start_ts, end_ts] ordered oldest → newest."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT timestamp, rx_bps, tx_bps, rx_total, tx_total, "
                "max_down_bps, max_up_bps FROM fbwb_samples "
                "WHERE timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp ASC LIMIT ?",
                (start_ts, end_ts, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_recent(self, limit: int = 720) -> list[dict]:
        """Return the N most recent samples, oldest → newest."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT timestamp, rx_bps, tx_bps, rx_total, tx_total, "
                "max_down_bps, max_up_bps FROM ("
                "  SELECT * FROM fbwb_samples ORDER BY timestamp DESC LIMIT ?"
                ") ORDER BY timestamp ASC",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def prune_older_than(self, cutoff_ts: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM fbwb_samples WHERE timestamp < ?", (cutoff_ts,)
            )
            return cur.rowcount or 0

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM fbwb_samples").fetchone()
        return row[0] if row else 0
