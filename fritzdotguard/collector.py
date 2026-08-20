"""Collector for FritzBox DoT Guard – Built-in Module.
Detects DNS-over-TLS outages and auto-heals via WAN reconnect.
"""

import hashlib
import json
import logging
import smtplib
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from requests.auth import HTTPDigestAuth

from app.collectors.base import Collector, CollectorResult
from app.tz import utc_now

logger = logging.getLogger(__name__)

# Shared state for status page (module-level, collector updates it)
SHARED_STATE: dict = {
    "last_check_ts": None,
    "dot_ok": True,
    "details": "",
    "status": "ok",
    "reconnect_count": 0,
    "last_reconnect_ts": None,
    "last_error_ts": None,
    "watchdog_alerted": False,
}

TR064_PORT = 49000
_TR064_CONTROL_PATHS = {"WANIPConnection:1": "wanipconnection1"}


def _build_soap(service_type, action):
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"'
        ' s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        "<s:Body>"
        f'<u:{action} xmlns:u="urn:dslforum-org:service:{service_type}" />'
        "</s:Body>"
        "</s:Envelope>"
    )


class FritzDoTGuardCollector(Collector):
    name = "fritzdotguard"

    def __init__(self, config_mgr, storage, web, **kwargs):
        poll_interval = int(config_mgr.get("fritzdotguard_poll_interval_seconds", 10))
        super().__init__(poll_interval_seconds=poll_interval)
        self._cfg = config_mgr
        self._storage = storage
        self._web = web
        raw_url = config_mgr.get("modem_url", "http://192.168.178.1")
        self._fritz_ip = raw_url.replace("http://", "").replace("https://", "").rstrip("/")
        self._fritz_user = config_mgr.get("modem_user", "")
        self._fritz_password = config_mgr.get("modem_password", "")
        self._tg_token = config_mgr.get("fritzdotguard_telegram_bot_token", "")
        self._tg_chat_id = config_mgr.get("fritzdotguard_telegram_chat_id", "")
        self._email_enabled = bool(config_mgr.get("fritzdotguard_email_enabled", False))
        self._email_addresses = config_mgr.get("fritzdotguard_email_addresses", "")
        self._smtp_host = config_mgr.get("fritzdotguard_smtp_host", "smtp.gmail.com")
        self._smtp_port = int(config_mgr.get("fritzdotguard_smtp_port", "587"))
        self._smtp_user = config_mgr.get("fritzdotguard_smtp_user", "")
        self._smtp_password = config_mgr.get("fritzdotguard_smtp_password", "")
        self._smtp_from = config_mgr.get("fritzdotguard_smtp_from", "")
        self._last_reconnect = 0.0
        self._cooldown = int(config_mgr.get("fritzdotguard_cooldown_seconds", 20))
        self._watchdog_multiplier = int(config_mgr.get("fritzdotguard_watchdog_multiplier", 3))
        self._watchdog_alerted = False
        self._last_state = (True, "")
        # Notification queue: stores outgoing notifications during DoT outage;
        # flushed when DoT recovers so DNS is available again.
        self._notification_queue: list = []
        # Initialize historical data storage
        try:
            from app.modules.fritzdotguard.storage import FritzDoTGuardStorage
            self._dot_storage = FritzDoTGuardStorage(storage.db_path)
            logger.info("FritzDoTGuard storage initialized")
        except Exception as exc:
            logger.warning("FritzDoTGuard storage init failed: %s", exc)
            self._dot_storage = None
        self._poll_count = 0
        # Start watchdog thread (daemon: dies with main process)
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()
        logger.info("FritzDoTGuard watchdog started (multiplier=%d, check every %ds)",
                    self._watchdog_multiplier, poll_interval * self._watchdog_multiplier)

    def is_enabled(self):
        return bool(self._cfg.get("fritzdotguard_enabled", False))

    def _force_termination(self):
        """Trigger WAN reconnect via TR-064 ForceTermination.
        Retries up to 3 times with backoff, since the FritzBox UPnP service
        may be temporarily unresponsive during a DNS outage."""
        svc, act = "WANIPConnection:1", "ForceTermination"
        ctl = _TR064_CONTROL_PATHS.get(svc, "wanipconnection1")
        url = f"http://{self._fritz_ip}:{TR064_PORT}/upnp/control/{ctl}"
        auth = HTTPDigestAuth(self._fritz_user, self._fritz_password)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SoapAction": f"urn:dslforum-org:service:{svc}#{act}",
        }
        last_exc = None
        for attempt in range(1, 4):
            try:
                resp = requests.post(url, data=_build_soap(svc, act).encode(),
                                    headers=headers, auth=auth, timeout=30)
                resp.raise_for_status()
                logger.info("ForceTermination OK (HTTP %d, attempt %d)", resp.status_code, attempt)
                return True
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning("ForceTermination attempt %d/3 failed: %s", attempt, exc)
                if attempt < 3:
                    time.sleep(2 * attempt)  # 2s, 4s backoff
        logger.error("ForceTermination failed after 3 attempts: %s", last_exc)
        return False

    def _get_sid(self):
        base = f"http://{self._fritz_ip}"
        try:
            r = requests.get(f"{base}/login_sid.lua", timeout=10)
            r.raise_for_status()
            ch = ET.fromstring(r.text).findtext("Challenge")
            if not ch:
                return None
            cr = hashlib.md5(f"{ch}-{self._fritz_password}".encode("utf-16-le")).hexdigest()
            r2 = requests.get(f"{base}/login_sid.lua",
                             params={"username": self._fritz_user, "response": f"{ch}-{cr}"},
                             timeout=10)
            r2.raise_for_status()
            sid = ET.fromstring(r2.text).findtext("SID")
            if not sid or sid == "0000000000000000":
                return None
            return sid
        except Exception as exc:
            logger.error("SID login error: %s", exc)
            return None

    def _check_dot(self):
        sid = self._get_sid()
        if not sid:
            self._last_state = (True, "")
            return False, "SID login failed"
        try:
            r = requests.get(f"http://{self._fritz_ip}/data.lua",
                           params={"sid": sid}, timeout=10)
            data = r.json()
        except Exception as exc:
            return False, f"data.lua error: {exc}"
        for conn in data.get("data", {}).get("internet", {}).get("connections", []):
            ipv4 = conn.get("ipv4", {})
            if not ipv4.get("connected"):
                continue
            dns_list = ipv4.get("dns", [])
            dot_entries = [d for d in dns_list if d.get("type") == "dot"]
            all_ips = [d.get("ip", "?") for d in dns_list]
            if dot_entries:
                return True, "DoT: " + ", ".join(d["ip"] for d in dot_entries)
            elif dns_list:
                return False, "DNS without DoT: " + ", ".join(all_ips)
        return False, "No DNS entries"

    def _telegram_send(self, text):
        if not self._tg_token or not self._tg_chat_id:
            return False
        url = (f"https://api.telegram.org/bot{self._tg_token}/sendMessage"
               f"?chat_id={self._tg_chat_id}&text={urllib.parse.quote(text)}"
               f"&parse_mode=HTML")
        try:
            requests.get(url, timeout=10)
            return True
        except Exception as exc:
            logger.error("Telegram error: %s", exc)
            return False

    @staticmethod
    def _parse_email_addresses(raw):
        """Parse email addresses from a + separated string."""
        if not raw or not raw.strip():
            return []
        parts = [p.strip() for p in raw.split("+")]
        return [p for p in parts if p and '@' in p]

    def _send_email(self, subject, body_html):
        """Send email notification to configured addresses."""
        if not self._email_enabled:
            return False
        recipients = self._parse_email_addresses(self._email_addresses)
        if not recipients:
            logger.warning("Email enabled but no valid addresses configured")
            return False
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._smtp_from
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        try:
            server = smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=15)
            server.starttls()
            server.login(self._smtp_user, self._smtp_password)
            server.sendmail(self._smtp_from, recipients, msg.as_string())
            server.quit()
            logger.info("Email sent to %s", ", ".join(recipients))
            return True
        except Exception as exc:
            logger.error("Email send failed: %s", exc)
            return False

    def _log_event(self, severity, event_type, message, details=None):
        """Write an event to the central DOCSight event log (/#events)."""
        try:
            self._storage.save_events([{
                "timestamp": utc_now(),
                "severity": severity,
                "event_type": event_type,
                "message": message,
                "details": details or {},
            }])
        except Exception as exc:
            logger.error("Failed to write event to central log: %s", exc)

    def _log_notification_event(self, kind, channels_sent, channels_failed, details=None):
        """Log metadata about a dispatched notification into the central event log."""
        if not channels_sent and not channels_failed:
            return  # no channels configured → nothing to report
        meta = dict(details or {})
        meta["channels_sent"] = channels_sent
        meta["channels_failed"] = channels_failed
        if channels_failed:
            severity = "warning"
            message = (f"{kind}: Versand fehlgeschlagen für {', '.join(channels_failed)}"
                       + (f" (OK: {', '.join(channels_sent)})" if channels_sent else ""))
        else:
            severity = "info"
            message = f"{kind} gesendet via {', '.join(channels_sent)}"
        self._log_event(severity, "fritzdotguard_notification", message, meta)

    def _watchdog_loop(self):
        """Watchdog daemon thread: alert if collect() hasn't updated
        last_check_ts within watchdog_multiplier * poll_interval_seconds.

        The watchdog checks once per (multiplier * interval) seconds.
        An alert fires when the last check is > (multiplier * 1.5 * interval)
        seconds old, giving one full watchdog cycle of grace before alerting.
        """
        check_interval = self._poll_interval_seconds * self._watchdog_multiplier
        while True:
            time.sleep(check_interval)
            try:
                last_ts = SHARED_STATE.get("last_check_ts")
                if last_ts is None:
                    continue  # hasn't started yet
                last_dt = datetime.fromisoformat(last_ts)
                age_s = (datetime.now(timezone.utc) - last_dt).total_seconds()
                threshold = self._poll_interval_seconds * self._watchdog_multiplier * 1.5

                if age_s > threshold:
                    if not self._watchdog_alerted:
                        self._watchdog_alerted = True
                        SHARED_STATE["watchdog_alerted"] = True
                        logger.critical(
                            "WATCHDOG: Collector hang detected! Last poll %s (%.0fs ago, threshold=%.0fs)",
                            last_ts, age_s, threshold
                        )
                        self._log_event(
                            "critical", "fritzdotguard_watchdog_hang",
                            f"Watchdog: Collector-Hang erkannt (letzter Poll vor {age_s:.0f}s)",
                            {"last_poll": last_ts, "age_seconds": round(age_s),
                             "threshold_seconds": round(threshold)},
                        )
                        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                        msg = (
                            f"<b>⚠️ FritzBox DoT Guard – WATCHDOG</b>\n\n"
                            f"DOCSight-Prozess hängt!\n"
                            f"Letzter Poll: {last_ts}\n"
                            f"Alter: {age_s:.0f}s (Schwelle: {threshold:.0f}s)\n\n"
                            f"<i>Modul kann keine DoT-Ausfälle erkennen, "
                            f"bis DOCSight wieder läuft.</i>"
                        )
                        self._telegram_send(msg)
                        if self._email_enabled:
                            self._send_email(
                                f"[WATCHDOG] DOCSight FritzBox DoT Guard – Hang erkannt – {ts}",
                                f"<html><body>"
                                f"<h2>⚠️ Collector Hang</h2>"
                                f"<p><strong>Zeit:</strong> {ts}</p>"
                                f"<p><strong>Letzter Poll:</strong> {last_ts}</p>"
                                f"<p><strong>Alter:</strong> {age_s:.0f}s</p>"
                                f"<p>DOCSight ist eingefroren – manueller Neustart nötig.</p>"
                                f"<hr><p style='color:#666;font-size:small'>"
                                f"Sent by DOCSight FritzBox DoT Guard Watchdog</p>"
                                f"</body></html>"
                            )
                else:
                    if self._watchdog_alerted:
                        self._watchdog_alerted = False
                        SHARED_STATE["watchdog_alerted"] = False
                        logger.info("WATCHDOG: Collector recovered (age=%.0fs)", age_s)
                        self._log_event(
                            "info", "fritzdotguard_watchdog_recovered",
                            "Watchdog: Collector wieder aktiv",
                            {"age_seconds": round(age_s)},
                        )
                        self._telegram_send("✅ FritzBox DoT Guard Watchdog – Collector recovered")
            except Exception:
                # Never let the watchdog itself crash
                logger.error("Watchdog loop error", exc_info=True)

    def _notify_outage(self, details):
        """Queue outage notification to be sent AFTER DoT restores.
        Messages are deferred because DNS is down during an outage,
        so Telegram/SMTP cannot be reached. They carry the original
        outage timestamp for accurate reporting."""
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        self._notification_queue.append({
            "timestamp": ts,
            "details": details,
            "outage_ts_iso": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("Outage notification QUEUED (will send after recovery): %s", details)

    def _flush_notification_queue(self):
        """Send all queued outage notifications and clear the queue.
        Called when DoT has recovered (= DNS is reachable again)."""
        if not self._notification_queue:
            return
        logger.info("Flushing %d queued notification(s)", len(self._notification_queue))
        for item in self._notification_queue:
            ts = item["timestamp"]
            details = item["details"]
            tg_text = (
                f"<b>\U0001f6a8 FritzBox DoT OUTAGE</b>\n\n"
                f"<i>Occurred:</i> {ts}\n"
                f"<i>Details:</i> {details}\n\n"
                f"WAN-Reconnect triggered – DoT has since recovered \u2705"
            )
            channels_sent = []
            channels_failed = []
            if self._tg_token and self._tg_chat_id:
                (channels_sent if self._telegram_send(tg_text) else channels_failed).append("telegram")
            if self._email_enabled:
                sent = self._send_email(
                    f"[FritzBox DoT Guard] DoT outage at {ts}",
                    f"""<html><body>
                    <h2>FritzBox DoT Guard – Outage (now recovered)</h2>
                    <p><strong>Outage time:</strong> {ts}</p>
                    <p><strong>Details:</strong> {details}</p>
                    <p>WAN reconnect was triggered. DoT has since recovered.</p>
                    <hr><p style="color:#666;font-size:small">Sent by DOCSight FritzBox DoT Guard</p>
                    </body></html>""",
                )
                (channels_sent if sent else channels_failed).append("email")
            self._log_notification_event("Ausfall-Benachrichtigung", channels_sent, channels_failed,
                                         {"outage_time": ts, "reason": details})
        self._notification_queue.clear()
        logger.info("Notification queue flushed")

    def _notify_recovery(self):
        """Flush queued outage notifications, then send recovery notice.
        Flushing first ensures outage alerts arrive before the recovery message."""
        self._flush_notification_queue()
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        channels_sent = []
        channels_failed = []
        if self._tg_token and self._tg_chat_id:
            ok = self._telegram_send("\u2705 FritzBox WAN-Reconnect successful – DoT should recover soon.")
            (channels_sent if ok else channels_failed).append("telegram")
        if self._email_enabled:
            ok = self._send_email(
                f"[FritzBox DoT Guard] DoT recovered – {ts}",
                f"""<html><body>
                <h2>FritzBox DoT Guard – Recovered</h2>
                <p><strong>Time:</strong> {ts}</p>
                <p>WAN reconnect was successful. DNS-over-TLS should be active again.</p>
                <hr><p style="color:#666;font-size:small">Sent by DOCSight FritzBox DoT Guard</p>
                </body></html>""",
            )
            (channels_sent if ok else channels_failed).append("email")
        self._log_notification_event("Recovery-Benachrichtigung", channels_sent, channels_failed,
                                     {"recovery_time": ts})

    def collect(self):
        now = time.monotonic()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        SHARED_STATE["last_check_ts"] = datetime.now(timezone.utc).isoformat()
        self._poll_count += 1

        if (now - self._last_reconnect) < self._cooldown:
            SHARED_STATE["status"] = "cooldown"
            if self._dot_storage:
                try:
                    self._dot_storage.save_status(ts, True, "cooldown", "cooldown")
                except Exception:
                    pass
            return CollectorResult(source=self.name, data={"status": "cooldown"})

        dot_ok, details = self._check_dot()
        state_changed = (dot_ok != self._last_state[0])
        self._last_state = (dot_ok, details)

        SHARED_STATE["dot_ok"] = dot_ok
        SHARED_STATE["details"] = details

        # Store periodic samples (every ~5 polls = ~50s) and on state change
        if self._dot_storage and (state_changed or self._poll_count <= 1 or self._poll_count % 5 == 0):
            try:
                event_type = "recovery" if (state_changed and dot_ok) else ("outage" if (state_changed and not dot_ok) else None)
                self._dot_storage.save_status(ts, dot_ok, details, event_type)
                logger.info("DoT status saved: poll=%d ok=%s type=%s", self._poll_count, dot_ok, event_type)
            except Exception as exc:
                logger.error("Failed to store DoT status: %s", exc)

        if dot_ok:
            SHARED_STATE["status"] = "ok"
            if state_changed:
                logger.info("DoT recovered: %s", details)
                self._log_event(
                    "info", "fritzdotguard_recovery",
                    f"DoT wiederhergestellt: {details}",
                    {"details": details},
                )
                self._flush_notification_queue()
            else:
                logger.info("DoT OK: %s", details)
            return CollectorResult(source=self.name, data={"status": "ok", "details": details})

        # Transient error (SID login, data.lua unreachable) → penalty backoff, NO reconnect
        if "SID login" in details or "data.lua error" in details:
            SHARED_STATE["status"] = "transient_error"
            SHARED_STATE["last_error_ts"] = datetime.now(timezone.utc).isoformat()
            logger.warning("Transient error: %s – penalty backoff", details)
            return CollectorResult(source=self.name, success=False, error=details,
                                   data={"status": "transient_error", "details": details})

        # Real DoT outage → WAN reconnect
        SHARED_STATE["status"] = "outage"
        logger.warning("DoT OUTAGE: %s - triggering reconnect", details)
        self._log_event(
            "critical", "fritzdotguard_outage",
            f"DoT-Ausfall erkannt: {details}",
            {"reason": details},
        )
        self._notify_outage(details)

        # Store outage in historical DB
        if self._dot_storage:
            try:
                self._dot_storage.save_status(ts, False, details, "outage")
            except Exception:
                pass

        success = self._force_termination()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if success:
            self._last_reconnect = time.monotonic()
            SHARED_STATE["reconnect_count"] += 1
            SHARED_STATE["last_reconnect_ts"] = datetime.now(timezone.utc).isoformat()
            SHARED_STATE["status"] = "reconnected"
            self._log_event(
                "warning", "fritzdotguard_reconnect",
                f"DoT-Ausfall – WAN-Reconnect ausgelöst. Grund: {details}",
                {"reason": details, "action": "reconnect"},
            )
            self._notify_recovery()
            # Store reconnect event in historical DB
            if self._dot_storage:
                try:
                    self._dot_storage.save_status(ts, False, details, "reconnect")
                except Exception:
                    pass
            return CollectorResult(source=self.name, data={
                "status": "reconnected", "details": details,
            })

        SHARED_STATE["status"] = "reconnect_failed"
        SHARED_STATE["last_error_ts"] = datetime.now(timezone.utc).isoformat()
        if self._dot_storage:
            try:
                self._dot_storage.save_status(ts, False, details, "reconnect_failed")
            except Exception:
                pass
        self._log_event(
            "critical", "fritzdotguard_reconnect_failed",
            f"DoT-Ausfall und WAN-Reconnect FEHLGESCHLAGEN! Grund: {details}",
            {"reason": details, "action": "reconnect_failed"},
        )
        return CollectorResult(source=self.name, success=False, error=details, data={
            "status": "reconnect_failed", "details": details,
        })
