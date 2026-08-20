"""API routes for FritzBox DoT Guard."""

import logging
import urllib.parse

import requests
from flask import Blueprint, jsonify, request

from app.web import get_config_manager, require_auth, get_storage
from app.tz import utc_now
from .collector import SHARED_STATE

logger = logging.getLogger(__name__)

bp = Blueprint("fritzdotguard_module", __name__)


def _log_event(severity, event_type, message, details=None):
    """Write an event to the central DOCSight event log (/#events)."""
    try:
        storage = get_storage()
        if storage is None or not hasattr(storage, "save_events"):
            return
        storage.save_events([{
            "timestamp": utc_now(),
            "severity": severity,
            "event_type": event_type,
            "message": message,
            "details": details or {},
        }])
    except Exception:
        logger.exception("Failed to write event to central log")


@bp.after_request
def _no_cache_api(response):
    """Prevent browser from caching API responses."""
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# --- Status ---

@bp.route("/api/fritzdotguard/status", methods=["GET"])
@require_auth
def api_get_status():
    """Return current DoT guard status for the dashboard card."""
    cfg = get_config_manager()
    return jsonify({
        "status": SHARED_STATE.get("status", "unknown"),
        "dot_ok": SHARED_STATE.get("dot_ok"),
        "details": SHARED_STATE.get("details", ""),
        "last_check_ts": SHARED_STATE.get("last_check_ts"),
        "reconnect_count": SHARED_STATE.get("reconnect_count", 0),
        "last_reconnect_ts": SHARED_STATE.get("last_reconnect_ts"),
        "last_error_ts": SHARED_STATE.get("last_error_ts"),
        "config": {
            "fritzbox_url": cfg.get("modem_url", ""),
            "poll_interval_s": cfg.get("fritzdotguard_poll_interval_seconds", 10),
            "cooldown_s": cfg.get("fritzdotguard_cooldown_seconds", 20),
            "telegram_configured": bool(cfg.get("fritzdotguard_telegram_bot_token", "")),
            "email_configured": bool(cfg.get("fritzdotguard_email_enabled", False) and cfg.get("fritzdotguard_email_addresses", "")),
        },
    })


# --- Telegram Test ---

@bp.route("/api/fritzdotguard/test-telegram", methods=["POST"])
@require_auth
def api_test_telegram():
    """Send a test message to the configured Telegram chat."""
    cfg = get_config_manager()
    token = cfg.get("fritzdotguard_telegram_bot_token", "").strip()
    chat_id = cfg.get("fritzdotguard_telegram_chat_id", "").strip()

    if not token or not chat_id:
        return jsonify({"success": False, "error": "Telegram token or chat ID not configured"}), 400

    text = "\u2705 <b>FRITZ!Box DoT Guard – Test Message</b>\n\nThe Telegram integration is working correctly."
    url = f"https://api.telegram.org/bot{token}/sendMessage?chat_id={chat_id}&text={urllib.parse.quote(text)}&parse_mode=HTML"

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        if body.get("ok"):
            logger.info("Telegram test message sent successfully to chat %s", chat_id)
            _log_event("info", "fritzdotguard_notification",
                       "Telegram-Testnachricht gesendet",
                       {"channel": "telegram", "test": True})
            return jsonify({"success": True, "message": "Test message sent!"})
        else:
            logger.error("Telegram API error: %s", body.get("description", "unknown"))
            _log_event("warning", "fritzdotguard_notification",
                       "Telegram-Testnachricht fehlgeschlagen",
                       {"channel": "telegram", "test": True,
                        "error": body.get("description", "Telegram API error")})
            return jsonify({"success": False, "error": body.get("description", "Telegram API error")}), 400
    except requests.RequestException as exc:
        logger.error("Telegram test failed: %s", exc)
        _log_event("warning", "fritzdotguard_notification",
                   "Telegram-Testnachricht fehlgeschlagen",
                   {"channel": "telegram", "test": True, "error": str(exc)})
        return jsonify({"success": False, "error": str(exc)}), 500


# --- Email Test ---

