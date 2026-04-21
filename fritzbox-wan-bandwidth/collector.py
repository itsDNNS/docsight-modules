"""FRITZ!Box WAN bandwidth collector.

Polls the AVM TR-064 ``WANCommonInterfaceConfig`` service and stores the
current downstream/upstream byte rates plus the reported link max bitrates
as a local time-series.

TR-064 requires the "Zugriff für Anwendungen" option on the FRITZ!Box and a
FRITZ!Box user with at least "Smart Home" or equivalent permission.
"""

from __future__ import annotations

import logging
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests
from requests.auth import HTTPDigestAuth

from app.collectors.base import Collector, CollectorResult

from .storage import FbwbStorage

log = logging.getLogger("docsight.fritzbox_wan_bandwidth")

_SOAP_NS = "urn:dslforum-org:service:WANCommonInterfaceConfig:1"
_ENVELOPE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
    "<s:Body><u:{action} xmlns:u=\"" + _SOAP_NS + "\"/></s:Body>"
    "</s:Envelope>"
)

_MIN_INTERVAL = 10
_MAX_INTERVAL = 3600


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_cfg(cfg_mgr) -> dict:
    host = (cfg_mgr.get("fbwb_host") or "").strip()
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.rstrip("/").split("/", 1)[0]
    port = int(cfg_mgr.get("fbwb_port", 49000) or 49000)
    use_tls = bool(cfg_mgr.get("fbwb_use_tls", False))
    scheme = "https" if use_tls else "http"
    return {
        "host": host,
        "port": port,
        "use_tls": use_tls,
        "base": f"{scheme}://{host}:{port}" if host else "",
        "username": cfg_mgr.get("fbwb_username", "") or "",
        "password": cfg_mgr.get("fbwb_password", "") or "",
    }


def _soap_call(cfg: dict, action: str, timeout: int = 10) -> dict:
    """Invoke a TR-064 SOAP action and return its flattened response fields."""
    if not cfg["host"]:
        raise ValueError("FRITZ!Box host not configured")

    url = f"{cfg['base']}/upnp/control/wancommonifconfig1"
    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPACTION": f'"{_SOAP_NS}#{action}"',
    }
    body = _ENVELOPE.format(action=action)
    auth = HTTPDigestAuth(cfg["username"], cfg["password"])

    resp = requests.post(
        url,
        data=body,
        headers=headers,
        auth=auth,
        timeout=timeout,
        # TR-064 on FRITZ!Box uses a self-signed cert on 49443.
        verify=False,
    )
    if resp.status_code == 401:
        raise PermissionError("TR-064 authentication failed (HTTP 401)")
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    out: dict[str, str] = {}
    for elem in root.iter():
        tag = elem.tag.split("}", 1)[-1]
        if tag.startswith("New") and elem.text is not None:
            out[tag] = elem.text.strip()
    return out


def _coerce_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class FritzBandwidthCollector(Collector):
    """Periodically polls FRITZ!Box TR-064 for current WAN bandwidth counters."""

    name = "fritzbox_wan_bandwidth"

    def __init__(self, config_mgr, storage, web, **kwargs):
        interval = int(config_mgr.get("fbwb_interval", 30) or 30)
        interval = max(_MIN_INTERVAL, min(_MAX_INTERVAL, interval))
        super().__init__(poll_interval_seconds=interval)
        self._cfg_mgr = config_mgr
        self._storage = FbwbStorage(storage.db_path)
        self._web = web
        self._lock = threading.Lock()
        self._last_sample: dict | None = None
        self._link: dict | None = None
        self._link_fetched_at: float = 0.0
        self._last_prune: datetime | None = None

    def is_enabled(self) -> bool:
        cfg = self._cfg_mgr
        return bool(cfg.get("fbwb_enabled", False)) and bool(
            (cfg.get("fbwb_host") or "").strip()
        )

    def collect(self) -> CollectorResult:
        cfg = _build_cfg(self._cfg_mgr)
        if not cfg["host"]:
            return CollectorResult.failure(self.name, "Host not configured")

        try:
            addon = _soap_call(cfg, "GetAddonInfos")
        except PermissionError:
            return CollectorResult.failure(self.name, "Authentication failed")
        except requests.exceptions.ConnectionError:
            return CollectorResult.failure(self.name, "Connection failed")
        except requests.exceptions.Timeout:
            return CollectorResult.failure(self.name, "Timeout")
        except ET.ParseError:
            return CollectorResult.failure(self.name, "Invalid TR-064 response")
        except Exception:  # noqa: BLE001
            log.exception("fbwb: collect failed")
            return CollectorResult.failure(self.name, "Internal error")

        link = self._refresh_link_props(cfg)

        sample = {
            "timestamp": _utc_now_iso(),
            "rx_bps":       _coerce_int(addon.get("NewByteReceiveRate")),
            "tx_bps":       _coerce_int(addon.get("NewByteSendRate")),
            "rx_total":     _coerce_int(addon.get("NewTotalBytesReceived"))
                            or _coerce_int(addon.get("NewX_AVM_DE_TotalBytesReceived64")),
            "tx_total":     _coerce_int(addon.get("NewTotalBytesSent"))
                            or _coerce_int(addon.get("NewX_AVM_DE_TotalBytesSent64")),
            "max_down_bps": (link or {}).get("max_down_bps"),
            "max_up_bps":   (link or {}).get("max_up_bps"),
        }

        self._storage.save_sample(sample)
        with self._lock:
            self._last_sample = sample
        self._maybe_prune()

        return CollectorResult.ok(self.name, sample)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _refresh_link_props(self, cfg: dict) -> dict | None:
        """Fetch max link rates at most once every 10 min; cheap enough to keep fresh."""
        import time

        now = time.time()
        if self._link is not None and (now - self._link_fetched_at) < 600:
            return self._link
        try:
            raw = _soap_call(cfg, "GetCommonLinkProperties", timeout=8)
        except Exception as e:  # noqa: BLE001
            log.debug("fbwb: link props fetch failed: %s", e)
            return self._link
        link = {
            "max_down_bps": _coerce_int(raw.get("NewLayer1DownstreamMaxBitRate")),
            "max_up_bps":   _coerce_int(raw.get("NewLayer1UpstreamMaxBitRate")),
            "link_status":  raw.get("NewPhysicalLinkStatus"),
            "access_type":  raw.get("NewWANAccessType"),
        }
        self._link = link
        self._link_fetched_at = now
        return link

    def _maybe_prune(self) -> None:
        """Prune old samples at most once per hour."""
        now = datetime.now(timezone.utc)
        if self._last_prune and (now - self._last_prune) < timedelta(hours=1):
            return
        days = int(self._cfg_mgr.get("fbwb_history_days", 7) or 7)
        if days <= 0:
            self._last_prune = now
            return
        cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            removed = self._storage.prune_older_than(cutoff)
            if removed:
                log.info("fbwb: pruned %d samples older than %s", removed, cutoff)
        except Exception:  # noqa: BLE001
            log.warning("fbwb: prune failed", exc_info=True)
        self._last_prune = now

    def snapshot(self) -> dict:
        """Latest in-memory sample + cached link info (for API layer)."""
        with self._lock:
            sample = dict(self._last_sample) if self._last_sample else None
        return {"sample": sample, "link": dict(self._link) if self._link else None}
