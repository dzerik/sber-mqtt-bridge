# Sber Spec 2026-05 Alignment — Design

Дата: 2026-07-03
Затрагивает: v1.40.0
Статус: draft (ожидает review)

## Контекст

Спецификация Sber Smart Home (`developers.sber.ru/docs/ru/smarthome/c2c`)
обновилась между 2026-04-12 и 2026-05-21. Одновременно с этим в этой сессии
починен наш скрапер (`tools/fetch_sber_schemas.py`) — два бага, из-за
которых свежие данные раньше выглядели как «Sber что-то убрал»:

- `_parse_categories_from_text` строил `functions[X].used_in_categories`
  по хрупкому парсингу текста функциональной страницы. Заменён на
  `build_used_in_categories()` — обратный индекс, построенный из таблиц
  `Доступные функции` каждой категории. Результат детерминистичный.
- JS-экстрактор таблицы фич не различал `✔︎` и `✔︎*`. Оба попадали в
  `obligatory`. Разделены на `obligatory` (strict `✔︎`) и `conditional`
  (`✔︎*`, «хотя бы одна из отмеченных должна быть у устройства»).

После регенерации свежего снапшота (`sber_full_spec.json`, 96 функций,
28 категорий + `sensor_air` в очереди) выявлено 8 сдвигов относительно
нашего кода и `_generated/`. Настоящий документ фиксирует, какие из них
надо адаптировать, каким образом и в каком порядке.

## Инвентарь изменений (source-of-truth таблица)

| Уровень | Изменение | Наше текущее состояние | Планируемое действие |
|---|---|---|---|
| **P0.1** | `hvac_temp_set` mandatory для всех HVAC-категорий | `ClimateEntity._create_features_list` уже включает `hvac_temp_set` (`custom_components/sber_mqtt_bridge/devices/climate.py:290`) и эмитит его в `to_sber_current_state` (`climate.py:389`) | **No-op.** Наш код уже соответствует. |
| **P0.2** | `gas_leak_state` mandatory для `sensor_gas` | `GasSensorEntity._sber_value_key = "gas_leak_state"` — фактически основной канал сенсора | **No-op.** |
| **P0.3** | `humidity`/`temperature` в `sensor_temp`: `✔︎ → ✔︎*` | `CATEGORY_OBLIGATORY_FEATURES[sensor_temp] = {humidity, online, temperature}` — строже, чем спек; `missing_obligatory_features()` возвращает лишние поля и локально отклоняет валидные устройства (например, чисто-температурный HA-датчик без влажности) | **Regen `_generated/`** от свежего снапшота — `codegen.py` уже читает поле `obligatory` (строка 167), это автоматически даст `{online}` |
| **P0.4** | `open_percentage`/`open_set` для `curtain`/`gate`/`valve`/`window_blind`: `✔︎ → ✔︎*` | Те же четыре категории с избыточной валидацией | То же самое — **regen** даст `{online, open_state}` |
| **P1** | Новая категория `sensor_air` (13 features, 8 из них conditional-any-of: `temperature`, `humidity`, `co2`, `pm1_0`, `pm2_5`, `pm10`, `tvoc_float`, `hcho_float`) | Не поддерживается | **Новый класс** `SensorAirEntity` + `LINKABLE_ROLES` из 8 measurement-ролей + `CATEGORY_DOMAIN_MAP` mapping + локализации |
| **P2.1** | `hvac_water_percentage` (optional) для `hvac_humidifier` | Не поддерживается | Один `AttrSpec` в `HumidifierEntity` + emit в `to_sber_current_state` |
| **P2.2** | `kitchen_water_temperature` (optional) для `kettle` | Не поддерживается | Один `AttrSpec` в `KettleEntity` + emit |
| **Deferred** | `channel`/`channel_int` для `tv`, `open_left_set`/`open_right_state` для двустворчатых, `hvac_water_low_level` для humidifier | Не поддерживается | Отдельные PR по запросу пользователей |

