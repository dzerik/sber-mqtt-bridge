# Sber Smart Home MQTT Bridge

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/dzerik/sber-mqtt-bridge)](https://github.com/dzerik/sber-mqtt-bridge/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.txt)

Home Assistant custom integration for bridging HA entities to [Sber Smart Home](https://developers.sber.ru/docs/ru/smarthome) cloud via MQTT.

Control your Home Assistant devices through Sber voice assistants (Salut) and the Sber Smart Home app.

## Features

- Native HA integration (not an addon) — installs via HACS
- Config Flow UI for Sber MQTT credentials
- Entity selection — choose which HA entities to expose to Sber
- Real-time state sync — HA state changes instantly reflected in Sber
- Voice control through Sber assistants (Salut)
- 15 device types supported
- Automatic MQTT reconnection with exponential backoff
- Optional SSL certificate verification (for custom CA)
- Translations: English and Russian

## Supported Device Types

| HA Domain | Sber Category | Description |
|-----------|---------------|-------------|
| `light` | light | Brightness, color, color temperature |
| `switch` | relay | On/off control |
| `switch` (outlet) | socket | Smart socket |
| `script` | relay | Script execution |
| `button` | relay | Button press |
| `cover` | curtain | Curtains, position control |
| `cover` (blind/shade) | window_blind | Blinds, roller shutters |
| `climate` | hvac_ac | Air conditioner, HVAC |
| `climate` (radiator) | hvac_radiator | Radiator thermostat |
| `sensor` (temperature) | sensor_temp | Temperature sensor |
| `sensor` (humidity) | sensor_temp | Humidity sensor |
| `binary_sensor` (motion) | sensor_pir | Motion sensor |
| `binary_sensor` (door) | sensor_door | Door/window sensor |
| `binary_sensor` (moisture) | sensor_water_leak | Water leak sensor |
| `input_boolean` | scenario_button | Scenario button |
| `valve` | valve | Motorized water valve |
| `humidifier` | hvac_humidifier | Air humidifier |

## Prerequisites

1. [Register in Sber Studio](https://developers.sber.ru/studio/workspaces/)
2. Create an integration project and obtain MQTT credentials (login + password)
3. See [Sber MQTT-to-Cloud documentation](https://developers.sber.ru/docs/ru/smarthome/mqtt-diy/mqtt-to-diy)

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Click "Custom repositories" (three dots menu)
3. Add `https://github.com/dzerik/sber-mqtt-bridge` as "Integration"
4. Search for "Sber Smart Home MQTT Bridge" and install
5. Restart Home Assistant

### Manual

1. Copy `custom_components/sber_mqtt_bridge/` to your HA `config/custom_components/`
2. Restart Home Assistant

## Configuration

1. Go to **Settings** > **Devices & Services** > **Add Integration**
2. Search for "Sber Smart Home MQTT Bridge"
3. Enter your Sber MQTT credentials:
   - **MQTT Login** — from your Sber Studio integration project
   - **MQTT Password** — from your Sber Studio integration project
   - **MQTT Broker** — `mqtt-partners.iot.sberdevices.ru` (default)
   - **MQTT Port** — `8883` (default)
   - **Verify SSL** — enable (recommended); disable only if broker uses a custom CA
4. After adding, go to integration options to select which entities to expose to Sber

### Configuration Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| MQTT Login | Yes | — | Sber Studio integration login |
| MQTT Password | Yes | — | Sber Studio integration password |
| MQTT Broker | No | `mqtt-partners.iot.sberdevices.ru` | Sber MQTT broker address |
| MQTT Port | No | `8883` | Sber MQTT broker port |
| Verify SSL | No | `true` | Verify broker SSL certificate |

### Options

| Parameter | Description |
|-----------|-------------|
| Exposed Entities | Select which HA entities to make available in Sber Smart Home |

## Removal

1. Go to **Settings** > **Devices & Services**
2. Find "Sber Smart Home MQTT Bridge"
3. Click the three dots menu and select "Delete"

## Troubleshooting

- **Cannot connect**: Verify your Sber MQTT credentials in Sber Studio
- **SSL errors**: Try disabling SSL verification in the integration options (for brokers with custom CA)
- **Entities not appearing in Sber**: Check that entities are selected in integration options
- **Enable debug logging**: Add to `configuration.yaml`:
  ```yaml
  logger:
    logs:
      custom_components.sber_mqtt_bridge: debug
  ```

## Acknowledgments

This project is a fork and evolution of [MQTT-SberGate](https://gitverse.ru/mberezovsky/MQTT-SberGate) by [@mberezovsky](https://gitverse.ru/mberezovsky). The original project provided the Sber Smart Home MQTT protocol implementation as a Home Assistant addon. This version has been rewritten as a native HACS custom integration with full async support, Config Flow UI, and comprehensive test coverage.

Thank you to the original author for the foundational work and Sber protocol reverse-engineering.

## Trademarks & Legal Notice

All product names, logos, and brands mentioned in this project are property of their respective owners:

- **Sber**, **SberDevices**, **Salut**, **Sber Smart Home** are trademarks of [Sber](https://www.sber.ru/) (PAO Sberbank).
- **Home Assistant** is a trademark of the [Home Assistant](https://www.home-assistant.io/) project.
- **HACS** (Home Assistant Community Store) is an independent community project.

This project is not affiliated with, endorsed by, or sponsored by Sber, SberDevices, or the Home Assistant project. It is an independent open-source community integration.

## Links

- [Sber Smart Home Developer Portal](https://developers.sber.ru/docs/ru/smarthome)
- [Register in Sber Studio](https://developers.sber.ru/docs/ru/smarthome/space/registration)
- [MQTT-to-Cloud Integration](https://developers.sber.ru/docs/ru/smarthome/mqtt-diy/mqtt-to-diy)
- [Supported Device Categories](https://developers.sber.ru/docs/ru/smarthome/c2c/devices)
- [Telegram Community](https://t.me/+k_w9uO0h73FkNjJi)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

[MIT](LICENSE.txt)
