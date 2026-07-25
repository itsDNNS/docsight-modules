# Module Name

> Short description of what this module does.

## Installation

```bash
cd /path/to/docsight/modules/
git clone https://github.com/YOUR_USER/YOUR_MODULE module-name
# Restart DOCSight container
docker restart docsight
```

## Configuration

List any configuration keys here. If the module stores passwords or API tokens,
declare those keys in `config_secrets` in `manifest.json` with string defaults,
normally `""`, and render the field as an empty password/token input in Settings
with `data-config-secret="true"`. Non-string secret defaults are invalid because
encrypted values must not enter boolean or integer coercion. When the masked
config value indicates an existing secret, also render
`data-saved-secret="true"`. Saved secret values must not be written back into
HTML `value` attributes.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/example/hello` | Returns a greeting |

## License

MIT
