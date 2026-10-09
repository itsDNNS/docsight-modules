"""
UniFi WAN Monitor — Collector  v3.3.0

Polls /proxy/network/api/s/{site}/stat/device and extracts WAN status
from the UDM/UCG gateway device entry.

State tracked per interface:
  - up        (link state from wan1/wan2.up)
  - alive     (from last_wan_interfaces.WAN/WAN2.alive)
  - online    (from last_wan_status.WAN/WAN2 == "online")
  - is_uplink (active WAN interface — failover detection)

Review fixes applied:
  - No global urllib3.disable_warnings(); verify=False set on session only
  - _build_cfg_from validates and normalises host/port/protocol
  - _write_events uses save_event() directly (no fragile hasattr branching)
  - All event messages in English; German translations live in i18n/de.json
  - Blueprint static_url_path removed (no static/ dir exists)
"""

import json
import logging
import re
import threading
from urllib.parse import urlparse, urlunparse

import requests

from app.collectors.base import Collector, CollectorResult
from app.tz import utc_now

logger = logging.getLogger("docsight.udm_wan_monitor")

# ── In-process WAN state ─────────────────────────────────────────────────────
_state_lock = threading.Lock()
_state = {
    "wan1": {"up": None, "alive": None, "online": None, "is_uplink": None},
    "wan2": {"up": None, "alive": None, "online": None, "is_uplink": None},
}


def _result_ok(source: str, data) -> CollectorResult:
    if hasattr(CollectorResult, "ok"):
        return CollectorResult.ok(source, data)
    return CollectorResult(source=source, data=data, success=True)


def _result_failure(source: str, error: str) -> CollectorResult:
    if hasattr(CollectorResult, "failure"):
        return CollectorResult.failure(source, error)
    return CollectorResult(source=source, success=False, error=error)


