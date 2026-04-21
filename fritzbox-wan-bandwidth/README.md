# FRITZ!Box WAN Bandwidth

> Poll the current WAN upload/download rate from an AVM FRITZ!Box via TR-064
> and keep a local history so you can correlate your own traffic with ping or
> signal issues in DOCSight.

This module is intentionally narrow: it does **not** run throughput tests,
doesn't touch segment-utilization data, and has no alerting. It just reads
what the FRITZ!Box already reports and graphs it over time.

## Requirements

- FRITZ!Box with TR-064 enabled
  (FRITZ!Box UI → *Home Network* → *Network* → *Network Settings* →
  *Access for Applications* → enable)
- A FRITZ!Box user with enough permission to read box status.
  For most setups the account you already use for the web UI is sufficient.
- DOCSight **2026.2** or newer.

## Installation

```bash
cd /path/to/docsight/modules/
git clone https://github.com/itsDNNS/docsight-modules fritzbox-wan-bandwidth-src
cp -r fritzbox-wan-bandwidth-src/fritzbox-wan-bandwidth .
docker restart docsight
```

The module can also be installed via the in-app community modules catalog
once this repo entry is merged.

## Configuration

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `fbwb_enabled` | bool | `false` | Enable the collector. |
| `fbwb_host` | string | `fritz.box` | Hostname or IP of the FRITZ!Box. |
| `fbwb_port` | int | `49000` | TR-064 port (49000 HTTP, 49443 HTTPS). |
| `fbwb_use_tls` | bool | `false` | Use HTTPS for TR-064. |
| `fbwb_username` | string | — | FRITZ!Box user. |
| `fbwb_password` | string | — | FRITZ!Box password (stored encrypted). |
| `fbwb_interval` | int | `30` | Sample interval in seconds (min 10, max 3600). |
| `fbwb_history_days` | int | `7` | Days of samples to retain. |

`fbwb_password` is declared in the module manifest under `config_secrets`, so DOCSight stores it encrypted at rest and keeps it masked in the settings payload.

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/fbwb` | Standalone dashboard page. |
| GET | `/api/fbwb/status` | Latest sample + cached link properties. |
| GET | `/api/fbwb/history?hours=N` | Time-series samples for the last N hours (cap 24 in V1). |
| POST | `/api/fbwb/test` | Live TR-064 connectivity check. |

All endpoints require an authenticated DOCSight session.

## Storage

Samples live in the same SQLite database DOCSight already uses, in a table
called `fbwb_samples`. Old samples are pruned once per hour based on the
configured retention window.

## License

MIT