## Ключевые архитектурные решения

Все три решения были приняты явно в штурме — фиксируются здесь как
основа для реализации.

### D1. Conditional features локально не валидируются

`CATEGORY_OBLIGATORY_FEATURES` содержит только strict `✔︎`. Пропуск
`conditional`-фич — на усмотрение Sber cloud. Обоснование:

- Наш `missing_obligatory_features()` создавался как защита от известных
  silent-reject. Для conditional-фич Sber сам определяет валидность —
  дублирование локально даст false-reject там, где сервер бы принял.
- `AckAudit` (v1.30.0) уже ловит silent-rejection на трафике. Если
  реальный `sensor_air` без `co2` начнёт отклоняться — увидим и адаптируемся.
- Дешевле: одна колонка снапшота вместо новой схемы «группы any-of».

Альтернативные варианты, отвергнутые в штурме:

- `CATEGORY_CONDITIONAL_FEATURES: dict[str, frozenset[str]]` + предикат
  `at-least-one` в валидаторе. Даёт максимальную защиту, но добавляет
  новый инвариант, который надо поддерживать в codegen и тестах.
- WARN без блокировки. Компромисс, но захламляет логи для устройств,
  которые Sber всё равно принимает.

### D2. `sensor_air` через существующий Entity Linking

Один Sber `sensor_air` объединяет N HA-сенсоров одного физического
устройства (co2 + pm25 + pm10 + tvoc + …). Механика — как у
`SensorTempEntity` + `linked humidity`:

- Primary: любой из HA-сенсоров подходящего `device_class` (обычно
  `carbon_dioxide` — если у пользователя есть Aqara AirBox или подобный
  датчик, CO2 обычно первый в HA registry).
- Остальные измерения того же `device_id` — через `LinkableRole` +
  `update_linked_data`.
- Wizard (`HaDeviceGrouper.suggest_links`) уже группирует HA-сущности
  по `device_id`. Никакого нового авто-детектора не требуется — просто
  добавляем новые роли в `LINKABLE_ROLES`.

Альтернативы, отвергнутые в штурме:

- Автогруппировка по `device_class` без явного linking — новый механизм,
  дублирует существующий wizard flow.
- Один HA-sensor = отдельный Sber-девайс — засоряет UI Sber-приложения
  восемью «дубликатами» на один физический прибор.

### D3. P2 = только пассивные win'ы

В спек попадают только `hvac_water_percentage` и `kitchen_water_temperature` —
обе тривиальны: `AttrSpec` → forward в `to_sber_current_state`. Никаких
новых команд, UI-полей, wizard-логики.

## Компоненты — детальный дизайн

### Компонент 1: Регенерация `_generated/`

**Задача:** синхронизировать `custom_components/sber_mqtt_bridge/_generated/`
со свежим `sber_full_spec.json`.

**Действие:**

```bash
python tools/codegen.py
```

`codegen.py::render_obligatory_features` (line 167) читает
`categories[category].get("obligatory", [])`. Свежий снапшот содержит
только strict `✔︎`, поэтому regen автоматически:

- Уберёт `humidity`, `temperature` из `CATEGORY_OBLIGATORY_FEATURES[sensor_temp]`.
- Уберёт `open_percentage`, `open_set` из obligatory для curtain/gate/valve/window_blind.
- Подхватит новые функции (`co2`, `pm1_0`, `pm2_5`, `pm10`, `tvoc_float`,
  `hcho_float`) в `FEATURE_TYPES` — с их типами.
- Обновит `SPEC_GENERATED_AT` и `SPEC_SOURCE`.

**Файлы**, которые меняются:

- `_generated/obligatory_features.py`
- `_generated/category_features.py` (добавит новые фичи в CATEGORY_REFERENCE_FEATURES)
- `_generated/feature_types.py` (добавит FEATURE_TYPES для новых)

**Файлы**, которые НЕ меняются: device-классы, `sber_models.py`, тесты
(кроме `test_codegen_safety.py`, который читает свежие значения — при
первом запуске старые ожидания станут актуальными автоматически).