class UdmWanCollector(Collector):
    name = "udm_wan_monitor"

    def __init__(self, config_mgr, storage, web, **kwargs):
        interval = int(config_mgr.get("udm_wan_interval", 60) or 60)
        super().__init__(poll_interval_seconds=interval)
        self._cfg     = config_mgr
        self._storage = storage
        self._web     = web
        self._session: requests.Session | None = None
        self._session_lock = threading.Lock()
        self._last_result: dict | None = None

    def is_enabled(self) -> bool:
        return bool(self._cfg.get("udm_wan_enabled", False))

    def collect(self) -> CollectorResult:
        cfg = _build_cfg_from(self._cfg)
        if not cfg["host"]:
            return _result_failure(self.name, "UDM host not configured")
        try:
            session = self._get_session(cfg)
            device  = _fetch_udm_device(
                session, cfg, allow_no_wan=bool(parse_extra_ports(self._cfg))
            )
        except PermissionError:
            self._invalidate_session()
            return _result_failure(self.name, "Authentication failed")
        except LookupError as exc:
            return _result_failure(self.name, str(exc))
        except requests.exceptions.ConnectionError:
            self._invalidate_session()
            return _result_failure(self.name, "Connection error")
        except requests.exceptions.Timeout:
            self._invalidate_session()
            return _result_failure(self.name, "Timeout")
        except Exception:  # noqa: BLE001
            self._invalidate_session()
            logger.exception("UDM WAN collect failed")
            return _result_failure(self.name, "Internal error")

        parsed = parse_device(device)
        events = self._detect_changes(parsed)
        if events:
            self._write_events(events)

        ts = utc_now()
        self._last_result = {"parsed": parsed, "timestamp": ts}
        return _result_ok(self.name, {"parsed": parsed, "events": events, "timestamp": ts})

    # ── Session management ────────────────────────────────────────────────────

    def _get_session(self, cfg) -> requests.Session:
        with self._session_lock:
            if self._session is None:
                self._session = _login(cfg)
            return self._session

    def _invalidate_session(self):
        with self._session_lock:
            self._session = None

    # ── State-change detection ────────────────────────────────────────────────

    def _detect_changes(self, parsed: dict) -> list[dict]:
        events: list[dict] = []
        now = utc_now()
        primary = primary_wan(self._cfg)

        def sev(severity: str, key: str) -> str:
            if primary and key != primary and severity == "critical":
                return "warning"
            return severity

        with _state_lock:
            # Failover: active uplink interface changed
            new_uplink = next(
                (k for k in ("wan1", "wan2") if parsed.get(k, {}).get("is_uplink")),
                None,
            )
            old_uplink = next(
                (k for k in ("wan1", "wan2") if _state[k]["is_uplink"] is True),
                None,
            )
            if old_uplink is not None and new_uplink is not None and old_uplink != new_uplink:
                old_lbl = "WAN 1" if old_uplink == "wan1" else "WAN 2"
                new_lbl = "WAN 1" if new_uplink == "wan1" else "WAN 2"
                msg = f"WAN failover: {old_lbl} → {new_lbl} is now the active uplink"
                self._append_event(events, now, "warning", msg, new_lbl, "failover", None)

            # Per-interface state checks
            for key in ("wan1", "wan2"):
                w     = parsed.get(key, {})
                label = "WAN 1" if key == "wan1" else "WAN 2"
                prev  = _state[key]
                ip    = w.get("ip")

                cur_up       = w.get("up")
                cur_alive    = w.get("alive")
                cur_online   = w.get("online")
                cur_is_uplink= w.get("is_uplink", False)

                # Always update is_uplink (baseline or current)
                prev["is_uplink"] = cur_is_uplink

                # ── alive + online (combined event logic) ─────────────────────
                first_alive  = prev["alive"]  is None
                first_online = prev["online"] is None

                if first_alive:
                    prev["alive"] = cur_alive
                if first_online:
                    prev["online"] = cur_online

                if not first_alive and not first_online:
                    alive_ch  = cur_alive  != prev["alive"]
                    online_ch = cur_online != prev["online"]

                    if alive_ch or online_ch:
                        prev["alive"]  = cur_alive
                        prev["online"] = cur_online

                        both_down = alive_ch and not cur_alive and online_ch and not cur_online
                        both_up   = alive_ch and cur_alive     and online_ch and cur_online

                        if both_down:
                            msg = f"{label} ({ip or '?'}): down — alive=false, offline"
                            self._append_event(events, now, sev("critical", key), msg, label, "down", ip)
                        elif both_up:
                            msg = f"{label} ({ip or '?'}): restored — alive=true, online"
                            self._append_event(events, now, "info", msg, label, "up", ip)
                        else:
                            if alive_ch:
                                degraded = not cur_alive
                                msg = _event_msg(label, "alive", cur_alive, ip)
                                self._append_event(
                                    events, now,
                                    sev("critical", key) if degraded else "info",
                                    msg, label,
                                    "alive_down" if degraded else "alive_up", ip,
                                )
                            if online_ch:
                                degraded = not cur_online
                                msg = _event_msg(label, "online", cur_online, ip)
                                self._append_event(
                                    events, now,
                                    sev("critical", key) if degraded else "info",
                                    msg, label,
                                    "offline" if degraded else "online", ip,
                                )

                # ── link state (always individual) ────────────────────────────
                if prev["up"] is None:
                    prev["up"] = cur_up
                elif cur_up != prev["up"]:
                    prev["up"] = cur_up
                    degraded = not cur_up
                    msg = _event_msg(label, "up", cur_up, ip)
                    self._append_event(
                        events, now,
                        sev("critical", key) if degraded else "info",
                        msg, label,
                        "link_down" if degraded else "link_up", ip,
                    )

        return events

    @staticmethod
    def _append_event(events, now, severity, msg, iface, direction, ip):
        events.append({
            "timestamp":  now,
            "severity":   severity,
            "event_type": "udm_wan",
            "message":    msg,
            "details": {
                "interface": iface,
                "direction": direction,
                "ip":        ip,
                "source":    "community.udm_wan_monitor",
            },
        })
        logger.warning("UDM WAN EVENT: %s", msg)

    def _write_events(self, events: list[dict]) -> None:
        """Write events to DOCSight's global event log via save_event()."""
        if not self._storage:
            return
        try:
            for ev in events:
                self._storage.save_event(
                    timestamp  = ev["timestamp"],
                    severity   = ev["severity"],
                    event_type = ev["event_type"],
                    message    = ev["message"],
                    details    = ev.get("details"),
                )
            logger.info("UDM WAN: wrote %d event(s) to global log", len(events))
        except Exception:  # noqa: BLE001
            logger.warning("UDM WAN: could not write events to global log", exc_info=True)


