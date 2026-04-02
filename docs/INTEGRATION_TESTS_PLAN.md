# Integration Flow Tests — Plan

## Проблема

Unit тесты (1174) покрывают формат JSON и enum значения, но **не ловят race conditions**:

| Баг | Как нашли | Почему unit тест не поймал |
|-----|----------|---------------------------|
| RGB: state confirm шлёт "white" вместо "colour" | Вживую на ESPHome лампе | `hs_color` = tuple, а тест использовал list |
| Debounce skip при смене цвета | Вживую | `has_significant_change()` не вызывался в тестах |
| Delayed confirm не отправлялся | Вживую | `async_create_task` не тестировался |
| `color_temp` deprecated в HA 2025+ | Вживую (voluptuous error) | Unit тест не вызывал реальный HA service |

## Цель

Файл: `tests/hacs/test_integration_flows.py`

Тестируем полный цикл: **Sber MQTT command → process_cmd → HA service call → state_changed → fill_by_ha_state → publish_states → MQTT publish**

---

## Готовые инструменты (НЕ изобретать велосипед)

### Из `pytest-homeassistant-custom-component`:

| Fixture | Назначение | Наш use case |
|---------|-----------|-------------|
| `hass` | Полный экземпляр HA | Основа всех тестов |
| `service_calls` | Перехват service calls | Проверка `light.turn_on` params |
| `async_fire_time_changed` | Промотка времени | Delayed confirm 1.5s |
| `entity_registry` | Entity registry | Создание test entities |
| `device_registry` | Device registry | Device linking |
| `area_registry` | Area registry | Room resolution |
| `hass_storage` | Мок storage | Redefinitions persistence |
| `MockConfigEntry` | Config entry | Setup bridge |

### Свои моки (aiomqtt):

```python
# aiomqtt.Client — мокаем потому что мы не используем HA built-in MQTT
with patch("custom_components.sber_mqtt_bridge.sber_bridge.aiomqtt.Client") as mqtt_cls:
    mqtt_client = AsyncMock()
    mqtt_client.publish = AsyncMock()
    # ...
```

### НЕ нужно мокать:
- `hass.states` — использовать реальный state machine (`hass.states.async_set()`)
- `hass.services.async_call` — перехватывается через `service_calls` fixture
- `entity_registry` / `device_registry` — реальные из `hass` fixture

---

## Архитектура Fixtures

```python
@pytest.fixture
async def bridge_with_light(hass, service_calls, entity_registry, device_registry):
    """Bridge с RGB лампой, mocked MQTT, реальный hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "test", "password": "test", "host": "localhost"},
        options={"exposed_entities": ["light.test_lamp"]},
    )
    entry.add_to_hass(hass)

    # Регистрируем entity в HA
    hass.states.async_set("light.test_lamp", "on", {
        "color_mode": "color_temp",
        "supported_color_modes": ["color_temp", "hs", "rgb"],
        "brightness": 255,
        "color_temp": 300,
        "hs_color": (45.0, 60.0),  # TUPLE — как реальный HA
        "rgb_color": (255, 219, 102),
        "friendly_name": "Test Lamp",
    })

    mqtt_client = AsyncMock()
    mqtt_client.publish = AsyncMock()

    bridge = SberBridge(hass, entry)
    bridge._mqtt_client = mqtt_client
    bridge._connected = True
    # Build entities
    # ...

    yield bridge, mqtt_client, service_calls


@pytest.fixture
async def bridge_with_sensor(hass, service_calls):
    """Bridge с PIR сенсором для event-based тестов."""
    # ...


@pytest.fixture  
async def bridge_with_climate(hass, service_calls):
    """Bridge с climate entity для HVAC тестов."""
    # ...
```

### Helper функции:

