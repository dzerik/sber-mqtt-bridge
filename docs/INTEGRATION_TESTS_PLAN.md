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

## Device-Specific Integration Scenarios (11-25)

### Fixtures

```python
@pytest.fixture
async def bridge_with_climate(hass, service_calls):
    """Bridge с climate entity (hvac_ac)."""
    hass.states.async_set("climate.ac", "cool", {
        "hvac_modes": ["off", "cool", "heat", "dry", "fan_only", "auto"],
        "fan_modes": ["auto", "low", "medium", "high"],
        "swing_modes": ["off", "vertical", "horizontal"],
        "preset_modes": ["sleep", "boost"],
        "current_temperature": 24.5,
        "temperature": 22,
        "fan_mode": "auto",
        "swing_mode": "off",
    })
    # ...yield bridge, mqtt_client, service_calls

@pytest.fixture
async def bridge_with_curtain(hass, service_calls):
    """Bridge с cover entity."""
    hass.states.async_set("cover.curtain", "open", {
        "current_position": 75,
    })
    # ...

@pytest.fixture
async def bridge_with_vacuum(hass, service_calls):
    """Bridge с vacuum entity."""
    hass.states.async_set("vacuum.robo", "docked", {
        "fan_speed": "standard",
        "fan_speed_list": ["quiet", "standard", "turbo"],
        "battery_level": 85,
    })
    # ...
```

### 11. Climate: hvac_mode Change Cascade
```
Sber: hvac_work_mode=cooling → bridge: climate.set_hvac_mode(cool)
→ HA: state changes to "cool" + fan_mode resets to "auto"
→ bridge: publish hvac_work_mode=cooling + hvac_air_flow_power=auto
```
Проверяем: service call с `hvac_mode`, state publish с обоими features.

### 12. Climate: Temperature + Mode в одной команде
```
Sber: [hvac_temp_set=25, hvac_work_mode=heating] (одно сообщение)
→ bridge: set_temperature(25) + set_hvac_mode(heat)
→ HA: state=heat, temperature=25
→ publish: оба значения
```
Проверяем: два service calls, publish содержит оба.

### 13. Climate: Night Mode Toggle
```
Sber: hvac_night_mode=true → bridge: set_preset_mode("sleep")
→ HA: preset_mode=sleep → publish: hvac_night_mode=true + hvac_work_mode=quiet
Sber: hvac_night_mode=false → bridge: set_preset_mode(first non-night)
→ HA: preset_mode=none → publish: hvac_night_mode=false
```
Проверяем: preset_mode переключается, work_mode меняется.

### 14. Humidifier: Mode + Humidity в одной команде
```
Sber: [hvac_humidity_set=60, hvac_air_flow_power=medium]
→ bridge: set_humidity(60) + set_mode(medium)
→ publish: оба значения
```
Проверяем: два service calls, оба в publish.

### 15. Curtain: Position 0→50→100 + open_state Consistency
```
Sber: open_percentage=50 → bridge: set_cover_position(50)
→ HA: position=50, state=open → publish: open_percentage="50", open_state="open"
Sber: open_percentage=0 → bridge: set_cover_position(0)
→ HA: position=0, state=closed → publish: open_percentage="0", open_state="close"
```
Проверяем: open_state **всегда** консистентен с percentage (pos>0→open, pos=0→close).

### 16. Curtain: Open/Close/Stop Commands
```
Sber: open_set=open → bridge: open_cover
Sber: open_set=stop → bridge: stop_cover
Sber: open_set=close → bridge: close_cover
```
Проверяем: правильные service calls для каждого enum.

### 17. TV: Volume + Mute + Source Cascade
```
Sber: [volume_int=30, mute=false, source="HDMI"] (одно сообщение)
→ bridge: volume_set(0.3) + volume_mute(false) + select_source("HDMI")
→ publish: все три значения
```
Проверяем: три service calls, volume конвертирован (30→0.3).

### 18. TV: Channel Int + Direction
```
Sber: channel_int=5 → bridge: play_media(channel, "5")
Sber: direction=ok → bridge: media_play_pause
Sber: channel="+" → bridge: media_next_track
```
Проверяем: правильные service calls.