# ── Module-level helpers (shared with routes.py) ──────────────────────────────

def _safe_site(s: str) -> str:
    """Validate site name to prevent path traversal."""
    return s if re.fullmatch(r'[a-zA-Z0-9_-]+', s) else "default"


def _build_cfg_from(cfg) -> dict:
    """
    Build a normalised config dict from the DOCSight config manager.

    Handles these host inputs safely:
      - bare IP/hostname:     "10.10.10.254"
      - with protocol:        "https://10.10.10.254"
      - with protocol+port:   "https://10.10.10.254:8443"
    Port from the config field always takes precedence over any port in the host string.
    Protocol is always forced to https.
    """
    raw_host = (cfg.get("udm_wan_host") or "").strip().rstrip("/")
    cfg_port = int(cfg.get("udm_wan_port", 443) or 443)

    if raw_host:
        # Ensure we have a parseable URL
        if "://" not in raw_host:
            raw_host = "https://" + raw_host
        parsed = urlparse(raw_host)
        hostname = parsed.hostname or ""          # pure hostname, no port
        base = urlunparse(("https", f"{hostname}:{cfg_port}", "", "", "", ""))
    else:
        hostname = ""
        base = ""

    return {
        "host":       hostname,
        "base":       base,
        "username":   cfg.get("udm_wan_username", ""),
        "password":   cfg.get("udm_wan_password", ""),
        "site":       _safe_site((cfg.get("udm_wan_site") or "default").strip()),
        "verify_ssl": bool(cfg.get("udm_wan_verify_ssl", False)),
    }


def _login(cfg: dict) -> requests.Session:
    """Authenticate with UniFi OS 5.x (with legacy /api/login fallback)."""
    session = requests.Session()
    session.verify = cfg["verify_ssl"]   # verify=False per-session, not globally
    payload = {"username": cfg["username"], "password": cfg["password"], "remember": True}
    headers = {"Content-Type": "application/json"}

    r = session.post(
        f"{cfg['base']}/api/auth/login", json=payload, headers=headers, timeout=15
    )
    if r.status_code in (404, 405):
        r = session.post(
            f"{cfg['base']}/api/login", json=payload, headers=headers, timeout=15
        )
    r.raise_for_status()

    token = r.headers.get("X-Updated-Csrf-Token") or r.headers.get("csrf-token")
    if token:
        session.headers["X-Csrf-Token"] = token
    logger.info("UDM WAN: login successful")
    return session


GATEWAY_TYPES = ("udm", "ugw", "usg", "ucg")


def select_gateway(devices: list[dict]) -> dict | None:
    for d in devices:
        if d.get("type") in GATEWAY_TYPES and "wan1" in d:
            return d
    for d in devices:
        if "wan1" in d:
            return d
    return next((d for d in devices if d.get("type") in GATEWAY_TYPES), None)


def primary_wan(cfg) -> str | None:
    value = str(cfg.get("udm_wan_primary") or "").strip().lower()
    return value if value in ("wan1", "wan2") else None


MAX_EXTRA_PORTS = 8
_IFNAME_RE = re.compile(r"[A-Za-z0-9_.:-]{1,32}")


