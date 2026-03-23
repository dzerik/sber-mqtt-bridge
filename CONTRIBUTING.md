# Contributing to Sber Smart Home MQTT Bridge

## Development Setup

```bash
git clone https://github.com/mberezovsky/MQTT-SberGate.git
cd MQTT-SberGate
uv venv .venv
source .venv/bin/activate
uv pip install aiomqtt pytest pytest-asyncio pytest-homeassistant-custom-component pytest-cov ruff mypy
```

## Running Tests

```bash
pytest tests/hacs/ -v -o asyncio_mode=auto
```

## Linting

```bash
ruff check custom_components/
ruff format custom_components/
```

## Adding a New Device Type

1. Create a new class in `custom_components/sber_mqtt_bridge/devices/`
2. Inherit from `BaseEntity`
3. Implement: `fill_by_ha_state`, `create_features_list`, `to_sber_current_state`, `process_cmd`, `process_state_change`
4. Add to factory in `sber_entity_map.py`
5. Write tests in `tests/hacs/`

## Commit Messages

Format: `type: description`

Types: `feat`, `fix`, `refactor`, `docs`, `chore`, `perf`, `test`
