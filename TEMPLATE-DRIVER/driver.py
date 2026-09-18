"""Minimal inert driver; replace these methods with your modem implementation."""

from app.drivers.base import ModemDriver


class ExampleDriver(ModemDriver):
    def login(self):
        pass

    def get_docsis_data(self):
        return {
            "channelDs": {"docsis30": [], "docsis31": []},
            "channelUs": {"docsis30": [], "docsis31": []},
        }

    def get_device_info(self):
        return {"model": "Example Modem", "sw_version": "unknown"}

    def get_connection_info(self):
        return {}