def parse_extra_ports(cfg) -> list[dict]:
    raw = cfg.get("udm_wan_extra_ports")
    entries = []
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            entries = parsed if isinstance(parsed, list) else []
        except ValueError:
            entries = []
    elif not raw:
        for i in (1, 2):
            entries.append({
                "ifname": cfg.get(f"udm_wan_extra_port{i}_ifname"),
                "alias": cfg.get(f"udm_wan_extra_port{i}_alias"),
            })

    ports, seen = [], set()
    for e in entries:
        if not isinstance(e, dict):
            continue
        ifname = str(e.get("ifname") or "").strip().lower()
        if not _IFNAME_RE.fullmatch(ifname) or ifname in seen:
            continue
        seen.add(ifname)
        alias = str(e.get("alias") or "").strip()[:40] or ifname
        ports.append({"ifname": ifname, "alias": alias})
        if len(ports) >= MAX_EXTRA_PORTS:
            break
    return ports


def has_wan(device: dict) -> bool:
    return any(
        (device.get(k) or {}).get("ifname") or (device.get(k) or {}).get("name")
        for k in ("wan1", "wan2")
    )


def _fetch_udm_device(session: requests.Session, cfg: dict, allow_no_wan: bool = False) -> dict:
    """Fetch /stat/device and return the UDM/gateway device entry."""
    url = f"{cfg['base']}/proxy/network/api/s/{cfg['site']}/stat/device"
    r = session.get(url, timeout=15)
    if r.status_code == 401:
        raise PermissionError("Session expired (401)")
    r.raise_for_status()
    gateway = select_gateway(r.json().get("data", []))
    if gateway is None:
        raise LookupError("No gateway device found")
    if not allow_no_wan and not has_wan(gateway):
        raise LookupError(
            "No WAN interface (wan1/wan2) found on gateway; "
            "define the WAN port manually in the module settings"
        )
    return gateway


def build_wan_ports(device: dict, parsed: dict, extra_ports: list[dict]) -> list[dict]:
    wanted = {ep["ifname"]: ep["alias"] for ep in extra_ports}
    order = {}
    for idx, key in enumerate(("wan1", "wan2")):
        ifname = (parsed.get(key, {}).get("ifname") or "").lower()
        if ifname:
            wanted[ifname] = f"WAN {idx + 1}"
            order[ifname] = idx

    rows = []
    for p in device.get("port_table", []):
        ifname_raw = p.get("ifname") or ""
        label = wanted.get(ifname_raw.lower())
        if label is None:
            continue
        rows.append({
            "label":       label,
            "name":        p.get("name"),
            "ifname":      ifname_raw,
            "up":          p.get("up"),
            "speed":       p.get("speed"),
            "full_duplex": p.get("full_duplex"),
            "rx_bytes":    p.get("rx_bytes"),
            "tx_bytes":    p.get("tx_bytes"),
            "rx_bytes_r":  p.get("rx_bytes-r"),
            "tx_bytes_r":  p.get("tx_bytes-r"),
            "rx_errors":   p.get("rx_errors"),
            "tx_errors":   p.get("tx_errors"),
            "rx_dropped":  p.get("rx_dropped"),
            "tx_dropped":  p.get("tx_dropped"),
        })
    rows.sort(key=lambda r: order.get(r["ifname"].lower(), 99))
    return rows


def _global_ipv6(addresses) -> str | None:
    for addr in addresses or []:
        a = str(addr).strip().lower()
        if a and not a.startswith(("fe8", "fe9", "fea", "feb")):
            return str(addr).strip()
    return None


