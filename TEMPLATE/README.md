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
declare those keys in `config_secrets` in `manifest.json` and render the field as
an empty password/token input in Settings. Saved secret values must not be written
back into HTML `value` attributes.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/example/hello` | Returns a greeting |

## License

MIT
