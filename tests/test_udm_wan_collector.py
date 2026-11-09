import dataclasses
import importlib.util
import sys
import unittest
from pathlib import Path

from test_udm_wan_loader import isolated_modules, module_stubs


COLLECTOR = Path(__file__).resolve().parents[1] / "udm-wan-monitor" / "collector.py"


@dataclasses.dataclass
class CollectorResult:
    source: str
    data: object = None
    success: bool = True
    error: str | None = None


def load_collector():
    stubs = module_stubs(config=None)
    stubs["app.collectors.base"].CollectorResult = CollectorResult
    with isolated_modules(stubs, list(stubs)):
        spec = importlib.util.spec_from_file_location("udm_wan_collector_under_test", COLLECTOR)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def gateway(wan1="eth8", wan2="eth9", type_="udm"):
    device = {"type": type_, "port_table": []}
    for key, ifname in (("wan1", wan1), ("wan2", wan2)):
        if ifname:
            device[key] = {"ifname": ifname}
            device["port_table"].append({"ifname": ifname, "name": ifname.upper(), "up": True})
    return device


class UdmWanCollectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = load_collector()

    def test_gateway_is_picked_over_devices_without_wan(self):
        switch = {"type": "usw"}
        ucg = gateway(type_="ucg")
        self.assertIs(self.c.select_gateway([switch, ucg]), ucg)
        self.assertIsNone(self.c.select_gateway([switch]))

    def test_wan_ports_follow_the_gateway_assignment(self):
        device = gateway(wan1="eth4", wan2="eth0")
        device["port_table"].append({"ifname": "eth1", "name": "LAN"})
        parsed = {"wan1": {"ifname": "eth4"}, "wan2": {"ifname": "eth0"}}
        rows = self.c.build_wan_ports(device, parsed, [{"ifname": "eth1", "alias": "Uplink"}])
        self.assertEqual([(r["label"], r["ifname"]) for r in rows],
                         [("WAN 1", "eth4"), ("WAN 2", "eth0"), ("Uplink", "eth1")])

    def test_extra_ports_read_legacy_fields_until_the_list_is_saved(self):
        legacy = {"udm_wan_extra_port1_ifname": "ETH7", "udm_wan_extra_port1_alias": "SFP"}
        self.assertEqual(self.c.parse_extra_ports(legacy), [{"ifname": "eth7", "alias": "SFP"}])
        saved = dict(legacy, udm_wan_extra_ports="[]")
        self.assertEqual(self.c.parse_extra_ports(saved), [])

    def test_extra_ports_drop_invalid_and_duplicate_entries(self):
        raw = '[{"ifname":"eth7"},{"ifname":"ETH7"},{"ifname":"bad name"},"x",{"ifname":"eth6","alias":"%s"}]' % ("a" * 50)
        ports = self.c.parse_extra_ports({"udm_wan_extra_ports": raw})
        self.assertEqual([p["ifname"] for p in ports], ["eth7", "eth6"])
        self.assertEqual(len(ports[1]["alias"]), 40)
        self.assertEqual(self.c.parse_extra_ports({"udm_wan_extra_ports": "not json"}), [])

    def test_link_local_ipv6_is_skipped(self):
        self.assertEqual(self.c._global_ipv6(["fe80::1", "FEBF::2", "2001:db8::1"]), "2001:db8::1")
        self.assertIsNone(self.c._global_ipv6(["fe80::1"]))
        self.assertIsNone(self.c._global_ipv6(None))

    def test_results_work_with_the_plain_dataclass(self):
        self.assertTrue(self.c._result_ok("x", {"a": 1}).success)
        failure = self.c._result_failure("x", "boom")
        self.assertFalse(failure.success)
        self.assertEqual(failure.error, "boom")

    def link_down_severity(self, primary, down):
        for state in self.c._state.values():
            state.update(up=None, alive=None, online=None, is_uplink=None)
        collector = object.__new__(self.c.UdmWanCollector)
        collector._cfg = {"udm_wan_primary": primary}
        up = {"up": True, "alive": True, "online": True}
        collector._detect_changes({"wan1": dict(up), "wan2": dict(up)})
        parsed = {"wan1": dict(up), "wan2": dict(up)}
        parsed[down]["up"] = False
        events = collector._detect_changes(parsed)
        return [e["severity"] for e in events if e["details"]["direction"] == "link_down"]

    def test_outage_of_the_other_wan_is_a_warning_when_a_cable_wan_is_set(self):
        self.assertEqual(self.link_down_severity("wan1", "wan2"), ["warning"])
        self.assertEqual(self.link_down_severity("wan1", "wan1"), ["critical"])
        self.assertEqual(self.link_down_severity("", "wan2"), ["critical"])

    def test_primary_wan_accepts_only_wan1_or_wan2(self):
        self.assertEqual(self.c.primary_wan({"udm_wan_primary": " WAN2 "}), "wan2")
        self.assertIsNone(self.c.primary_wan({"udm_wan_primary": "eth4"}))
        self.assertIsNone(self.c.primary_wan({}))

    def test_gateway_http_errors_get_a_readable_message(self):
        def error(code):
            exc = Exception()
            exc.response = type("Response", (), {"status_code": code})()
            return exc

        self.assertEqual(self.c.http_error_message(error(429)),
                         "Gateway returned HTTP 429 (login rate limit, try again in a few minutes)")
        self.assertEqual(self.c.http_error_message(error(500)), "Gateway returned HTTP 500")
        self.assertIsNone(self.c.http_error_message(ValueError("boom")))


if __name__ == "__main__":
    unittest.main()