def parse_device(d: dict) -> dict:
    """
    Parse a UDM stat/device entry into a structured dict.

    Field sources:
      wan1 / wan2           → ip, up, latency, speed, rx/tx, availability, type, ipv6, dns
      last_wan_interfaces   → alive (bool)
      last_wan_status       → "online" / "offline"
      active_geo_info       → public IP address, ISP, city, country
      uplink                → nameservers_dynamic (DNS fallback for WAN1), uptime
    """
    wan1_raw = d.get("wan1", {})
    wan2_raw = d.get("wan2", {})
    lwi      = d.get("last_wan_interfaces", {})
    lws      = d.get("last_wan_status", {})
    uplink   = d.get("uplink", {})
    geo      = d.get("active_geo_info", {})

    def _parse_wan(raw, lwi_key, lws_key, geo_key, uplink_data):
        dns_list = list(raw.get("dns") or [])
        if not dns_list and uplink_data:
            dns_list = list(uplink_data.get("nameservers_dynamic") or [])

        lwi_entry = lwi.get(lwi_key, {})
        geo_entry = geo.get(geo_key, {})

        return {
            "ip":           raw.get("ip") or geo_entry.get("address"),
            "ip_public":    geo_entry.get("address"),
            "ip_local":     raw.get("ip"),
            "netmask":      raw.get("netmask"),
            "ipv6":         _global_ipv6(raw.get("ipv6")),
            "up":           raw.get("up"),
            "alive":        lwi_entry.get("alive"),
            "online":       lws.get(lws_key) == "online",
            "is_uplink":    raw.get("is_uplink", False),
            "latency":      raw.get("latency"),
            "availability": raw.get("availability"),
            "speed":        raw.get("speed"),
            "type":         raw.get("type"),
            "media":        raw.get("media"),
            "full_duplex":  raw.get("full_duplex"),
            "ifname":       raw.get("ifname") or raw.get("name"),
            "rx_bytes":     raw.get("rx_bytes"),
            "tx_bytes":     raw.get("tx_bytes"),
            "rx_bytes_r":   raw.get("rx_bytes-r"),
            "tx_bytes_r":   raw.get("tx_bytes-r"),
            "rx_errors":    raw.get("rx_errors"),
            "tx_errors":    raw.get("tx_errors"),
            "rx_dropped":   raw.get("rx_dropped"),
            "tx_dropped":   raw.get("tx_dropped"),
            "dns":          ", ".join(str(x) for x in dns_list) or None,
            "isp":          geo_entry.get("isp_name"),
            "city":         geo_entry.get("city"),
            "country":      geo_entry.get("country_code"),
        }

    wan1_is_uplink = bool(wan1_raw.get("is_uplink"))
    return {
        "wan1": _parse_wan(
            wan1_raw, "WAN",  "WAN",  "WAN",
            uplink if wan1_is_uplink else None,
        ),
        "wan2": _parse_wan(
            wan2_raw, "WAN2", "WAN2", "WAN2",
            uplink if not wan1_is_uplink else None,
        ),
        "device": {
            "model":        d.get("model"),
            "name":         d.get("name"),
            "version":      d.get("version"),
            "ip":           d.get("ip"),
            "mac":          d.get("mac"),
            "uptime":       uplink.get("uptime") or d.get("uptime"),
            "cpu_pct":      d.get("system-stats", {}).get("cpu"),
            "mem_pct":      d.get("system-stats", {}).get("mem"),
            "temperature":  (d.get("temperatures") or [{}])[0].get("value"),
            "lan_clients":  d.get("user-num_sta") or d.get("num_sta"),
            "active_wan":   uplink.get("comment"),
        },
        "wan_ports": [],   # populated by routes.py from port_table
    }


def _event_msg(iface: str, field: str, value, ip: str | None) -> str:
    """Build an English event message for a single field change."""
    ip_str = f" ({ip})" if ip else ""
    if field == "alive":
        state = "unreachable (alive=false)" if not value else "reachable again (alive=true)"
        return f"{iface}{ip_str}: {state}"
    if field == "online":
        state = "offline" if not value else "back online"
        return f"{iface}{ip_str}: {state}"
    if field == "up":
        state = "link DOWN" if not value else "link UP"
        return f"{iface}{ip_str}: {state}"
    return f"{iface}: {field} changed to {value}"
