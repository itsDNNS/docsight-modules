# Driver template

Community modem driver support is restored on main and in images built from this fix. The tagged v2026-09-16.1 release does not include this restoration. Replace `NEXT_RELEASE` in `minAppVersion` with the released version containing this restoration before publishing your module.

1. Copy this folder to `/data/modules/community.example_driver` in DOCSight's persistent data volume, or bind-mount it there.
2. Set the manifest ID, name, author and description. The ID is the modem selection key: use a unique community prefix for new support, or the exact built-in key for an explicit override. For overrides, absent or empty hints inherit the built-in hints; nonempty hints replace them entirely. Disabling or removing the override restores the built-in implementation, name and hints after restart.
3. Implement the four methods in `driver.py`, importing `ModemDriver` from `app.drivers.base`. The inherited constructor receives URL, username and password. Relative imports of sibling helpers are supported.
4. Restart DOCSight, enable the module in Settings > Extensions if needed and restart again. Select your driver in the modem settings and save.

The example performs no network requests and returns empty channel lists. A successful connection test with this template only confirms that the driver loaded. Replace its methods before using it for monitoring, and set credential hints appropriate to the modem. See the core [Adding Modem Support guide](https://github.com/itsDNNS/docsight/wiki/Adding-Modem-Support) for channel formats.

An old `/modules` mount requires `MODULES_DIR=/modules`. Driver code runs as trusted Python with access to modem credentials. The collector/publisher contribution restrictions are not a sandbox. See the [driver contract](../README.md#driver-modem-support).