### 19. Vacuum: Full Lifecycle
```
Sber: vacuum_cleaner_command=start → bridge: vacuum.start
→ HA: state=cleaning → publish: status=cleaning
Sber: vacuum_cleaner_command=return_to_base → bridge: vacuum.return_to_base
→ HA: state=returning → publish: status=go_home
→ HA: state=docked → publish: status=standby
```
Проверяем: полный цикл с правильными Sber enum на каждом шаге.

### 20. Fan: Simple Relay (no speed)
```
Sber: on_off=true → bridge: fan.turn_on
→ publish: on_off=true (NO hvac_air_flow_power!)
Sber: hvac_air_flow_power=high → bridge: IGNORED (no speed support)
→ publish: on_off only
```
Проверяем: простой fan без speed не крашится на speed command.

### 21. Sensor: Linked Data Propagation
```
Parent: sensor_temp (temperature) linked with battery + humidity
→ battery sensor changes → parent re-reads battery
→ publish: temperature + battery_percentage + humidity
```
Проверяем: linked data обновляется и публикуется вместе с parent.

### 22. Valve: Open/Close + Battery Linked
```
Sber: open_set=open → bridge: valve.open_valve
→ HA: state=open → publish: open_state="open"
Battery linked sensor changes: 85→20
→ publish: open_state + battery_percentage="20" + battery_low_power=false
Battery linked: 20→15
→ publish: battery_low_power=true (threshold < 20%)
```
Проверяем: valve state + linked battery с порогом.

### 23. PIR: Event-Based (No Idle State)
```
HA: binary_sensor off→on → publish: pir="pir"
HA: binary_sensor on→off → publish: online=true (NO pir key!)
```
Проверяем: pir ключ **отсутствует** при state=off.

### 24. Redefinitions: Edit → Re-publish
```
User: update_redefinitions(entity, name="Новое имя", room="Спальня")
→ bridge: persist + re-publish config
→ Config JSON: name="Новое имя", room="Спальня"
```
Проверяем: redefinitions в config payload.

### 25. Multiple Entities Same Device (Temp + Humidity)
```
Device has: sensor.temp (primary, sensor_temp) + sensor.humidity (linked)
→ humidity changes → parent sensor.temp re-reads
→ publish: temperature + humidity обновлённые
Temperature changes → publish: temperature новая + humidity текущая
```
Проверяем: linked entities обновляются при изменении любого sibling.

---

## Порядок реализации

### Этап 1 — Инфраструктура и базовые сценарии
1. **Fixtures**: `bridge_with_light`, `bridge_with_climate`, `bridge_with_curtain`, `bridge_with_vacuum`, helpers
2. **Сценарии 1, 8**: базовый command→state→publish (самые простые)
3. **Сценарии 2, 4**: delayed confirm + RGB (баг из реальной жизни)

### Этап 2 — Device-specific: Climate, Humidifier
4. **Сценарии 11, 12, 13**: climate mode cascade, multi-command, night mode
5. **Сценарий 14**: humidifier mode + humidity

### Этап 3 — Device-specific: Cover, TV, Vacuum
6. **Сценарии 15, 16**: curtain position + open_state consistency
7. **Сценарии 17, 18**: TV volume cascade + channel/direction
8. **Сценарий 19**: vacuum full lifecycle

### Этап 4 — Device-specific: Sensors, Valve, Fan
9. **Сценарии 20, 21, 22**: fan simple relay, sensor linked data, valve + battery
10. **Сценарий 23**: PIR event-based (no idle state)

### Этап 5 — Edge cases и redefinitions
11. **Сценарии 3, 5**: async device, debounce
12. **Сценарий 7**: reconnect guard
13. **Сценарии 6, 10**: rapid commands, concurrent
14. **Сценарий 9**: config rejection
15. **Сценарии 24, 25**: redefinitions, multiple entities same device

## Зависимости

- `pytest-homeassistant-custom-component` (уже установлен)
- `pytest-asyncio` с `asyncio_mode=auto` (уже настроен)
- `pytest-freezer` (уже установлен — для time control)