### Компонент 2: `SensorAirEntity`

**Новые ролевые константы** в `custom_components/sber_mqtt_bridge/devices/base_entity.py`
(рядом с существующими `ROLE_HUMIDITY`, `ROLE_BATTERY`, `ROLE_SIGNAL`):

```python
ROLE_CO2 = "co2"
ROLE_PM1 = "pm1"
ROLE_PM25 = "pm25"
ROLE_PM10 = "pm10"
ROLE_TVOC = "tvoc"
ROLE_HCHO = "hcho"
ROLE_TEMPERATURE = "temperature"
```

`ROLE_HUMIDITY` уже определён.

**Новые SberFeature константы** в `sber_constants.py`:

```python
CO2 = "co2"
PM1_0 = "pm1_0"
PM2_5 = "pm2_5"
PM10 = "pm10"
TVOC_FLOAT = "tvoc_float"
HCHO_FLOAT = "hcho_float"
```

**Новый файл** `custom_components/sber_mqtt_bridge/devices/sensor_air.py`:

```python
"""Sber Air Quality Sensor entity — maps HA air-quality sensors to Sber sensor_air.

Sber category ``sensor_air`` accepts a bundle of measurements from one
physical device: temperature, humidity, CO2, PM1/2.5/10, TVOC, HCHO.
Any subset is valid — spec marks all 8 measurement features as
conditional (✔︎*, "at least one of these").

We model this as one primary HA-entity + linked entities per role,
mirroring the SensorTempEntity + humidity-linked pattern.
"""

from __future__ import annotations

import logging
import math

from ..sber_constants import SberFeature
from ..sber_models import make_float_value, make_integer_value, make_state
from .base_entity import (
    BaseEntity,
    ROLE_CO2, ROLE_HCHO, ROLE_HUMIDITY, ROLE_PM1, ROLE_PM10, ROLE_PM25,
    ROLE_TEMPERATURE, ROLE_TVOC, SENSOR_LINK_ROLES,
)

_LOGGER = logging.getLogger(__name__)

SENSOR_AIR_CATEGORY = "sensor_air"


class SensorAirEntity(BaseEntity):
    """Sber air-quality sensor.

    Reports up to eight independent measurements to Sber. Any subset
    is valid; empty fields are omitted from ``to_sber_current_state``.

    Naследует от BaseEntity напрямую (не от SimpleReadOnlySensor),
    потому что у sensor_air нет одной primary-фичи — восемь measurement
    полей равноправны и все conditional по спеку Sber (✔︎*). Primary HA
    entity — просто «главный» sensor, который пользователь выбрал в
    wizard; его device_class определяет, в какое поле пойдёт state.
    """

    LINKABLE_ROLES = (
        *SENSOR_LINK_ROLES,
        ROLE_CO2, ROLE_PM1, ROLE_PM25, ROLE_PM10,
        ROLE_TVOC, ROLE_HCHO,
        ROLE_TEMPERATURE, ROLE_HUMIDITY,
    )

    def __init__(self, entity_data: dict) -> None:
        super().__init__(SENSOR_AIR_CATEGORY, entity_data)
        self._co2: int | None = None
        self._pm1: int | None = None
        self._pm25: int | None = None
        self._pm10: int | None = None
        self._tvoc: float | None = None
        self._hcho: float | None = None
        self._temperature: float | None = None
        self._humidity: int | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Route the primary HA sensor into the correct measurement field."""
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        device_class = attrs.get("device_class")
        state_raw = ha_state.get("state")
        # Detailed dispatch per device_class → self._<field>
        # (implementation in the plan)

    def update_linked_data(self, role: str, ha_state: dict) -> None:
        """Fill a specific measurement from a linked HA sensor."""
        super().update_linked_data(role, ha_state)
        # role → field mapping (implementation in the plan)

    def to_sber_current_state(self) -> list[dict]:
        """Emit make_state() entries only for populated measurements."""
        out = super().to_sber_current_state()
        # For each non-None field, append the corresponding SberFeature
        # (implementation in the plan)
        return out
```

