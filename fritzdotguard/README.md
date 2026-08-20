# FritzBox DoT Guard

A [DOCSight](https://github.com/itsDNNS/docsight) **community module** that detects DNS-over-TLS (DoT) outages on a FRITZ!Box and auto-heals them via a TR-064 WAN reconnect. Outages, recoveries and watchdog alarms are delivered via Telegram and/or email and are written to the DOCSight event log.

## Features

- Polls the FRITZ!Box for active DoT (DNS-over-TLS, port 853) servers.
- Detects DoT outages and triggers `ForceTermination` (TR-064) to force a WAN reconnect.
- Telegram and email (SMTP/STARTTLS) notifications for outages, recoveries, and a watchdog hang alarm.
- Watchdog thread that alerts when the DOCSight process stops polling.
- SQLite time-series storage of DoT status snapshots.
- Canvas block chart ("DoT Status Verlauf") with event markers and selectable time ranges (1h … 90d).
- Dashboard card with sparkline.
- All relevant events (outage, reconnect, recovery, watchdog, notification metadata) are written to the central DOCSight event log (`/#events`).

## Requirements

- DOCSight `>= 2026.8`
- A FRITZ!Box reachable over HTTP with TR-064 (`ForceTermination`) enabled and a user with the necessary permissions.

## Configuration

The module registers the following config keys (all prefixed with `fritzdotguard_`):

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | bool | `false` | Enable the module |
| `poll_interval_seconds` | int | `10` | Check interval (seconds) |
| `cooldown_seconds` | int | `20` | Reconnect cooldown (seconds) |
| `watchdog_multiplier` | int | `3` | Watchdog grace = multiplier × interval |
| `telegram_bot_token` | str | `""` | Telegram bot token (secret) |
| `telegram_chat_id` | str | `""` | Telegram chat ID |
| `email_enabled` | bool | `false` | Enable email notifications |
| `email_addresses` | str | `""` | Recipients, separated by `+` or `,` |
| `smtp_host` | str | `smtp.gmail.com` | SMTP server |
| `smtp_port` | int | `587` | SMTP port |
| `smtp_user` | str | `""` | SMTP username |
| `smtp_password` | str | `""` | SMTP password/app password (secret) |
| `smtp_from` | str | `""` | From address |
| `smtp_use_tls` | bool | `true` | Use STARTTLS |

Secrets (`telegram_bot_token`, `smtp_password`) are declared via `config_secrets` and are never returned to the frontend.

## File Structure

```
fritzdotguard/
├── __init__.py
├── manifest.json
├── collector.py            # Collector: TR-064, DoT detection, notifications
├── routes.py               # Flask Blueprint (status, test, history)
├── storage.py              # SQLite time-series storage
├── i18n/
│   ├── de.json
│   └── en.json
├── templates/
│   ├── fritzdotguard_card.html
│   ├── fritzdotguard_detail.html
│   └── fritzdotguard_settings.html
└── static/
    └── js/
        ├── fritzdotguard-card.js
        └── fritzdotguard-detail.js
```

## License

MIT — see [LICENSE](LICENSE).
