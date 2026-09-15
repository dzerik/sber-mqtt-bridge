# Contributing to Sber Smart Home MQTT Bridge

## Development Setup

```bash
git clone https://github.com/dzerik/sber-mqtt-bridge.git
cd sber-mqtt-bridge
uv venv .venv
source .venv/bin/activate
uv pip install --constraint=.github/workflows/constraints.txt \
  aiomqtt pytest pytest-asyncio pytest-homeassistant-custom-component pytest-cov ruff mypy
```

`.github/workflows/constraints.txt` pins the same Home Assistant, ruff and mypy
versions CI uses, so a local run reports what CI will.

## Running Tests

```bash
pytest tests/hacs/ -v -o asyncio_mode=auto
```

## Linting

```bash
ruff check custom_components/
ruff format custom_components/
mypy custom_components/sber_mqtt_bridge/
```

CI runs all three and fails on any finding.  mypy is a ratchet: modules that
had type errors when the check was introduced are listed under
`[[tool.mypy.overrides]]` in `pyproject.toml`.  Remove a module from that list
once it is clean; never add one — new code must type-check.

## Adding a New Device Type

Choose the appropriate base class:

- **On/off devices** (switch, valve, socket): inherit from `OnOffEntity`
  - Override `process_cmd` to map Sber commands to HA service calls
  - `fill_by_ha_state`, `_create_features_list`, `to_sber_current_state`, `process_state_change` are provided

- **Read-only sensors** (temperature, humidity, motion, door, leak): inherit from `SimpleReadOnlySensor`
  - Set `_sber_value_key` and `_sber_value_type` class attributes
  - Implement `_get_sber_value()` and `fill_by_ha_state()`
  - `_create_features_list`, `to_sber_current_state`, `process_cmd`, `process_state_change` are provided

- **Complex devices** (climate, light, curtain): inherit from `BaseEntity`
  - Implement all abstract methods: `to_sber_current_state`, `process_cmd`

Steps:
1. Create a new class in `custom_components/sber_mqtt_bridge/devices/`
2. Add to factory in `sber_entity_map.py`
3. Write tests in `tests/hacs/`
4. Use `_LOGGER = logging.getLogger(__name__)` convention

## Commit Messages

Format: `type: description`

Types: `feat`, `fix`, `refactor`, `docs`, `chore`, `perf`, `test`
