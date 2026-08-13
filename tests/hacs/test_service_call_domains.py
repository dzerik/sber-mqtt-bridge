"""Домен HA-сервиса берётся из самой сущности, а не зашит в класс устройства (issue #33).

Каждый класс устройства строит вызовы вида ``{"url": {"domain": ..., "service": ...}}``,
которые ``SberCommandDispatcher`` отдаёт в ``hass.services.async_call``.  Домен в
этом вызове обязан совпадать с доменом ``entity_id`` — иначе:

* пользователь, назначивший категорию вручную (``set_override`` минует проверку
  ``CategorySpec.matches``), получает ``ServiceNotFound`` на КАЖДУЮ команду Sber —
  устройство «есть», но не управляется;
* штатные несовпадения домена и категории ломаются молча: ``hvac_boiler``
  наследует ``ClimateEntity``, но живёт в домене ``water_heater``, а ``intercom``
  и ``kettle`` зарегистрированы сразу на два домена.

Файл проверяет обе стороны инварианта:

1. **защита от регресса** — сущность своего (штатного) домена порождает РОВНО
   прежние вызовы: полные словари, а не «содержит»;
2. **issue #33** — та же категория, назначенная сущности чужого домена,
   порождает вызовы в СВОЁМ домене (или не порождает ни одного, если сервиса
   для этого домена быть не может — см. импульсные ворота);
3. **общий инвариант** — параметризация идёт по ``CATEGORY_DOMAIN_MAP``, поэтому
   новый класс устройства попадает под проверку автоматически, а не только
   сегодняшние семь файлов;
4. **часовой** — AST-скан ``devices/`` падает при появлении нового литерального
   домена в аргументах ``_build_service_call`` / ``_build_on_off_service_call``.

Ожидания выведены из протокола Sber (`open_set`, `hvac_*`, `vacuum_cleaner_*`),
из состава сервисов соответствующих HA-платформ и из формулировки issue #33 —
не из текущего вывода кода.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from custom_components.sber_mqtt_bridge.sber_constants import SERVICE_CALL_TYPE
from custom_components.sber_mqtt_bridge.sber_entity_map import (
    CATEGORY_DOMAIN_MAP,
    create_sber_entity,
)

CALL_SERVICE = "call_service"
"""Литерал типа команды «вызвать сервис HA» в ``CommandResult``.

