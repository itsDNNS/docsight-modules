#!/usr/bin/env python3
"""Validate the DOCSight community module registry and module folders."""

from __future__ import annotations

import json
import py_compile
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REGISTRY_REQUIRED_FIELDS = {
    "id",
    "name",
    "description",
    "author",
    "repo",
    "version",
    "min_app_version",
    "type",
    "download_url",
}
REGISTRY_OPTIONAL_FIELDS = {"verified"}
REGISTRY_ALLOWED_FIELDS = REGISTRY_REQUIRED_FIELDS | REGISTRY_OPTIONAL_FIELDS
ALLOWED_TYPES = {"integration", "analysis", "theme"}


def load_json(path: Path, errors: list[str]) -> object | None:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:  # pragma: no cover - exact JSON error text is interpreter-specific
        errors.append(f"{path}: invalid JSON: {exc}")
        return None


def flatten_keys(value: object, prefix: str = "") -> set[str]:
    """Return dotted leaf keys for a JSON object."""
    if isinstance(value, dict):
        keys: set[str] = set()
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            keys.update(flatten_keys(child, child_prefix))
        return keys
    return {prefix}


def module_dir_from_download_url(root: Path, download_url: str) -> Path | None:
    parsed = urlparse(download_url)
    if parsed.scheme != "https":
        return None
    if parsed.netloc == "api.github.com":
        marker = "/contents/"
        if marker not in parsed.path:
            return None
        rel = parsed.path.split(marker, 1)[1].strip("/")
        return root / rel
    if parsed.netloc == "raw.githubusercontent.com":
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 4:
            return None
        rel = Path(*parts[3:])
        if rel.name == "manifest.json":
            rel = rel.parent
        return root / rel
    return None


def validate_registry_entry(root: Path, entry: object, index: int, errors: list[str]) -> None:
    if not isinstance(entry, dict):
        errors.append(f"registry.json modules[{index}]: entry must be an object")
        return

    module_id = str(entry.get("id", f"modules[{index}]"))
    missing = sorted(REGISTRY_REQUIRED_FIELDS - set(entry))
    if missing:
        errors.append(f"registry.json {module_id}: missing required field(s): {', '.join(missing)}")
    extra = sorted(set(entry) - REGISTRY_ALLOWED_FIELDS)
    if extra:
        errors.append(f"registry.json {module_id}: unsupported field(s): {', '.join(extra)}")
    if entry.get("type") not in ALLOWED_TYPES:
        errors.append(f"registry.json {module_id}: invalid type {entry.get('type')!r}")

    download_url = entry.get("download_url")
    if not isinstance(download_url, str):
        errors.append(f"registry.json {module_id}: download_url must be a string")
        return

    module_dir = module_dir_from_download_url(root, download_url)
    if module_dir is None:
        errors.append(f"registry.json {module_id}: download_url must point to a supported GitHub module directory")
        return
    if not module_dir.is_dir():
        errors.append(f"registry.json {module_id}: download_url directory does not exist locally: {module_dir.relative_to(root)}")
        return

    manifest_path = module_dir / "manifest.json"
    if not manifest_path.is_file():
        errors.append(f"registry.json {module_id}: download_url directory has no manifest.json")
        return

    manifest = load_json(manifest_path, errors)
    if not isinstance(manifest, dict):
        return

    manifest_id = manifest.get("id")
    if manifest_id != entry.get("id"):
        errors.append(
            f"registry.json {module_id}: manifest ID {manifest_id!r} does not match registry ID {entry.get('id')!r}"
        )
    if manifest.get("version") != entry.get("version"):
        errors.append(
            f"registry.json {module_id}: manifest version {manifest.get('version')!r} does not match registry version {entry.get('version')!r}"
        )
    manifest_type = manifest.get("type")
    if manifest_type not in ALLOWED_TYPES:
        errors.append(
            f"registry.json {module_id}: manifest type {manifest_type!r} is not supported"
        )
    if manifest_type != entry.get("type"):
        errors.append(
            f"registry.json {module_id}: manifest type {manifest_type!r} does not match registry type {entry.get('type')!r}"
        )


def validate_i18n(module_dir: Path, errors: list[str]) -> None:
    i18n_dir = module_dir / "i18n"
    if not i18n_dir.is_dir():
        return

    files = sorted(i18n_dir.glob("*.json"))
    if not files:
        return

    key_sets: dict[str, set[str]] = {}
    for path in files:
        data = load_json(path, errors)
        if isinstance(data, dict):
            key_sets[path.name] = flatten_keys(data)

    if not key_sets:
        return

    base_name = "en.json" if "en.json" in key_sets else sorted(key_sets)[0]
    base_keys = key_sets[base_name]
    for name, keys in sorted(key_sets.items()):
        missing = sorted(base_keys - keys)
        extra = sorted(keys - base_keys)
        if missing or extra:
            details = []
            if missing:
                details.append(f"missing: {', '.join(missing)}")
            if extra:
                details.append(f"extra: {', '.join(extra)}")
            errors.append(f"{module_dir.name}: i18n key mismatch in {name} vs {base_name} ({'; '.join(details)})")


def validate_json_files(root: Path, errors: list[str]) -> None:
    for path in sorted(root.glob("**/*.json")):
        if ".git" in path.parts:
            continue
        load_json(path, errors)


def validate_python_files(root: Path, errors: list[str]) -> None:
    for path in sorted(root.glob("**/*.py")):
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(f"{path.relative_to(root)}: Python compile failed: {exc.msg}")


def validate_repository(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []

    registry = load_json(root / "registry.json", errors)
    if not isinstance(registry, dict):
        return errors

    modules = registry.get("modules")
    if not isinstance(modules, list):
        errors.append("registry.json: 'modules' must be an array")
        return errors

    seen_ids: set[str] = set()
    for index, entry in enumerate(modules):
        if isinstance(entry, dict):
            module_id = entry.get("id")
            if isinstance(module_id, str):
                if module_id in seen_ids:
                    errors.append(f"registry.json {module_id}: duplicate module ID")
                seen_ids.add(module_id)
        validate_registry_entry(root, entry, index, errors)

    for manifest_path in sorted(root.glob("*/manifest.json")):
        if ".git" in manifest_path.parts:
            continue
        validate_i18n(manifest_path.parent, errors)

    validate_json_files(root, errors)
    validate_python_files(root, errors)
    return errors


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    root = Path(argv[0]) if argv else Path.cwd()
    errors = validate_repository(root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Registry validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
