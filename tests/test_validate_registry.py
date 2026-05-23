import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_registry import validate_repository


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def make_valid_fixture(root: Path, *, registry_id: str = "community.sample", manifest_id: str = "community.sample") -> None:
    module_dir = root / "sample-module"
    module_dir.mkdir(parents=True)
    write_json(root / "registry.json", {
        "modules": [
            {
                "id": registry_id,
                "name": "Sample Module",
                "description": "A sample module",
                "author": "sample-author",
                "repo": "https://github.com/example/docsight-sample",
                "version": "1.0.0",
                "min_app_version": "2026.2",
                "type": "integration",
                "download_url": "https://api.github.com/repos/example/docsight-sample/contents/sample-module?ref=main",
                "verified": False,
            }
        ]
    })
    write_json(module_dir / "manifest.json", {
        "id": manifest_id,
        "name": "Sample Module",
        "description": "A sample module",
        "version": "1.0.0",
        "author": "sample-author",
        "minAppVersion": "2026.2",
        "type": "integration",
        "contributes": {"i18n": "i18n/"},
    })
    write_json(module_dir / "i18n" / "en.json", {"sample.title": "Sample"})
    write_json(module_dir / "i18n" / "de.json", {"sample.title": "Beispiel"})


class ValidateRegistryTests(unittest.TestCase):
    def test_valid_registry_accepts_installable_module_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_valid_fixture(root)

            errors = validate_repository(root)

            self.assertEqual(errors, [])

    def test_registry_id_must_match_manifest_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_valid_fixture(root, registry_id="community.sample", manifest_id="community.other")

            errors = validate_repository(root)

            self.assertTrue(any("manifest ID" in error and "community.sample" in error for error in errors))

    def test_i18n_files_must_have_matching_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_valid_fixture(root)
            write_json(root / "sample-module" / "i18n" / "de.json", {})

            errors = validate_repository(root)

            self.assertTrue(any("i18n key mismatch" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