**Регистрация в фабрике** — `sber_entity_map.py::CATEGORY_DOMAIN_MAP`:

```python
AIR_QUALITY_DEVICE_CLASSES = frozenset({
    "carbon_dioxide", "pm1", "pm25", "pm10", "volatile_organic_compounds",
})

"sensor_air": CategorySpec(
    cls=SensorAirEntity,
    ha_domains=("sensor",),
    matches=lambda entity_data: (
        entity_data.get("device_class") in AIR_QUALITY_DEVICE_CLASSES
    ),
    ui_meta=CategoryUIMeta(
        label_key="category.sensor_air",
        icon="mdi:air-filter",
    ),
),
```

Плюс `sensor_air` добавляется в кортеж `CATEGORIES` в `tools/fetch_sber_schemas.py`
и в проверяемое множество тестов.

**Локализация** — `strings.json`, `translations/en.json`, `translations/ru.json`:

- `category.sensor_air` = «Датчик качества воздуха» / «Air quality sensor»
- Метки ролей: `co2`, `pm1`, `pm25`, `pm10`, `tvoc`, `hcho`
- (роли temperature/humidity уже локализованы)

### Компонент 3: `hvac_water_percentage`

**Файл:** `custom_components/sber_mqtt_bridge/devices/humidifier.py`.

**Изменение в `ATTR_SPECS`:**

```python
AttrSpec(
    field="_water_percentage",
    attr_keys=("water_level",),
    parser=lambda v: max(0, min(100, int(float(v)))),
    default=None,
),
```

**Изменение в `to_sber_current_state`:**

```python
if self._water_percentage is not None:
    out.append(make_state(
        SberFeature.HVAC_WATER_PERCENTAGE,
        make_integer_value(self._water_percentage),
    ))
```

`SberFeature.HVAC_WATER_PERCENTAGE = "hvac_water_percentage"` добавляется
в `sber_constants.py`.

`hvac_water_low_level` (BOOL) — не включаем в этот спек. Если понадобится
в будущем, будет тривиальным дополнением: `self._water_percentage < 10`.

### Компонент 4: `kitchen_water_temperature`

**Файл:** `custom_components/sber_mqtt_bridge/devices/kettle.py`.

**Изменение в `ATTR_SPECS`:**

```python
AttrSpec(
    field="_water_temp",
    attr_keys=("current_temperature", "temperature"),
    parser=float,
    default=None,
),
```

**Изменение в `to_sber_current_state`:**

```python
if self._water_temp is not None and math.isfinite(self._water_temp):
    out.append(make_state(
        SberFeature.KITCHEN_WATER_TEMPERATURE,
        make_integer_value(round(self._water_temp * 10)),
    ))
```

`SberFeature.KITCHEN_WATER_TEMPERATURE = "kitchen_water_temperature"` добавляется
в `sber_constants.py`.

## Data flow

`sensor_air` — read-only (Sber не шлёт команды датчикам качества воздуха):

```
HA state_changed для одного из связанных сенсоров
  → HaStateForwarder._on_state_changed(entity_id, new_state)
  → resolve primary/linked role по entity_id
  → SensorAirEntity.fill_by_ha_state()   ← если primary
    или SensorAirEntity.update_linked_data(role, state)   ← если linked
  → SensorAirEntity.to_sber_current_state()
  → build_states_list_json → MqttClientService.publish
```

Для `hvac_water_percentage` / `kitchen_water_temperature` — тот же
существующий поток HumidifierEntity / KettleEntity, просто с новыми
AttrSpec и одной строкой в `to_sber_current_state`.

## Тестирование