@bp.route("/api/fritzdotguard/test-email", methods=["POST"])
@require_auth
def api_test_email():
    """Send a test email via SMTP."""
    from .collector import FritzDoTGuardCollector
    cfg = get_config_manager()
    enabled = bool(cfg.get("fritzdotguard_email_enabled", False))
    addresses = cfg.get("fritzdotguard_email_addresses", "")

    if not enabled or not addresses:
        return jsonify({"success": False, "error": "Email not enabled or no addresses configured"}), 400

    parsed = FritzDoTGuardCollector._parse_email_addresses(addresses)
    if not parsed:
        return jsonify({"success": False, "error": "No valid email addresses found"}), 400

    smtp_host = cfg.get("fritzdotguard_smtp_host", "smtp.gmail.com")
    smtp_port = int(cfg.get("fritzdotguard_smtp_port", "587"))
    smtp_user = cfg.get("fritzdotguard_smtp_user", "")
    smtp_password = cfg.get("fritzdotguard_smtp_password", "")
    smtp_from = cfg.get("fritzdotguard_smtp_from", "")

    if not smtp_user or not smtp_password or not smtp_from:
        return jsonify({"success": False, "error": "SMTP credentials not fully configured (host/user/password/from)"}), 400

    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    ts = __import__("time").strftime("%Y-%m-%d %H:%M:%S", __import__("time").localtime())
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[FritzBox DoT Guard] Test Email – {ts}"
    msg["From"] = smtp_from
    msg["To"] = ", ".join(parsed)
    msg.attach(MIMEText(
        f"""<html><body>
        <h2>FritzBox DoT Guard – Test Email</h2>
        <p><strong>Time:</strong> {ts}</p>
        <p>The email notification integration is working correctly.</p>
        <hr><p style="color:#666;font-size:small">Sent by DOCSight FritzBox DoT Guard</p>
        </body></html>""", "html", "utf-8"))

    try:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_from, parsed, msg.as_string())
        server.quit()
        logger.info("Test email sent to %s", ", ".join(parsed))
        _log_event("info", "fritzdotguard_notification",
                   "Email-Testnachricht gesendet",
                   {"channel": "email", "test": True, "recipients": len(parsed)})
        return jsonify({"success": True, "message": f"Test email sent to {len(parsed)} recipient(s)!"})
    except Exception as exc:
        logger.error("Test email failed: %s", exc)
        _log_event("warning", "fritzdotguard_notification",
                   "Email-Testnachricht fehlgeschlagen",
                   {"channel": "email", "test": True, "error": str(exc)})
        return jsonify({"success": False, "error": str(exc)}), 500


# --- History (for charts) ---

@bp.route("/api/fritzdotguard/history", methods=["GET"])
@require_auth
def api_get_history():
    """Return DoT status history for chart rendering."""
    try:
        from .storage import FritzDoTGuardStorage
    except ImportError as exc:
        logger.error("History endpoint: storage import failed: %s", exc)
        return jsonify({"error": "Storage module not available"}), 500

    try:
        core_storage = get_storage()
        if core_storage is None:
            logger.error("History endpoint: get_storage() returned None")
            return jsonify({"error": "Core storage not initialized"}), 503
        storage = FritzDoTGuardStorage(core_storage.db_path)
    except Exception as exc:
        logger.error("History endpoint: storage init failed: %s", exc)
        return jsonify({"error": f"Storage init failed: {exc}"}), 500

    hours = request.args.get("hours", 24, type=int)
    from datetime import datetime, timedelta, timezone
    start_ts = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    try:
        rows = storage.get_status_range(start_ts, datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        logger.error("History endpoint: get_status_range failed: %s", exc)
        return jsonify({"error": f"Query failed: {exc}"}), 500

    timestamps = []
    dot_ok = []
    event_types = []
    details = []

    for r in rows:
        timestamps.append(r["timestamp"])
        dot_ok.append(r["dot_ok"])
        event_types.append(r.get("event_type") or "check")
        details.append(r.get("details") or "")

    return jsonify({
        "timestamps": timestamps,
        "dot_ok": dot_ok,
        "event_types": event_types,
        "details": details,
    })
