"""FRITZ!Box WAN bandwidth — Flask routes.

Exposed endpoints:

  GET  /fbwb                          Standalone dashboard page
  GET  /api/fbwb/status               Latest cached sample + link properties
  GET  /api/fbwb/history?hours=N      Time-series of samples (default 6h)
  POST /api/fbwb/test                 Live TR-064 connection test
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import requests as _requests
from flask import Blueprint, jsonify, render_template, request

from app.web import require_auth

from .collector import _build_cfg, _soap_call, _coerce_int
from .storage import FbwbStorage

logger = logging.getLogger("docsight.fritzbox_wan_bandwidth")

bp = Blueprint(
    "fritzbox_wan_bandwidth_bp",
    __name__,
    template_folder="templates",
)


def _cfg_mgr():
    from app.web import get_config_manager  # noqa: PLC0415
    return get_config_manager()


def _storage() -> FbwbStorage:
    from app.web import get_storage  # noqa: PLC0415
    return FbwbStorage(get_storage().db_path)


def _collector():
    try:
        from app.web import get_collectors  # noqa: PLC0415
        for c in (get_collectors() or []):
            if getattr(c, "name", None) == "fritzbox_wan_bandwidth":
                return c
    except Exception:  # noqa: BLE001
        return None
    return None


@bp.route("/fbwb")
@require_auth
def dashboard():
    from app.i18n import get_translations  # noqa: PLC0415
    c = _cfg_mgr()
    lang = (c.get("language") or "en") if c else "en"
    t = get_translations(lang)
    return render_template("fbwb_standalone.html", t=t)


@bp.route("/api/fbwb/status")
@require_auth
def api_status():
    c = _collector()
    enabled = bool(_cfg_mgr().get("fbwb_enabled", False))
    if c is None:
        # Module is loaded but the collector was not registered yet — surface
        # whatever we have in storage so the UI is still useful after restart.
        latest = _storage().get_latest()
        return jsonify({"enabled": enabled, "sample": latest, "link": None})

    snap = c.snapshot()
    if snap.get("sample") is None:
        snap["sample"] = _storage().get_latest()
    return jsonify({"enabled": enabled, **snap})


@bp.route("/api/fbwb/history")
@require_auth
def api_history():
    try:
        hours = int(request.args.get("hours", "6"))
    except (TypeError, ValueError):
        hours = 6
    hours = max(1, min(hours, 24))  # V1 stays truthful at the default 30 s interval

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    interval = int(_cfg_mgr().get("fbwb_interval", 30) or 30)
    interval = max(10, min(interval, 3600))
    limit = max(1, int(hours * 3600 / interval) + 5)
    rows = _storage().get_range(
        start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        limit=limit,
    )
    return jsonify({"hours": hours, "count": len(rows), "samples": rows})


@bp.route("/api/fbwb/test", methods=["POST"])
@require_auth
def api_test():
    cfg_mgr = _cfg_mgr()
    cfg = _build_cfg(cfg_mgr)
    payload = request.get_json(silent=True) or {}
    if payload:
        host = (payload.get("fbwb_host") or cfg.get("host") or "").strip()
        if "://" in host:
            host = host.split("://", 1)[1]
        host = host.rstrip("/").split("/", 1)[0]
        try:
            port = int(payload.get("fbwb_port", cfg.get("port", 49000)) or 49000)
        except (TypeError, ValueError):
            port = int(cfg.get("port", 49000) or 49000)
        use_tls = str(payload.get("fbwb_use_tls", cfg.get("use_tls", False))).lower() in {"1", "true", "yes", "on"}
        scheme = "https" if use_tls else "http"
        cfg.update({
            "host": host,
            "port": port,
            "use_tls": use_tls,
            "base": f"{scheme}://{host}:{port}" if host else "",
            "username": payload.get("fbwb_username", cfg.get("username", "")) or "",
            "password": payload.get("fbwb_password", cfg.get("password", "")) or "",
        })
    if not cfg["host"]:
        return jsonify({"ok": False, "error": "Host not configured"}), 400

    try:
        addon = _soap_call(cfg, "GetAddonInfos", timeout=8)
        link = {}
        try:
            link = _soap_call(cfg, "GetCommonLinkProperties", timeout=6)
        except Exception:  # noqa: BLE001
            pass
    except PermissionError:
        return jsonify({"ok": False, "error": "Authentication failed"}), 401
    except _requests.exceptions.ConnectionError:
        return jsonify({"ok": False, "error": "Connection failed"}), 502
    except _requests.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Timeout"}), 504
    except Exception:  # noqa: BLE001
        logger.exception("fbwb: test failed")
        return jsonify({"ok": False, "error": "Internal error"}), 500

    return jsonify({
        "ok": True,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rx_bps":       _coerce_int(addon.get("NewByteReceiveRate")),
        "tx_bps":       _coerce_int(addon.get("NewByteSendRate")),
        "rx_total":     _coerce_int(addon.get("NewTotalBytesReceived")),
        "tx_total":     _coerce_int(addon.get("NewTotalBytesSent")),
        "max_down_bps": _coerce_int(link.get("NewLayer1DownstreamMaxBitRate")),
        "max_up_bps":   _coerce_int(link.get("NewLayer1UpstreamMaxBitRate")),
        "link_status":  link.get("NewPhysicalLinkStatus"),
        "access_type":  link.get("NewWANAccessType"),
    })