| Файл | Задача |
|---|---|
| `tests/hacs/test_devices_sensor_air.py` (новый) | Parsing primary state с разными `device_class`, `update_linked_data` для каждой роли, `to_sber_current_state` с 1/несколькими/всеми ролями заполненными, edge cases (`None`, `unknown`, `unavailable`, отсутствующий `device_class`), unit conversions (temperature×10, tvoc float precision) |
| `tests/hacs/test_category_domain_map.py` (расширить) | `sensor_air` присутствует, `matches()` возвращает True для carbon_dioxide и pm25, False для температурного датчика; ha_domain = `sensor` |
| `tests/hacs/test_sber_compliance_sensors_covers_tv.py` (расширить) | Собранный sensor_air payload валиден по свежему `sber_full_spec.json` (features ⊂ all_features, obligatory ⊆ features) |
| `tests/hacs/test_devices_humidifier.py` (расширить) | `_water_percentage` парсинг из attribute `water_level`, clamping 0..100, emit при not-None |
| `tests/hacs/test_devices_kettle.py` (расширить) | `_water_temp` парсинг с двух возможных атрибутов, ×10 в `make_integer_value`, skip при NaN/None |
| `tests/hacs/test_codegen_safety.py` | После regen `sensor_temp` obligatory = `{online}`; curtain/gate/valve/window_blind — `{online, open_state}`; проверка что drift снапшота не остался |
| `tests/hacs/test_websocket_devices_grouped.py` (расширить) | Wizard `suggest_links` группирует HA-сенсоры с air-quality device_class в один `sensor_air` кандидат |

Полный прогон через существующий CI (`pytest -n auto --timeout=30 -k "not test_config_flow"`).

## Миграция и backward compatibility

- **`_generated/` regen** — строго backward-compatible. Устройства,
  которые эмитили и `humidity`, и `temperature`, продолжат эмитить обе.
  Устройства, у которых только одна, — раньше отклонялись локально
  `missing_obligatory_features()`, теперь пройдут. Ни одно ранее
  валидное устройство не станет невалидным.
- **`SensorAirEntity`** — новая категория. Пользователи без air-quality
  сенсоров ничего не заметят. У кого есть — в wizard появится новый
  тип устройства.
- **Новые `SberFeature` константы** — additive, StrEnum не имеет обратной
  ссылки на потребителей.
- **Config entries** — миграции не требуют, `options` не меняются.
- **Version bump** — MINOR (`1.39.8 → 1.40.0`) по правилу `CLAUDE.md`:
  новая функциональность backward-compatible.

## План коммитов

1. **`fix(scraper): inverse-index + conditional marker + main.js discovery`**
   Уже готово в этой сессии (uncommitted): фиксы скрапера,
   `build_used_in_categories`, разделение `obligatory` vs `conditional`,
   Phase 0b MVP через main.js, 9 unit-тестов, свежий snapshot.

2. **`chore(generated): regen _generated/ from fresh spec`**
   Одна команда `python tools/codegen.py`. Реализует P0.3 + P0.4.

3. **`feat(devices/sensor_air): new SensorAirEntity + Entity Linking`**
   P1: новый класс, роли, факт-мэппинг, локализация, тесты.

4. **`feat(devices): hvac_water_percentage + kitchen_water_temperature`**
   P2 win'ы: две AttrSpec + две строки в `to_sber_current_state` + тесты.

5. **`chore: release v1.40.0`**
   Bump через `tools/bump_version.py minor`, CHANGELOG, тег.

## Отложено (не в этом спеке)

- `channel` / `channel_int` для `tv` — требует UI-побуждения (list каналов
  или мэппинг на HA `media_player.select_source`).
- `open_left_set` / `open_right_state` для двустворчатых `curtain`/`gate` —
  HA-cover обычно однопозиционный, нужен «двустворчатый» wrapper.
- `hvac_water_low_level` для humidifier — тривиально, но требует новой
  StrEnum константы; отложено, если пользователи попросят.
- **Полное разделение `obligatory` vs `conditional`** в pydantic-валидации
  (вариант B из штурма D1) — включаем, если через месяц AckAudit покажет
  массовые silent-reject по conditional.
