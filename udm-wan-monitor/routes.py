"""
UDM WAN Monitor — Flask Routes  v3.1.1

  GET  /udm-wan                 → Standalone dashboard page
  GET  /api/udm-wan/status      → Latest cached data (JSON)
  GET  /api/udm-wan/detail      → Full live detail from stat/device (JSON)
  POST /api/udm-wan/test        → Live connection test (JSON)
"""

import logging
from datetime import datetime, timezone

import requests as req
from flask import Blueprint, jsonify, render_template

from app.web import require_auth

logger = logging.getLogger("docsight.udm_wan_monitor")

bp = Blueprint(
    "udm_wan_monitor_bp",
    __name__,
    template_folder="templates",
)

# ── Lazy helpers ──────────────────────────────────────────────────────────────

def _cfg():
    from app.web import get_config_manager  # noqa: PLC0415
    return get_config_manager()

def _collector():
    try:
        from app.web import get_collectors  # noqa: PLC0415
        for c in (get_collectors() or []):
            if getattr(c, "name", None) == "udm_wan_monitor":
                return c
    except Exception:  # noqa: BLE001
        pass
    return None

def _build_cfg():
    c = _cfg()
    from .collector import _build_cfg_from  # noqa: PLC0415
    d = _build_cfg_from(c)
    d["enabled"] = bool(c.get("udm_wan_enabled", False))
    return d

def _open_session(cfg):
    from .collector import _login  # noqa: PLC0415
    return _login(cfg)

# ── Pages ──────────────────────────────────────────────────────────────────────

@bp.route("/udm-wan")
@require_auth
def dashboard():
    from app.i18n import get_translations  # noqa: PLC0415
    lang = (_cfg().get("language") or "en") if _cfg() else "en"
    t = get_translations(lang)
    return render_template("udm_wan_standalone.html", t=t)

# ── API: cached status ──────────────────────────────────────────────────────────

@bp.route("/api/udm-wan/status")
@require_auth
def api_status():
    c = _collector()
    if c is None or not c.is_enabled():
        return jsonify({"enabled": False})
    last = getattr(c, "_last_result", None)
    if last is None:
        return jsonify({"enabled": True, "error": "No data yet"})
    return jsonify({"enabled": True, **last})

# ── API: full live detail ───────────────────────────────────────────────────────

@bp.route("/api/udm-wan/detail")
@require_auth
def api_detail():
    cfg = _build_cfg()
    if not cfg["host"]:
        return jsonify({"ok": False, "error": "Host not configured"}), 400
    if not cfg["enabled"]:
        return jsonify({"ok": False, "error": "Module not enabled"}), 403

    try:
        session  = _open_session(cfg)
        from .collector import _fetch_udm_device, parse_device  # noqa: PLC0415
        device   = _fetch_udm_device(session, cfg)
        parsed   = parse_device(device)
    except req.exceptions.ConnectionError:
        return jsonify({"ok": False, "error": "Connection failed"}), 502
    except req.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Timeout"}), 504
    except Exception:  # noqa: BLE001
        logger.exception("UDM detail fetch failed")
        return jsonify({"ok": False, "error": "Internal error"}), 500

    # ── Optional extra ports from config ────────────────────────────────────────
    c = _cfg()
    extra_ports_cfg = []
    for i in (1, 2):
        ifname = (c.get(f"udm_wan_extra_port{i}_ifname") or "").strip()
        alias  = (c.get(f"udm_wan_extra_port{i}_alias")  or "").strip()
        if ifname:
            extra_ports_cfg.append({"ifname": ifname.lower(), "alias": alias or ifname})

    fixed  = {"eth9": "WAN 1", "eth8": "WAN 2"}
    extra  = {ep["ifname"]: ep["alias"] for ep in extra_ports_cfg}
    wanted = {**fixed, **extra}
    order  = {"eth9": 0, "eth8": 1}

    wan_ports = []
    for p in device.get("port_table", []):
        ifname_raw = (p.get("ifname") or "")
        ifname_lc  = ifname_raw.lower()
        if ifname_lc not in wanted:
            continue
        wan_ports.append({
            "label":       wanted[ifname_lc],
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
    wan_ports.sort(key=lambda p: order.get((p["ifname"] or "").lower(), 99))
    parsed["wan_ports"] = wan_ports

    return jsonify({
        "ok":        True,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **parsed,
    })

# ── API: connection test ────────────────────────────────────────────────────────

@bp.route("/api/udm-wan/test", methods=["POST"])
@require_auth
def api_test():
    cfg = _build_cfg()
    if not cfg["host"]:
        return jsonify({"ok": False, "error": "Host not configured"}), 400
    try:
        session = _open_session(cfg)
        from .collector import _fetch_udm_device, parse_device  # noqa: PLC0415
        device  = _fetch_udm_device(session, cfg)
        parsed  = parse_device(device)
        return jsonify({
            "ok":        True,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            **parsed,
        })
    except req.exceptions.ConnectionError:
        return jsonify({"ok": False, "error": "Connection failed"}), 502
    except req.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Timeout"}), 504
    except Exception:  # noqa: BLE001
        logger.exception("UDM WAN test failed")
        return jsonify({"ok": False, "error": "Internal error"}), 500