Зафиксирован здесь строкой намеренно: тест описывает контракт протокола, а не
пересказывает константу модуля.  Совпадение с продовой константой проверяет
:func:`test_call_service_marker_matches_production_constant`."""

UPDATE_STATE: dict = {"update_state": True}
"""Подтверждение команды републикацией состояния — вместо сервисного вызова."""

DEVICES_DIR = Path(__file__).resolve().parents[2] / "custom_components" / "sber_mqtt_bridge" / "devices"
"""Каталог классов устройств — область действия теста-часового."""


# ---------------------------------------------------------------------------
#  Модель проб
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Expect:
    """Один ожидаемый элемент результата ``process_cmd``.

    Attributes:
        service: Имя HA-сервиса без домена (``turn_on``, ``set_cover_position``).
            ``None`` — ожидается подтверждение :data:`UPDATE_STATE` без вызова.
        data: Ожидаемый ``service_data``; ``None`` — ключа быть не должно.
    """

    service: str | None = None
    data: dict | None = None


ACK = Expect()
"""Ожидание «команда подтверждена републикацией, сервис не вызван»."""


@dataclass(frozen=True)
class Cmd:
    """Одна Sber-команда и то, что она обязана породить.

    Attributes:
        key: Ключ фичи Sber (``on_off``, ``open_set``, ...).
        value: Значение команды в формате протокола Sber.
        native: Ожидание для сущности штатного домена категории.
        alien: Ожидание для сущности чужого домена.  ``None`` — «те же самые
            сервисы с теми же данными, но в своём (чужом для категории)
            домене»: базовый случай issue #33.
        label: Суффикс идентификатора теста, когда один ключ проверяется
            несколькими значениями.
    """

    key: str
    value: dict
    native: tuple[Expect, ...]
    alien: tuple[Expect, ...] | None = None
    label: str = ""


@dataclass(frozen=True)
class Probe:
    """Категория Sber на паре сущностей: своего домена и чужого.

    Attributes:
        category: Ключ :data:`CATEGORY_DOMAIN_MAP`.
        native_entity_id: entity_id домена, штатного для категории.
        alien_entity_id: entity_id домена, которого нет в ``spec.domains``
            (то, что даёт ручной ``set_override``).
        cmds: Проверяемые команды.
        ha_state: HA-состояние, применяемое к обеим сущностям перед командой.
        label: Идентификатор пробы в отчёте pytest.
    """

    category: str
    native_entity_id: str
    alien_entity_id: str
    cmds: tuple[Cmd, ...]
    ha_state: dict | None = None
    label: str = ""

    @property
    def name(self) -> str:
        """Человекочитаемое имя пробы для ids параметризации."""
        return self.label or self.category


def _call(domain: str, service: str, entity_id: str, data: dict | None) -> dict:
    """Собрать ожидаемый сервисный вызов в формате ``CommandResult``.

    Args:
        domain: HA-домен сервиса.
        service: Имя сервиса.
        entity_id: Целевая сущность.
        data: ``service_data`` или ``None``, если данных быть не должно.

    Returns:
        Полный ожидаемый словарь результата.
    """
    url: dict = {
        "type": CALL_SERVICE,
        "domain": domain,
        "service": service,
        "target": {"entity_id": entity_id},
    }
    if data is not None:
        url["service_data"] = data
    return {"url": url}


def _render(expects: tuple[Expect, ...], domain: str, entity_id: str) -> list[dict]:
    """Развернуть ожидания в список результатов ``process_cmd``.

    Args:
        expects: Ожидания в порядке их появления в ответе.
        domain: Домен, в котором обязаны быть вызовы.
        entity_id: Целевая сущность.

    Returns:
        Список словарей, с которым сравнивается результат.
    """
    rendered: list[dict] = []
    for exp in expects:
        if exp.service is None:
            rendered.append(dict(UPDATE_STATE))
        else:
            rendered.append(_call(domain, exp.service, entity_id, exp.data))
    return rendered


def _build(category: str, entity_id: str, ha_state: dict | None):
    """Создать сущность продовым путём ручного назначения категории.

    Ровно этот путь исполняет ``set_override``: категория задана явно и
    подменяет доменное автоопределение.

    Args:
        category: Категория Sber.
        entity_id: entity_id первичной HA-сущности.
        ha_state: HA-состояние или ``None``.

    Returns:
        Готовая к приёму команд сущность.
    """
    entity = create_sber_entity(entity_id, {"entity_id": entity_id, "name": "Probe"}, sber_category=category)
    assert entity is not None, f"категория {category!r} не построила сущность для {entity_id}"
    if ha_state is not None:
        entity.fill_by_ha_state({"entity_id": entity_id, **ha_state})
    return entity


# ---------------------------------------------------------------------------
#  Наборы команд, общие для классов-родственников
# ---------------------------------------------------------------------------

LIGHT_STATE: dict = {
    "state": "on",
    "attributes": {
        "brightness": 128,
        "supported_color_modes": ["hs"],
        "color_mode": "hs",
        "hs_color": [30, 80],
    },
}
"""RGB-лампа без CCT: делает ветку ``light_mode=white`` детерминированной."""

LIGHT_CMDS: tuple[Cmd, ...] = (
    Cmd("on_off", {"type": "BOOL", "bool_value": True}, (Expect("turn_on"),), label="on"),
    Cmd("on_off", {"type": "BOOL", "bool_value": False}, (Expect("turn_off"),), label="off"),
    # Sber-яркость 100..900 линейно ложится на HA 0..255: верхняя граница → 255.
    Cmd(
        "light_brightness",
        {"type": "INTEGER", "integer_value": 900},
        (Expect("turn_on", {"brightness": 255}),),
    ),
    # HSV Sber (H 0..360, S 0..1000, V 100..1000) → HA (H 0..360, S 0..100, V 0..255).
    Cmd(
        "light_colour",
        {"type": "COLOUR", "colour_value": {"h": 120, "s": 1000, "v": 1000}},
        (Expect("turn_on", {"hs_color": [120, 100], "brightness": 255}),),
    ),
    Cmd(
        "light_mode",
        {"type": "ENUM", "enum_value": "colour"},
        (Expect("turn_on", {"hs_color": [30, 80]}),),
        label="colour",
    ),
    # «Белый» на RGB-лампе без CCT — это обесцвечивание, а не цветовая температура.
    Cmd(
        "light_mode",
        {"type": "ENUM", "enum_value": "white"},
        (Expect("turn_on", {"hs_color": [0, 0]}),),
        label="white",
    ),
    # Обратная шкала: Sber 0 → верхняя граница миредов (500) → 2000 K.
    Cmd(
        "light_colour_temp",
        {"type": "INTEGER", "integer_value": 0},
        (Expect("turn_on", {"color_temp_kelvin": 2000}),),
    ),
)
"""Команды светильника: все ключи ``_cmd_handlers`` LightEntity."""

COVER_CMDS: tuple[Cmd, ...] = (
    Cmd(
        "open_percentage",
        {"type": "INTEGER", "integer_value": 40},
        (Expect("set_cover_position", {"position": 40}),),
    ),
    Cmd(
        "cover_position",
        {"type": "INTEGER", "integer_value": 40},
        (Expect("set_cover_position", {"position": 40}),),
    ),
    Cmd("open_set", {"type": "ENUM", "enum_value": "open"}, (Expect("open_cover"),), label="open"),
    Cmd("open_set", {"type": "ENUM", "enum_value": "close"}, (Expect("close_cover"),), label="close"),
    Cmd("open_set", {"type": "ENUM", "enum_value": "stop"}, (Expect("stop_cover"),), label="stop"),
)
"""Команды штор/жалюзи/ворот-cover: позиция и open/close/stop."""

CLIMATE_STATE: dict = {
    "state": "cool",
    "attributes": {
        "current_temperature": 21,
        "temperature": 23,
        "fan_modes": ["low", "medium", "high", "auto"],
        "fan_mode": "low",
        "swing_modes": ["off", "vertical", "both"],
        "swing_mode": "off",
        "hvac_modes": ["off", "cool", "heat", "dry", "fan_only", "auto"],
        "preset_modes": ["none", "boost", "sleep", "eco"],
        "preset_mode": "none",
        "humidity": 45,
    },
}
"""Полнофункциональный термостат: включает все восемь обработчиков ClimateEntity."""

CLIMATE_CMDS: tuple[Cmd, ...] = (
    Cmd("on_off", {"type": "BOOL", "bool_value": True}, (Expect("turn_on"),), label="on"),
    Cmd("on_off", {"type": "BOOL", "bool_value": False}, (Expect("turn_off"),), label="off"),
    Cmd(
        "hvac_temp_set",
        {"type": "INTEGER", "integer_value": 24},
        (Expect("set_temperature", {"temperature": 24.0}),),
    ),
    Cmd(
        "hvac_air_flow_power",
        {"type": "ENUM", "enum_value": "medium"},
        (Expect("set_fan_mode", {"fan_mode": "medium"}),),
    ),
    Cmd(
        "hvac_air_flow_direction",
        {"type": "ENUM", "enum_value": "vertical"},
        (Expect("set_swing_mode", {"swing_mode": "vertical"}),),
    ),
    # Sber-режимы работы — не HA-имена: heating → heat.
    Cmd(
        "hvac_work_mode",
        {"type": "ENUM", "enum_value": "heating"},
        (Expect("set_hvac_mode", {"hvac_mode": "heat"}),),
        label="heating",
    ),
    # turbo/quiet у Sber — это пресеты HA, а не hvac_mode.
    Cmd(
        "hvac_work_mode",
        {"type": "ENUM", "enum_value": "turbo"},
        (Expect("set_preset_mode", {"preset_mode": "boost"}),),
        label="turbo",
    ),
    Cmd(
        "hvac_thermostat_mode",
        {"type": "ENUM", "enum_value": "heating"},
        (Expect("set_hvac_mode", {"hvac_mode": "heat"}),),
    ),
    Cmd(
        "hvac_humidity_set",
        {"type": "INTEGER", "integer_value": 55},
        (Expect("set_humidity", {"humidity": 55}),),
    ),
    Cmd(
        "hvac_night_mode",
        {"type": "BOOL", "bool_value": True},
        (Expect("set_preset_mode", {"preset_mode": "sleep"}),),
        label="on",
    ),
    Cmd(
        "hvac_night_mode",
        {"type": "BOOL", "bool_value": False},
        (Expect("set_preset_mode", {"preset_mode": "none"}),),
        label="off",
    ),
)
"""Команды климатики: все восемь ключей ``_cmd_handlers`` ClimateEntity."""

FAN_STATE: dict = {
    "state": "on",
    "attributes": {
        "preset_modes": ["low", "high"],
        "preset_mode": "low",
        "percentage": 50,
        "supported_features": 1,
    },
}
"""Вентилятор с пресетами low/high: остальные скорости уходят в проценты."""

FAN_CMDS: tuple[Cmd, ...] = (
    Cmd("on_off", {"type": "BOOL", "bool_value": True}, (Expect("turn_on"),), label="on"),
    Cmd("on_off", {"type": "BOOL", "bool_value": False}, (Expect("turn_off"),), label="off"),
    Cmd(
        "hvac_air_flow_power",
        {"type": "ENUM", "enum_value": "low"},
        (Expect("set_preset_mode", {"preset_mode": "low"}),),
        label="preset",
    ),
    Cmd(
        "hvac_air_flow_power",
        {"type": "ENUM", "enum_value": "medium"},
        (Expect("set_percentage", {"percentage": 50}),),
        label="percentage",
    ),
    Cmd(
        "hvac_air_flow_power",
        {"type": "ENUM", "enum_value": "auto"},
        (Expect("turn_on"),),
        label="auto",
    ),
)
"""Команды вентилятора / очистителя: общий FanSpeedMixin."""

ON_OFF_CMDS: tuple[Cmd, ...] = (
    Cmd("on_off", {"type": "BOOL", "bool_value": True}, (Expect("turn_on"),), label="on"),
    Cmd("on_off", {"type": "BOOL", "bool_value": False}, (Expect("turn_off"),), label="off"),
)
"""Команды простого реле/розетки."""

PRESS_CMDS: tuple[Cmd, ...] = (
    # У кнопки нет «выключить»: оба направления дают один и тот же импульс.
    Cmd(
        "on_off",
        {"type": "BOOL", "bool_value": True},
        (Expect("press"),),
        alien=(Expect("turn_on"),),
        label="on",
    ),
    Cmd(
        "on_off",
        {"type": "BOOL", "bool_value": False},
        (Expect("press"),),
        alien=(Expect("turn_off"),),
        label="off",
    ),
)
"""Команды реле, назначенного на HA ``button``."""


def _impulse_cmds(service: str) -> tuple[Cmd, ...]:
    """Собрать команды импульсных ворот для домена с известным импульсом.

    Args:
        service: Сервис импульса в штатном домене (``toggle`` / ``press`` /
            ``turn_on``).

    Returns:
        Набор команд ``open_set``; в чужом домене импульса быть не может,
        поэтому там ожидается пустой результат, а не выдуманный вызов.
    """
    return (
        Cmd("open_set", {"type": "ENUM", "enum_value": "open"}, (Expect(service),), alien=(), label="open"),
        Cmd("open_set", {"type": "ENUM", "enum_value": "close"}, (Expect(service),), alien=(), label="close"),
        # ``stop`` не объявлен в allowed_values — одна кнопка не умеет останавливать створку.
        Cmd("open_set", {"type": "ENUM", "enum_value": "stop"}, (), alien=(), label="stop"),
    )


# ---------------------------------------------------------------------------
#  Таблица проб
# ---------------------------------------------------------------------------

PROBES: tuple[Probe, ...] = (
    Probe("light", "light.hall", "switch.hall", LIGHT_CMDS, LIGHT_STATE),
    Probe("led_strip", "light.strip", "switch.strip", LIGHT_CMDS, LIGHT_STATE),
    Probe("relay", "switch.pump", "light.pump", ON_OFF_CMDS, label="relay-switch"),
    Probe("relay", "script.pump", "light.pump", ON_OFF_CMDS, label="relay-script"),
    Probe("relay", "button.pump", "light.pump", PRESS_CMDS, label="relay-button"),
    Probe("socket", "switch.outlet", "light.outlet", ON_OFF_CMDS),
    Probe("curtain", "cover.curtain", "switch.curtain", COVER_CMDS),
    Probe("window_blind", "cover.blind", "switch.blind", COVER_CMDS),
    # Ворота-cover: в чужом домене фабрика отдаёт импульсную реализацию,
    # у которой ни позиции, ни импульса для light быть не может.
    Probe(
        "gate",
        "cover.gate",
        "light.gate",
        tuple(Cmd(c.key, c.value, c.native, alien=(), label=c.label) for c in COVER_CMDS),
        label="gate-cover",
    ),
    Probe("gate", "switch.gate", "light.gate", _impulse_cmds("toggle"), label="gate-switch"),
    Probe("gate", "button.gate", "light.gate", _impulse_cmds("press"), label="gate-button"),
    Probe("gate", "script.gate", "light.gate", _impulse_cmds("turn_on"), label="gate-script"),
    Probe("hvac_ac", "climate.ac", "switch.ac", CLIMATE_CMDS, CLIMATE_STATE),
    Probe("hvac_radiator", "climate.radiator", "switch.radiator", CLIMATE_CMDS, CLIMATE_STATE),
    Probe("hvac_heater", "climate.heater", "switch.heater", CLIMATE_CMDS, CLIMATE_STATE),
    Probe(
        "hvac_underfloor_heating",
        "climate.floor",
        "switch.floor",
        CLIMATE_CMDS,
        CLIMATE_STATE,
    ),
    # Бойлер — штатный «несовпадающий» случай: класс климатический, домен water_heater.
    Probe("hvac_boiler", "water_heater.boiler", "switch.boiler", CLIMATE_CMDS, CLIMATE_STATE),
    Probe("hvac_fan", "fan.vent", "switch.vent", FAN_CMDS, FAN_STATE),
    Probe("hvac_air_purifier", "fan.purifier", "switch.purifier", FAN_CMDS, FAN_STATE),
    Probe(
        "hvac_humidifier",
        "humidifier.air",
        "switch.air",
        (
            Cmd("on_off", {"type": "BOOL", "bool_value": True}, (Expect("turn_on"),), label="on"),
            Cmd("on_off", {"type": "BOOL", "bool_value": False}, (Expect("turn_off"),), label="off"),
            Cmd(
                "humidity",
                {"type": "INTEGER", "integer_value": 55},
                (Expect("set_humidity", {"humidity": 55}),),
            ),
            Cmd(
                "hvac_humidity_set",
                {"type": "INTEGER", "integer_value": 60},
                (Expect("set_humidity", {"humidity": 60}),),
            ),
            # Sber medium ← HA normal (по таблице HA_TO_SBER_HUMIDIFIER_MODE).
            Cmd(
                "hvac_air_flow_power",
                {"type": "ENUM", "enum_value": "medium"},
                (Expect("set_mode", {"mode": "normal"}),),
            ),
            Cmd(
                "hvac_work_mode",
                {"type": "ENUM", "enum_value": "quiet"},
                (Expect("set_mode", {"mode": "sleep"}),),
            ),
            Cmd(
                "hvac_night_mode",
                {"type": "BOOL", "bool_value": True},
                (Expect("set_mode", {"mode": "sleep"}),),
                label="on",
            ),
            Cmd(
                "hvac_night_mode",
                {"type": "BOOL", "bool_value": False},
                (Expect("set_mode", {"mode": "normal"}),),
                label="off",
            ),
        ),
        {"state": "on", "attributes": {"available_modes": ["normal", "sleep", "boost"], "mode": "normal"}},
    ),
    Probe(
        "valve",
        "valve.water",
        "switch.water",
        (
            Cmd("open_set", {"type": "ENUM", "enum_value": "open"}, (Expect("open_valve"),), label="open"),
            Cmd("open_set", {"type": "ENUM", "enum_value": "close"}, (Expect("close_valve"),), label="close"),
            Cmd("open_set", {"type": "ENUM", "enum_value": "stop"}, (Expect("stop_valve"),), label="stop"),
        ),
    ),
    Probe(
        "kettle",
        "water_heater.kettle",
        "light.kettle",
        (
            Cmd("on_off", {"type": "BOOL", "bool_value": True}, (Expect("turn_on"),), label="on"),
            Cmd("on_off", {"type": "BOOL", "bool_value": False}, (Expect("turn_off"),), label="off"),
            Cmd(
                "kitchen_water_temperature_set",
                {"type": "INTEGER", "integer_value": 80},
                (Expect("set_temperature", {"temperature": 80}),),
            ),
        ),
        label="kettle-water_heater",
    ),
    Probe(
        "kettle",
        "switch.kettle",
        "light.kettle",
        (Cmd("on_off", {"type": "BOOL", "bool_value": True}, (Expect("turn_on"),), label="on"),),
        label="kettle-switch",
    ),
    Probe(
        "tv",
        "media_player.tv",
        "switch.tv",
        (
            Cmd("on_off", {"type": "BOOL", "bool_value": True}, (Expect("turn_on"),), label="on"),
            Cmd("on_off", {"type": "BOOL", "bool_value": False}, (Expect("turn_off"),), label="off"),
            # Sber отдаёт громкость в процентах, HA ждёт долю единицы.
            Cmd(
                "volume_int",
                {"type": "INTEGER", "integer_value": 40},
                (Expect("volume_set", {"volume_level": 0.4}),),
            ),
            Cmd(
                "mute",
                {"type": "BOOL", "bool_value": True},
                (Expect("volume_mute", {"is_volume_muted": True}),),
            ),
            Cmd(
                "source",
                {"type": "ENUM", "enum_value": "HDMI1"},
                (Expect("select_source", {"source": "HDMI1"}),),
            ),
            Cmd(
                "channel_int",
                {"type": "INTEGER", "integer_value": 5},
                (Expect("play_media", {"media_content_type": "channel", "media_content_id": "5"}),),
            ),
            Cmd(
                "number",
                {"type": "INTEGER", "integer_value": 7},
                (Expect("play_media", {"media_content_type": "channel", "media_content_id": "7"}),),
            ),
            Cmd("channel", {"type": "ENUM", "enum_value": "+"}, (Expect("media_next_track"),)),
            Cmd("volume", {"type": "ENUM", "enum_value": "-"}, (Expect("volume_down"),)),
            Cmd("direction", {"type": "ENUM", "enum_value": "ok"}, (Expect("media_play_pause"),)),
            Cmd("custom_key", {"type": "ENUM", "enum_value": "play"}, (Expect("media_play"),)),
        ),
    ),
    Probe(
        "vacuum_cleaner",
        "vacuum.robot",
        "switch.robot",
        (
            Cmd(
                "vacuum_cleaner_command",
                {"type": "ENUM", "enum_value": "start"},
                (Expect("start"),),
                label="start",
            ),
            Cmd(
                "vacuum_cleaner_command",
                {"type": "ENUM", "enum_value": "pause"},
                (Expect("pause"),),
                label="pause",
            ),
            Cmd(
                "vacuum_cleaner_command",
                {"type": "ENUM", "enum_value": "return_to_dock"},
                (Expect("return_to_base"),),
                label="dock",
            ),
            Cmd(
                "vacuum_cleaner_program",
                {"type": "ENUM", "enum_value": "turbo"},
                (Expect("set_fan_speed", {"fan_speed": "turbo"}),),
            ),
        ),
    ),
    Probe(
        "intercom",
        "lock.door",
        "light.door",
        (
            Cmd("on_off", {"type": "BOOL", "bool_value": True}, (Expect("turn_on"),), label="on"),
            Cmd("on_off", {"type": "BOOL", "bool_value": False}, (Expect("turn_off"),), label="off"),
            # У HA-замка своя команда открытия; в любом другом домене её нет.
            Cmd(
                "unlock",
                {"type": "ENUM", "enum_value": "unlock"},
                (Expect("unlock"),),
                alien=(Expect("turn_on"),),
            ),
            # reject_call не имеет аналога в HA — подтверждается републикацией.
            Cmd("reject_call", {"type": "ENUM", "enum_value": "reject"}, (ACK,), alien=(ACK,)),
        ),
        label="intercom-lock",
    ),
    Probe(
        "intercom",
        "switch.door",
        "light.door",
        (
            Cmd("on_off", {"type": "BOOL", "bool_value": True}, (Expect("turn_on"),), label="on"),
            Cmd("unlock", {"type": "ENUM", "enum_value": "unlock"}, (Expect("turn_on"),)),
        ),
        label="intercom-switch",
    ),
)
"""Полная таблица проб: категория × команда × ожидаемые вызовы."""


def _cases(alien: bool) -> tuple[list[tuple[Probe, Cmd]], list[str]]:
    """Развернуть :data:`PROBES` в параметры pytest.

    Args:
        alien: ``True`` — случаи чужого домена, ``False`` — штатного.

    Returns:
        Пара «список параметров, список идентификаторов».
    """
    params: list[tuple[Probe, Cmd]] = []
    ids: list[str] = []
    for probe in PROBES:
        for cmd in probe.cmds:
            params.append((probe, cmd))
            suffix = f"-{cmd.label}" if cmd.label else ""
            side = probe.alien_entity_id.split(".", 1)[0] if alien else probe.native_entity_id.split(".", 1)[0]
            ids.append(f"{probe.name}-{side}-{cmd.key}{suffix}")
    return params, ids


_NATIVE_PARAMS, _NATIVE_IDS = _cases(alien=False)
_ALIEN_PARAMS, _ALIEN_IDS = _cases(alien=True)


# ---------------------------------------------------------------------------
#  1. Защита от регресса: штатный домен
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("probe", "cmd"), _NATIVE_PARAMS, ids=_NATIVE_IDS)
def test_native_domain_calls_are_exact(probe: Probe, cmd: Cmd):
    """Сущность штатного домена порождает РОВНО прежние вызовы.

    Сравнивается полный список результатов, а не «содержит»: лишний вызов —
    это второе нажатие на реле, недостающий ``service_data`` — потерянная
    яркость/температура, а иной порядок ломает атомарность команды.
    """
    entity = _build(probe.category, probe.native_entity_id, probe.ha_state)
    domain = probe.native_entity_id.split(".", 1)[0]

    result = entity.process_cmd({"states": [{"key": cmd.key, "value": cmd.value}]})

    assert result == _render(cmd.native, domain, probe.native_entity_id)


# ---------------------------------------------------------------------------
#  2. Issue #33: чужой домен
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("probe", "cmd"), _ALIEN_PARAMS, ids=_ALIEN_IDS)
def test_overridden_entity_calls_its_own_domain(probe: Probe, cmd: Cmd):
    """Категория, назначенная сущности чужого домена, вызывает СВОЙ домен.

    ``set_override`` минует проверку совместимости, поэтому в проде такое
    сочетание достижимо одним кликом.  Вызов в домене категории (``light.*``
    для реле, ``climate.*`` для бойлера) гарантированно даёт
    ``ServiceNotFound`` — команда Sber исполняется вникуда.
    """
    entity = _build(probe.category, probe.alien_entity_id, probe.ha_state)
    domain = probe.alien_entity_id.split(".", 1)[0]
    expected_spec = cmd.native if cmd.alien is None else cmd.alien

    result = entity.process_cmd({"states": [{"key": cmd.key, "value": cmd.value}]})

    assert result == _render(expected_spec, domain, probe.alien_entity_id)


# ---------------------------------------------------------------------------
#  3. Полнота таблицы относительно CATEGORY_DOMAIN_MAP
# ---------------------------------------------------------------------------


def _handler_keys(category: str) -> set[str]:
    """Собрать все командные ключи категории по всем её штатным доменам.

    Одна категория может строить разные классы (``gate`` — ``GateEntity``
    для ``cover`` и ``ImpulseGateEntity`` для реле), поэтому ключи
    объединяются по всем доменам из ``CategorySpec.domains``.

    Args:
        category: Категория Sber.

    Returns:
        Множество ключей фич, которые категория умеет исполнять.
    """
    keys: set[str] = set()
    for domain in CATEGORY_DOMAIN_MAP[category].domains:
        entity = _build(category, f"{domain}.probe", None)
        keys |= set(entity._cmd_handlers)
    return keys


COMMANDING_CATEGORIES: frozenset[str] = frozenset(c for c in CATEGORY_DOMAIN_MAP if _handler_keys(c))
"""Категории, которые вообще строят сервисные вызовы (не read-only сенсоры)."""


def test_every_commanding_category_is_probed():
    """Каждая исполняющая команды категория карты присутствует в таблице проб.

    Новый класс устройства обязан прийти вместе с проверкой домена — иначе
    issue #33 воспроизведётся в следующей же категории.
    """
    probed = {probe.category for probe in PROBES}

    assert probed == set(COMMANDING_CATEGORIES)


@pytest.mark.parametrize("category", sorted(COMMANDING_CATEGORIES))
def test_every_command_key_of_category_is_probed(category: str):
    """Для категории покрыт каждый ключ ``_cmd_handlers``, и лишних ключей нет.

    Непокрытый ключ — это команда Sber, чей домен никто не проверяет;
    ключ в таблице, которого нет в обработчиках, — мёртвая проба, молча
    возвращающая пустой список.
    """
    probed = {cmd.key for probe in PROBES if probe.category == category for cmd in probe.cmds}

    assert probed == _handler_keys(category)


def test_probe_domains_match_category_map():
    """Штатный домен пробы объявлен в карте, чужой — заведомо нет.

    Иначе «чужой» случай перестанет быть чужим, и тест issue #33 выродится
    в дубликат регрессионного.
    """
    for probe in PROBES:
        domains = CATEGORY_DOMAIN_MAP[probe.category].domains
        native = probe.native_entity_id.split(".", 1)[0]
        alien = probe.alien_entity_id.split(".", 1)[0]
        assert native in domains, f"{probe.name}: {native} не объявлен для категории {probe.category}"
        assert alien not in domains, f"{probe.name}: {alien} объявлен для категории {probe.category}"


def test_call_service_marker_matches_production_constant():
    """Литерал типа вызова в тесте совпадает с константой протокола."""
    assert CALL_SERVICE == SERVICE_CALL_TYPE


# ---------------------------------------------------------------------------
#  4. Общий инвариант: домен вызова == домен сущности
# ---------------------------------------------------------------------------

FOREIGN_DOMAINS: tuple[str, ...] = ("switch", "light", "cover", "media_player", "water_heater", "sensor")
"""Домены, под которые сущность может быть выставлена вручную."""

GENERIC_VALUES: tuple[dict, ...] = (
    {"type": "BOOL", "bool_value": True},
    {"type": "BOOL", "bool_value": False},
    {"type": "INTEGER", "integer_value": 50},
    {"type": "COLOUR", "colour_value": {"h": 120, "s": 500, "v": 500}},
    *(
        {"type": "ENUM", "enum_value": v}
        for v in (
            "open",
            "close",
            "stop",
            "auto",
            "quiet",
            "low",
            "medium",
            "high",
            "turbo",
            "cooling",
            "heating",
            "ventilation",
            "vertical",
            "colour",
            "white",
            "start",
            "pause",
            "return_to_dock",
            "unlock",
            "reject",
            "play",
            "ok",
            "+",
            "-",
            "HDMI1",
        )
    ),
)
"""Корпус значений, покрывающий все типы Sber и ходовые ENUM-значения."""


@pytest.mark.parametrize("category", sorted(COMMANDING_CATEGORIES))
def test_no_handler_ever_targets_a_foreign_domain(category: str):
    """Ни один обработчик категории не адресует вызов чужому домену.

    Проверка идёт по карте категорий и корпусу значений, а не по списку
    известных классов: класс, добавленный завтра, попадёт сюда сам.
    """
    spec = CATEGORY_DOMAIN_MAP[category]
    offenders: list[str] = []
    for domain in dict.fromkeys((*spec.domains, *FOREIGN_DOMAINS)):
        entity_id = f"{domain}.probe"
        entity = _build(category, entity_id, None)
        for key in _handler_keys(category):
            for value in GENERIC_VALUES:
                for item in entity.process_cmd({"states": [{"key": key, "value": value}]}):
                    url = item.get("url")
                    if url is not None and url["domain"] != domain:
                        offenders.append(f"{entity_id} + {key}={value.get('enum_value', value['type'])} → {url}")

    assert offenders == [], f"категория {category} зовёт чужой домен:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
#  5. Часовой: литеральные домены в devices/
# ---------------------------------------------------------------------------

BUILDER_DOMAIN_ARG: dict[str, int] = {
    "_build_service_call": 0,
    "_build_on_off_service_call": 1,
}
"""Позиция аргумента ``domain`` у конструкторов сервисного вызова."""

ALLOWED_LITERAL_DOMAINS: frozenset[tuple[str, str, str]] = frozenset(
    {
        # Достижимо только внутри ветки ``domain == "lock"``, то есть равно
        # get_entity_domain() по построению; литерал держит имя сервиса
        # ``lock.unlock`` рядом с его доменом.
        ("intercom.py", "_cmd_unlock", "lock"),
    }
)
"""Осознанные исключения: (файл, функция, литеральный домен)."""


@dataclass
class _ModuleScan:
    """Результат разбора одного модуля устройств.

    Attributes:
        consts: Строковые константы уровня модуля.
        found: Найденные литеральные домены.
    """

    consts: dict[str, str] = field(default_factory=dict)
    found: set[tuple[str, str, str]] = field(default_factory=set)


def _string_consts(body: list[ast.stmt]) -> dict[str, str]:
    """Собрать присваивания строковых литералов простым именам.

    Args:
        body: Список инструкций (тело модуля или функции).

    Returns:
        Отображение «имя → строковое значение».
    """
    consts: dict[str, str] = {}
    for node in body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    consts[target.id] = node.value.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            consts[node.target.id] = node.value.value
    return consts


def _literal_domain(arg: ast.expr, scopes: tuple[dict[str, str], ...]) -> str | None:
    """Вернуть домен, если аргумент — строковый литерал (в т.ч. через константу).

    Args:
        arg: Узел аргумента ``domain``.
        scopes: Словари строковых констант от локального к модульному.

    Returns:
        Значение литерала или ``None``, если домен вычисляется динамически.
    """
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.Name):
        for scope in scopes:
            if arg.id in scope:
                return scope[arg.id]
    return None


def _scan_module(path: Path) -> set[tuple[str, str, str]]:
    """Найти в модуле сервисные вызовы с литеральным доменом.

    Args:
        path: Путь к файлу устройства.

    Returns:
        Множество кортежей (имя файла, имя функции, литерал домена).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    scan = _ModuleScan(consts=_string_consts(tree.body))
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef):
            scan.consts.update(_string_consts(cls.body))

    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    for func in functions:
        local = _string_consts(func.body)
        for node in ast.walk(func):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            index = BUILDER_DOMAIN_ARG.get(node.func.attr)
            if index is None:
                continue
            arg: ast.expr | None = None
            for kw in node.keywords:
                if kw.arg == "domain":
                    arg = kw.value
            if arg is None and len(node.args) > index:
                arg = node.args[index]
            if arg is None:
                continue
            literal = _literal_domain(arg, (local, scan.consts))
            if literal is not None:
                scan.found.add((path.name, func.name, literal))
    return scan.found


