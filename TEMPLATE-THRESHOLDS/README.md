# community.thresholds_CHANGEME

Signal threshold profile for **CHANGEME** cable networks.

## How to Use

1. Copy this folder and rename it (e.g., `community.thresholds_comcast`)
2. Edit `manifest.json`: update `id`, `name`, `description`, `author`
3. Edit `thresholds.json`: enter your ISP's signal threshold values
4. Mount into DOCSight: `-v ./your-module:/modules/community.thresholds_comcast`
5. Restart DOCSight and enable the profile in Settings > Modules

## Where to Find Threshold Values

- Your ISP's support pages or field technician documentation
- Community forums for your ISP/region
- DOCSIS specification (CableLabs for US, Excentis for Europe)
- Compare with your modem's current signal levels and ISP feedback

## Schema Reference

See the [DOCSight Modules README](../README.md#threshold-profiles) for the full threshold JSON schema.
