import importlib.util
import shutil
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path


_MISSING = object()


@contextmanager
def isolated_modules(stubs, names):
    saved = {name: sys.modules.get(name, _MISSING) for name in names}
    try:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(stubs)
        yield
    finally:
        for name in names:
            sys.modules.pop(name, None)
        for name, module in saved.items():
            if module is not _MISSING:
                sys.modules[name] = module


def module_stubs(config):
    app = types.ModuleType("app")
    app.__path__ = []

    app_web = types.ModuleType("app.web")
    app_web.require_auth = lambda function: function
    app_web.get_config_manager = lambda: config

    app_collectors = types.ModuleType("app.collectors")
    app_collectors.__path__ = []

    app_collectors_base = types.ModuleType("app.collectors.base")
    app_collectors_base.Collector = type("Collector", (), {})
    app_collectors_base.CollectorResult = type("CollectorResult", (), {})

    app_tz = types.ModuleType("app.tz")
    app_tz.utc_now = lambda: None

    flask = types.ModuleType("flask")

    class Blueprint:
        def __init__(self, *args, **kwargs):
            pass

        def route(self, *args, **kwargs):
            return lambda function: function

    flask.Blueprint = Blueprint
    flask.jsonify = lambda value: value
    flask.render_template = lambda *args, **kwargs: None

    requests = types.ModuleType("requests")
    requests.Session = type("Session", (), {})
    requests.exceptions = types.SimpleNamespace(
        ConnectionError=type("ConnectionError", (Exception,), {}),
        Timeout=type("Timeout", (Exception,), {}),
    )

    return {
        "app": app,
        "app.web": app_web,
        "app.collectors": app_collectors,
        "app.collectors.base": app_collectors_base,
        "app.tz": app_tz,
        "flask": flask,
        "requests": requests,
    }


class UdmWanSyntheticLoaderTests(unittest.TestCase):
    def test_routes_reuse_host_loaded_collector(self):
        for directory in ("community.udm_wan_monitor", "custom_udm_wan_monitor"):
            with self.subTest(directory=directory):
                self._assert_routes_reuse_host_loaded_collector(directory)

    def test_failed_fallback_removes_inserted_collector(self):
        root = Path(__file__).resolve().parents[1]
        directory = "custom_udm_wan_monitor"
        routes_name = f"community_modules.{directory}.routes"
        collector_name = f"app.modules.{directory}.collector"
        stubs = module_stubs({})

        with tempfile.TemporaryDirectory() as tmp:
            installed = Path(tmp) / directory
            installed.mkdir()
            routes_path = shutil.copy2(
                root / "udm-wan-monitor" / "routes.py",
                installed / "routes.py",
            )
            (installed / "collector.py").write_text(
                'raise RuntimeError("collector failed")\n',
                encoding="utf-8",
            )

            with isolated_modules(stubs, self._temporary_names(directory, stubs)):
                routes = self._load_leaf(routes_name, routes_path)

                with self.assertRaisesRegex(RuntimeError, "collector failed"):
                    routes._collector_mod()

                self.assertNotIn(collector_name, sys.modules)

    def _assert_routes_reuse_host_loaded_collector(self, directory):
        root = Path(__file__).resolve().parents[1]
        routes_name = f"community_modules.{directory}.routes"
        collector_name = f"app.modules.{directory}.collector"
        config = {
            "udm_wan_enabled": True,
            "udm_wan_host": "192.0.2.1",
            "udm_wan_port": 8443,
            "udm_wan_site": "default",
        }
        stubs = module_stubs(config)

        with tempfile.TemporaryDirectory() as tmp:
            installed = Path(tmp) / directory
            installed.mkdir()
            routes_path = shutil.copy2(
                root / "udm-wan-monitor" / "routes.py",
                installed / "routes.py",
            )
            collector_path = shutil.copy2(
                root / "udm-wan-monitor" / "collector.py",
                installed / "collector.py",
            )

            with isolated_modules(stubs, self._temporary_names(directory, stubs)):
                routes = self._load_leaf(routes_name, routes_path)
                collector = self._load_leaf(collector_name, collector_path)

                built_config = routes._build_cfg()

                self.assertEqual(
                    built_config,
                    {
                        "host": "192.0.2.1",
                        "base": "https://192.0.2.1:8443",
                        "username": "",
                        "password": "",
                        "site": "default",
                        "verify_ssl": False,
                        "enabled": True,
                    },
                )
                self.assertIs(routes._collector_mod(), collector)

    def _temporary_names(self, directory, stubs):
        return set(stubs) | {
            "app.modules",
            f"app.modules.{directory}",
            f"app.modules.{directory}.collector",
            "app.modules.community.udm_wan_monitor.collector",
            "community_modules",
            f"community_modules.{directory}",
            f"community_modules.{directory}.routes",
        }

    def _load_leaf(self, name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module


if __name__ == "__main__":
    unittest.main()