def test_devices_never_hardcode_the_service_domain():
    """В ``devices/`` нет литеральных доменов, кроме осознанных исключений.

    Часовой держит issue #33 закрытым: любой новый ``_build_service_call("light", ...)``
    ломает сборку сразу, а не через отчёт пользователя, у которого сущность
    другого домена молча перестала управляться.
    """
    found: set[tuple[str, str, str]] = set()
    for path in sorted(DEVICES_DIR.glob("*.py")):
        found |= _scan_module(path)

    unexpected = sorted(found - ALLOWED_LITERAL_DOMAINS)
    stale = sorted(ALLOWED_LITERAL_DOMAINS - found)

    assert not unexpected, f"новые захардкоженные домены: {unexpected}"
    assert not stale, f"исключение больше не встречается — удалите его из списка: {stale}"


def test_sentinel_detects_a_planted_hardcoded_domain(tmp_path: Path):
    """Сам часовой ловит и прямой литерал, и литерал через константу модуля.

    Без этой проверки молчание часового невозможно отличить от чистого кода.
    """
    module = tmp_path / "planted.py"
    module.write_text(
        "_DOMAIN = 'media_player'\n"
        "class X:\n"
        "    def a(self):\n"
        "        return self._build_service_call('light', 'turn_on', self.entity_id)\n"
        "    def b(self):\n"
        "        return self._build_on_off_service_call(self.entity_id, _DOMAIN, True)\n"
        "    def c(self):\n"
        "        return self._build_service_call(self.get_entity_domain(), 'turn_on', self.entity_id)\n"
        "    def d(self):\n"
        "        domain = self.entity_id.split('.', 1)[0]\n"
        "        return self._build_service_call(domain, 'turn_on', self.entity_id)\n",
        encoding="utf-8",
    )

    assert _scan_module(module) == {
        ("planted.py", "a", "light"),
        ("planted.py", "b", "media_player"),
    }