```python
async def simulate_sber_command(bridge, entity_id: str, states: list[dict]):
    """Отправить command от Sber как MQTT message."""
    payload = json.dumps({"devices": {entity_id: {"states": states}}}).encode()
    await bridge._handle_sber_command(payload)

def get_published_payloads(mqtt_mock) -> list[dict]:
    """Извлечь все опубликованные state payloads из MQTT mock."""
    return [
        json.loads(call.args[1])
        for call in mqtt_mock.publish.call_args_list
        if "up/status" in str(call.args[0])
    ]

async def advance_time(hass, seconds: float):
    """Промотать время для delayed confirm."""
    future = dt_util.utcnow() + timedelta(seconds=seconds)
    async_fire_time_changed(hass, future)
    await hass.async_block_till_done()
```

---

## 10 тестовых сценариев

### 1. Command → Service Call → State Confirm
```
Sber: on_off=true → bridge: light.turn_on → HA: state=on → bridge: publish on_off=true
```
Проверяем: service_calls содержит light.turn_on, MQTT publish содержит on_off=true.

### 2. Delayed State Confirm (1.5s)
```
Sber: light_colour command → bridge: light.turn_on(hs_color=...) 
→ 1.5s → bridge: re-read HA state → publish colour mode
```
Проверяем: `async_fire_time_changed` промотка → MQTT publish с light_mode="colour".

### 3. Async Device (ESPHome)
```
Sber: command → bridge: service call → HA state NOT updated yet
→ immediate publish = stale → 1.5s → HA state updated → publish = correct
```
Проверяем: два publish — первый stale, второй correct.

### 4. RGB Mode Switch
```
Sber: light_mode=colour, light_colour={h,s,v}
→ bridge: turn_on(hs_color=...)
→ immediate: color_mode still "color_temp" → publish "white" (BUG без delayed confirm)
→ 1.5s: color_mode="rgb" → publish "colour" (FIX)
```
Проверяем: финальный publish содержит light_mode="colour".

### 5. Debounce: Same State Different Attrs
```
Light on (white) → Sber: change color → still "on" but color changed
→ has_significant_change() must return True
```
Проверяем: publish НЕ пропущен.

### 6. Rapid Commands (3 за 500ms)
```
Sber: brightness=300 → brightness=500 → brightness=700 (rapid fire)
→ debounce: один publish с brightness=700
```
Проверяем: MQTT publish вызван минимально, финальное значение правильное.

### 7. Reconnect Guard
```
Bridge reconnects → _awaiting_sber_ack=True
→ Sber: turn_off command → REJECTED → re-publish current HA state (on)
→ Sber: status_request → _awaiting_sber_ack=False
→ Sber: turn_off command → ACCEPTED
```
Проверяем: первая команда отклонена, вторая принята.

### 8. State Confirm After on_off
```
Sber: turn_on → HA: state off→on → bridge: publish on_off=true
```
Проверяем: MQTT publish с on_off=true (confirmation).

### 9. Config Rejection (Invalid Device)
```
Device with invalid field → Sber reject entire config → error in logs
→ All devices unacknowledged
```
Проверяем: pydantic validation warning, но publish всё равно происходит.

### 10. Concurrent State Changes
```
light.a changes → light.b changes (same moment)
→ Both published, none lost
```
Проверяем: оба entity в publish payload.

---

## Порядок реализации

1. **Fixtures**: `bridge_with_light`, helpers
2. **Сценарии 1, 8**: базовый command→state→publish (самые простые)
3. **Сценарии 2, 4**: delayed confirm + RGB (баг из реальной жизни)
4. **Сценарии 3, 5**: async device, debounce (timing-sensitive)
5. **Сценарий 7**: reconnect guard
6. **Сценарии 6, 10**: rapid commands, concurrent (edge cases)
7. **Сценарий 9**: config rejection

## Зависимости

- `pytest-homeassistant-custom-component` (уже установлен)
- `pytest-asyncio` с `asyncio_mode=auto` (уже настроен)
- `pytest-freezer` (уже установлен — для time control)
