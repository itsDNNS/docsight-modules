<p align="center">
  <img src="https://raw.githubusercontent.com/itsDNNS/docsight/main/docs/docsight-logo-v2.svg" alt="DOCSight" width="96">
</p>

<h1 align="center">DOCSight Community Modules</h1>

<p align="center">
  Discover and share modules for <a href="https://github.com/itsDNNS/docsight">DOCSight</a>.
</p>

---

## Available Modules

See [`registry.json`](registry.json) for the full catalog.

> No community modules yet — yours could be the first! See below for how to build one.

---

## Building a Module

### Quick Start

1. Copy the [`TEMPLATE/`](TEMPLATE/) directory
2. Rename the directory to your module name
3. Edit `manifest.json` with your module's details
4. Add your code
5. Test locally
6. [Submit to the registry](#submitting-a-module)

### Module Structure

A DOCSight module is a directory with a `manifest.json` at its root:

```
my-module/
├── manifest.json          # Required — module metadata
├── __init__.py            # Required — Python package marker
├── routes.py              # Optional — Flask Blueprint (API endpoints / pages)
├── collector.py           # Optional — data collector class
├── storage.py             # Optional — SQLite storage helper
├── i18n/                  # Optional — translation files
│   ├── en.json
│   ├── de.json
│   ├── es.json
│   └── fr.json
├── static/                # Optional — CSS/JS assets
│   ├── style.css          # Auto-loaded if present
│   └── main.js            # Auto-loaded if present
└── templates/             # Optional — Jinja2 templates
    └── my_settings.html   # Settings panel template
```

### Manifest Reference

Every module needs a `manifest.json`:

```json
{
  "id": "community.mymodule",
  "name": "My Module",
  "description": "What this module does in one sentence",
  "version": "1.0.0",
  "author": "your-github-username",
  "minAppVersion": "2026.2",
  "type": "integration",
  "contributes": {
    "routes": "routes.py",
    "i18n": "i18n/"
  }
}
```

#### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier. Must match `^[a-z][a-z0-9_.]+$`. Use `community.` or your username as prefix. |
| `name` | string | Human-readable name shown in the UI |
| `description` | string | One-line description |
| `version` | string | Semantic version (`major.minor.patch`) |
| `author` | string | Your GitHub username |
| `minAppVersion` | string | Minimum DOCSight version (currently `2026.2`) |
| `type` | string | One of: `driver`, `integration`, `analysis`, `theme` |
| `contributes` | object | What this module provides (see [Contribution Types](#contribution-types)) |

#### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `homepage` | string | URL to module documentation or repo |
| `license` | string | SPDX license identifier (e.g., `MIT`) |
| `config` | object | Default configuration values ([details](#config-defaults)) |
| `menu` | object | Sidebar navigation entry ([details](#menu-entry)) |

#### Menu Entry

Add a sidebar link for your module:

```json
"menu": {
  "label_key": "community.mymodule.nav_title",
  "icon": "puzzle",
  "order": 50
}
```

- `label_key` — i18n key for the label (namespaced with your module ID)
- `icon` — [Lucide icon](https://lucide.dev/icons/) name
- `order` — Sort position in sidebar (higher = lower; built-in modules use 10–30)

#### Config Defaults

Declare default values and they are automatically registered in DOCSight's config system:

```json
"config": {
  "mymodule_enabled": false,
  "mymodule_api_url": "",
  "mymodule_interval": 300
}
```

- Boolean values are auto-added to `BOOL_KEYS` (parsed from checkbox forms)
- Integer values are auto-added to `INT_KEYS` (parsed from text inputs)
- String values are stored as-is
- Keys must not conflict with existing core config keys

---

## Contribution Types

The `contributes` object declares what your module provides. All keys are optional — include only what you need.

### `routes` — API Endpoints & Pages

```json
"contributes": { "routes": "routes.py" }
```

Your `routes.py` must export a Flask Blueprint named `bp` or `blueprint`:

```python
from flask import Blueprint, jsonify

bp = Blueprint("mymodule_bp", __name__)

@bp.route("/api/mymodule/data")
def api_data():
    return jsonify({"status": "ok"})
```

The Blueprint is automatically registered with the Flask app. No URL prefix is added — you control the full path.

**Accessing core services in routes:**

```python
from app.web import get_storage, get_config_manager

@bp.route("/api/mymodule/data")
def api_data():
    storage = get_storage()       # SQLite storage instance
    config = get_config_manager() # Config manager instance
    return jsonify({...})
```

### `collector` — Scheduled Data Collection

```json
"contributes": { "collector": "collector.py:MyCollector" }
```

Format: `filename.py:ClassName`. Your collector must extend the base class:

```python
from app.collectors.base import Collector, CollectorResult

class MyCollector(Collector):
    name = "mymodule"

    def __init__(self, config_mgr, poll_interval=300, **kwargs):
        super().__init__(poll_interval)
        self._config = config_mgr

    def is_enabled(self):
        return self._config.get("mymodule_enabled", False)

    def collect(self):
        data = {"value": 42}
        return CollectorResult.ok(self.name, data)
```

The collector runs in a thread on each polling cycle. The base class provides exponential backoff on repeated failures (30s → 3600s max, auto-reset after 24h idle).

### `publisher` — Data Export (e.g., MQTT)

```json
"contributes": { "publisher": "publisher.py:MyPublisher" }
```

Format: `filename.py:ClassName`. Publisher classes receive collected data and export it to external services.

### `settings` — Configuration UI

```json
"contributes": { "settings": "templates/mymodule_settings.html" }
```

Your settings template is rendered in the Settings page under "Extensions":

```html
<div class="settings-group">
  <label class="settings-label" for="mymodule_api_url">
    {{ t['community.mymodule.api_url'] or 'API URL' }}
  </label>
  <input type="text" id="mymodule_api_url" name="mymodule_api_url"
         class="settings-input" value="{{ config.mymodule_api_url }}"
         placeholder="https://api.example.com">
</div>
```

> **Important:** Template filename must be unique — do **not** name it `settings.html` (conflicts with core). Use `mymodule_settings.html`.

**Checkbox pattern** (required for boolean config keys):

```html
<input type="hidden" name="mymodule_enabled" value="false">
<input type="checkbox" id="mymodule_enabled" name="mymodule_enabled"
       value="true" {% if config.mymodule_enabled %}checked{% endif %}>
```

Both the hidden input (fallback when unchecked) and `value="true"` are **required**. Without them, unchecked checkboxes silently store the wrong value.

### `i18n` — Translations

```json
"contributes": { "i18n": "i18n/" }
```

Place JSON files in the `i18n/` directory:

```
i18n/
├── en.json    # English (required)
├── de.json    # German (recommended)
├── es.json    # Spanish (recommended)
└── fr.json    # French (recommended)
```

Keys are automatically namespaced with your module ID:

```json
{
  "nav_title": "My Module",
  "api_url": "API URL"
}
```

Access in templates: `{{ t['community.mymodule.nav_title'] }}`

### `tab` — Dashboard Tab

```json
"contributes": { "tab": "templates/mymodule_tab.html" }
```

Adds a tab to the main dashboard view switcher.

### `card` — Dashboard Card

```json
"contributes": { "card": "templates/mymodule_card.html" }
```

Adds a card widget to the dashboard overview.

### `thresholds` — Signal Threshold Profile

```json
"contributes": { "thresholds": "thresholds.json" }
```

A threshold module provides regional signal quality thresholds for DOCSight's health assessment. Only one threshold profile can be active at a time — enabling a new one automatically disables the previous one.

Use the [`TEMPLATE-THRESHOLDS/`](TEMPLATE-THRESHOLDS/) directory as a starting point.

#### Required Sections

The `thresholds.json` file must contain these three sections, each with a `_default` key:

| Section | Keys | Format |
|---------|------|--------|
| `downstream_power` | Modulation names (e.g., `256QAM`, `4096QAM`) | `{ "good": [min, max], "warning": [min, max], "critical": [min, max] }` |
| `upstream_power` | Channel types: `sc_qam`, `ofdma` | Same `[min, max]` array format |
| `snr` | Modulation names | `{ "good_min": N, "warning_min": N, "critical_min": N }` |

#### Optional Sections

| Section | Purpose |
|---------|---------|
| `_meta` | Metadata (`region`, `operator`, `docsis_variant`, `source`, `notes`) |
| `upstream_modulation` | QAM order thresholds (`critical_max_qam`, `warning_max_qam`) |
| `errors` | Uncorrectable error rate (`uncorrectable_pct: { warning: %, critical: % }`) |

### `driver` — Modem/Router Hardware Driver

> Since DOCSight v2026-03-03

```json
"contributes": { "driver": "driver.py:MyModemDriver" }
```

Format: `filename.py:ClassName`. Your driver must extend `ModemDriver` from `app/drivers/base.py`:

```python
from app.drivers.base import ModemDriver

class MyModemDriver(ModemDriver):
    def login(self):
        """Authenticate with the modem. Called before each poll cycle."""
        pass

    def get_docsis_data(self):
        """Return DOCSIS channel data (see Adding-Modem-Support wiki)."""
        return {"channelDs": {"docsis30": [], "docsis31": []},
                "channelUs": {"docsis30": [], "docsis31": []}}

    def get_device_info(self):
        """Return device model and firmware info."""
        return {"manufacturer": "...", "model": "...", "sw_version": "..."}

    def get_connection_info(self):
        """Return internet connection info. Empty dict if unavailable."""
        return {}
```

The driver is registered in DOCSight's `DriverRegistry` on startup. Module drivers take priority over built-in drivers with the same key, allowing community modules to override or improve existing drivers.

**Security restriction:** Driver modules **cannot** also contribute `collector` or `publisher`. This prevents a driver module from exfiltrating modem credentials to external services. If a manifest declares both, DOCSight rejects the module on startup.

See the [Adding Modem Support](https://github.com/itsDNNS/docsight/wiki/Adding-Modem-Support) wiki page for the full `get_docsis_data()` return format and driver development tips.

### `static` — CSS & JavaScript

```json
"contributes": { "static": "static/" }
```

Files are served at `/modules/<module-id>/static/`. Two files are auto-detected and loaded on every page:

- `style.css` — stylesheet
- `main.js` — JavaScript

Other static files (images, fonts, etc.) are accessible at their path but not auto-loaded.

---

## Testing Locally

1. **Mount the modules directory** in your Docker setup:

   ```yaml
   # docker-compose.yml
   services:
     docsight:
       image: ghcr.io/itsdnns/docsight:latest
       volumes:
         - docsight_data:/data
         - ./modules:/modules    # <-- add this line
       ports:
         - "8765:8765"
   ```

2. **Place your module** in the `modules/` directory:

   ```bash
   mkdir -p modules
   cp -r TEMPLATE modules/my-module
   # Edit modules/my-module/manifest.json and code
   ```

3. **Restart DOCSight** to discover the new module:

   ```bash
   docker compose restart docsight
   ```

4. **Verify** in Settings > Modules — your module should appear with a "Community" badge.

5. **Check logs** for any loading errors:

   ```bash
   docker compose logs docsight | grep -i module
   ```

### Error Handling

DOCSight never crashes due to a broken module:

- Invalid manifests are skipped with a warning
- Load failures are caught per-module and stored as error state
- Broken modules show an error badge in Settings > Modules
- Core functionality is never affected

---

## Submitting a Module

### Prerequisites

- Your module works locally (tested with DOCSight)
- Your module has its own GitHub repository
- Your module has a README with installation instructions

### Steps

1. Fork this repository
2. Add your module to `registry.json`:

   ```json
   {
     "id": "community.mymodule",
     "name": "My Module",
     "description": "What it does in one sentence",
     "author": "your-github-username",
     "repo": "https://github.com/your-username/docsight-mymodule",
     "version": "1.0.0",
     "minAppVersion": "2026.2",
     "type": "integration",
     "verified": false
   }
   ```

3. Open a Pull Request
4. We review: valid manifest, basic functionality, no malicious code
5. After merge, your module appears in the catalog

### Verified Badge

Modules reviewed and tested by the DOCSight team receive `"verified": true`. Unverified modules are functional but marked accordingly in the catalog.

### Guidelines

- **One module per repository** — keep it focused
- **Semantic versioning** — update `version` in both your manifest and the registry entry
- **No `docsight.*` IDs** — this prefix is reserved for built-in modules
- **English README required** — additional languages welcome

---

## Module Type Reference

| Type | Purpose | Example |
|------|---------|---------|
| `driver` | Hardware/modem support | Custom modem driver |
| `integration` | External service connection | Ping test, uptime monitor, API bridge |
| `analysis` | Data analysis/visualization | Custom charts, reports |
| `theme` | UI customization | Color schemes, layouts |

---

## Reference Implementations

These built-in DOCSight modules serve as examples:

| Module | Type | Contributes | Complexity |
|--------|------|-------------|------------|
| [Reports](https://github.com/itsDNNS/docsight/tree/main/app/modules/reports) | analysis | routes, i18n | Minimal |
| [Journal](https://github.com/itsDNNS/docsight/tree/main/app/modules/journal) | analysis | routes, i18n | Medium |
| [Weather](https://github.com/itsDNNS/docsight/tree/main/app/modules/weather) | integration | collector, routes, settings, i18n | Full |
| [Backup](https://github.com/itsDNNS/docsight/tree/main/app/modules/backup) | integration | collector, routes, settings, i18n | Full |
| [MQTT](https://github.com/itsDNNS/docsight/tree/main/app/modules/mqtt) | integration | publisher, settings, i18n | Publisher |
| [VFKD Thresholds](https://github.com/itsDNNS/docsight/tree/main/app/modules/thresholds_vfkd) | driver | thresholds | Minimal |
| [GenericDriver](https://github.com/itsDNNS/docsight/blob/main/app/drivers/generic.py) | driver | driver | Minimal |

---

## License

MIT — same as [DOCSight](https://github.com/itsDNNS/docsight).
