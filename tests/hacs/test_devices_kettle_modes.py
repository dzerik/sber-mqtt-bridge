"""Жёсткие тесты режимов работы чайника (:mod:`devices.kettle`).

Проверяется контракт, заданный ТЗ, а не текущий вывод кода:

* домен ``switch`` и сущность без ``operation_list`` обязаны работать
  ровно так, как до появления режимов (``turn_on`` / ``turn_off`` /
  ``set_temperature``);
* режимы автоопределяются из ``operation_list`` без учёта регистра,
  ручной выбор пользователя важнее автоопределения;
* режим не из списка сущности отвергается валидацией;
* полная матрица команд ``on_off`` × температура даёт точную
  ПОСЛЕДОВАТЕЛЬНОСТЬ сервисных вызовов;
* набор фич, ``allowed_values`` и дайджест модели не изменились —
  иначе у существующих пользователей сменится ``model.id`` и Sber
  заведёт новую модель устройства.

Каждый тест сравнивает результат с литералами, собранными здесь же, а не
с тем, что вернули хелперы продакшн-кода, — иначе ошибка в форме
сервисного вызова осталась бы незамеченной.
"""

from __future__ import annotations

import logging

import pytest

from custom_components.sber_mqtt_bridge.devices.kettle import (
    KETTLE_TEMPERATURE_MAX,
    KETTLE_TEMPERATURE_MIN,
    KETTLE_TEMPERATURE_STEP,
    KettleEntity,
)

KETTLE_LOGGER = "custom_components.sber_mqtt_bridge.devices.kettle"
"""Имя логгера модуля чайника — по нему фильтруются WARNING в тестах."""

WATER_HEATER_ID = "water_heater.kettle"
"""Идентификатор «умного» чайника (домен с ``set_operation_mode``)."""

SWITCH_ID = "switch.kettle"
"""Идентификатор «глупого» чайника в розетке (домен без режимов)."""

EXPECTED_FEATURES = [
    "online",
    "on_off",
    "kitchen_water_temperature",
    "kitchen_water_temperature_set",
    "kitchen_water_level",
    "kitchen_water_low_level",
    "child_lock",
]
"""Полный список фич Sber-категории ``kettle`` — заморожен."""

EXPECTED_ALLOWED_VALUES = {
    "kitchen_water_temperature_set": {
        "type": "INTEGER",
        "integer_values": {"min": "60", "max": "100", "step": "10"},
    }
}
"""Полный ``allowed_values`` категории ``kettle`` — заморожен."""

EXPECTED_MODEL_ID = "Mdl_kettle_3f117f51"
"""``model.id`` чайника без привязанного HA-устройства.

Дайджест считается по :data:`EXPECTED_FEATURES` и
:data:`EXPECTED_ALLOWED_VALUES`; значение зафиксировано до появления
режимов работы.  Его изменение означает, что у всех существующих
пользователей чайник переедет на новую модель в облаке Sber.
"""


def _make_entity(entity_id: str = WATER_HEATER_ID, state: str = "idle", **attributes: object) -> KettleEntity:
    """Создать заполненную состоянием сущность чайника.

    Args:
        entity_id: HA entity_id (определяет домен сервисных вызовов).
        state: Значение HA state.
        **attributes: Атрибуты HA-состояния.

    Returns:
        Сущность после ``fill_by_ha_state``.
    """
    entity = KettleEntity({"entity_id": entity_id, "name": "Kettle"})
    entity.fill_by_ha_state({"entity_id": entity_id, "state": state, "attributes": dict(attributes)})
    return entity


def _service_call(domain: str, service: str, entity_id: str, service_data: dict | None = None) -> dict:
    """Собрать ожидаемый дескриптор сервисного вызова (литерал, не хелпер кода).

    Args:
        domain: HA-домен.
        service: Имя сервиса.
        entity_id: Целевая сущность.
        service_data: Полезная нагрузка или ``None``, если её быть не должно.

    Returns:
        Словарь ровно той формы, которую ждёт мост.
    """
    url: dict = {
        "type": "call_service",
        "domain": domain,
        "service": service,
        "target": {"entity_id": entity_id},
    }
    if service_data is not None:
        url["service_data"] = service_data
    return {"url": url}


def _on_off_cmd(value: bool) -> dict:
    """Собрать элемент команды ``on_off``.

    Args:
        value: Требуемое состояние питания.

    Returns:
        Элемент списка ``states`` команды Sber.
    """
    return {"key": "on_off", "value": {"type": "BOOL", "bool_value": value}}


def _temp_cmd(value: int) -> dict:
    """Собрать элемент команды ``kitchen_water_temperature_set``.

    Args:
        value: Уставка в °C.

    Returns:
        Элемент списка ``states`` команды Sber.
    """
    return {
        "key": "kitchen_water_temperature_set",
        "value": {"type": "INTEGER", "integer_value": str(value)},
    }


def _services(result: list[dict]) -> list[str]:
    """Вернуть последовательность имён вызванных сервисов.

    Args:
        result: Результат ``process_cmd``.

    Returns:
        Имена сервисов в порядке вызова.
    """
    return [item["url"]["service"] for item in result]


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Вернуть WARNING-сообщения модуля чайника.

    Args:
        caplog: Фикстура перехвата логов.

    Returns:
        Отформатированные сообщения уровня WARNING.
    """
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == KETTLE_LOGGER and record.levelno == logging.WARNING
    ]


# ---------------------------------------------------------------------------
# Обратная совместимость: путь без режимов
# ---------------------------------------------------------------------------


def test_legacy_water_heater_turn_on_unchanged() -> None:
    """Чайник без ``operation_list`` обязан включаться прежним ``turn_on``.

    Если сломается: у пользователей, чья интеграция объявила
    ``WaterHeaterEntityFeature.ON_OFF``, чайник перестанет включаться из
    приложения Сбера — мост начнёт слать несуществующий для них сервис.
    """
    entity = _make_entity(state="off")

    result = entity.process_cmd({"states": [_on_off_cmd(True)]})

    assert result == [_service_call("water_heater", "turn_on", WATER_HEATER_ID)]


def test_legacy_water_heater_turn_off_unchanged() -> None:
    """Чайник без ``operation_list`` обязан выключаться прежним ``turn_off``.

    Если сломается: чайник невозможно выключить из приложения — прямой
    риск для пользователя (кипящая вода без команды на отключение).
    """
    entity = _make_entity(state="heating")

    result = entity.process_cmd({"states": [_on_off_cmd(False)]})

    assert result == [_service_call("water_heater", "turn_off", WATER_HEATER_ID)]


def test_legacy_set_temperature_unchanged() -> None:
    """Без режимов уставка ставится голым ``set_temperature`` с int-значением.

    Если сломается: температура уедет строкой или с другим ключом —
    Home Assistant отвергнет вызов, ползунок в приложении Сбера
    перестанет что-либо делать.
    """
    entity = _make_entity(state="heating")

    result = entity.process_cmd({"states": [_temp_cmd(80)]})

    assert result == [_service_call("water_heater", "set_temperature", WATER_HEATER_ID, {"temperature": 80})]


def test_legacy_combined_payload_keeps_both_calls_in_payload_order() -> None:
    """Без режимов совместная команда даёт оба вызова в порядке payload.

    Если сломается: пользователь, двигающий ползунок при включении,
    получит только половину действия — либо нагрев без уставки, либо
    уставку без нагрева.
    """
    entity = _make_entity(state="off")

    result = entity.process_cmd({"states": [_on_off_cmd(True), _temp_cmd(80)]})

    assert result == [
        _service_call("water_heater", "turn_on", WATER_HEATER_ID),
        _service_call("water_heater", "set_temperature", WATER_HEATER_ID, {"temperature": 80}),
    ]


def test_switch_domain_without_modes_unchanged() -> None:
    """Чайник на умной розетке (домен ``switch``) управляется ``switch.turn_on``.

    Если сломается: сценарий «глупый чайник в розетке» — самый массовый
    для этой категории — перестанет работать целиком.
    """
    entity = _make_entity(SWITCH_ID, "off")

    result = entity.process_cmd({"states": [_on_off_cmd(True)]})

    assert result == [_service_call("switch", "turn_on", SWITCH_ID)]


def test_switch_domain_never_uses_operation_modes() -> None:
    """Домен ``switch`` обязан идти прежним путём даже с атрибутом ``operation_list``.

    ТЗ: фолбэк применяется, «если у сущности нет ``operation_list``
    вообще (или это домен ``switch``)».  У домена ``switch`` сервиса
    ``set_operation_mode`` не существует: вызов упадёт с
    ``ServiceNotFound``, и команда из приложения Сбера не выполнится
    вообще.  Шаблонный switch с посторонним атрибутом ``operation_list``
    — вполне реальная конфигурация.
    """
    entity = _make_entity(SWITCH_ID, "on", operation_list=["off", "Boil", "Heat"])

    result = entity.process_cmd({"states": [_on_off_cmd(True)]})

    assert result == [_service_call("switch", "turn_on", SWITCH_ID)]


def test_empty_operation_list_falls_back() -> None:
    """Пустой ``operation_list`` — это отсутствие режимов, а не «режимы есть».

    Если сломается: интеграция, отдающая пустой список, получит вызовы
    ``set_operation_mode`` без единого допустимого значения.
    """
    entity = _make_entity(state="off", operation_list=[])

    result = entity.process_cmd({"states": [_on_off_cmd(True)]})

    assert result == [_service_call("water_heater", "turn_on", WATER_HEATER_ID)]
    assert entity.supports_operation_modes is False


def test_malformed_operation_list_falls_back() -> None:
    """``operation_list`` не-списком игнорируется, режимы не включаются.

    Если сломается: кривой атрибут (строка вместо списка) уронит разбор
    состояния и выкинет чайник из публикации конфигурации.
    """
    entity = _make_entity(state="off", operation_list="Boil")

    assert entity.supports_operation_modes is False
    assert entity.process_cmd({"states": [_on_off_cmd(True)]}) == [
        _service_call("water_heater", "turn_on", WATER_HEATER_ID)
    ]


def test_operation_list_drops_non_string_items() -> None:
    """Из ``operation_list`` берутся только непустые строки.

    Если сломается: ``None`` или число в списке режимов попадёт в
    ``set_operation_mode`` и в выпадающий список панели.
    """
    entity = _make_entity(state="off", operation_list=["off", None, "", 5, "Boil"])

    assert entity.entity_options_state()["operation_list"] == ["off", "Boil"]


@pytest.mark.parametrize("operation_list", [None, ["off", "Boil", "Heat"]])
def test_unknown_command_key_yields_no_calls(operation_list: list[str] | None) -> None:
    """Незнакомый ключ команды не порождает вызовов ни на одном из путей.

    Если сломается: любая посторонняя команда Sber (например
    ``child_lock``) начнёт дёргать чайник — кипячение по чужой команде.
    """
    attrs = {} if operation_list is None else {"operation_list": operation_list}
    entity = _make_entity(state="off", **attrs)

    result = entity.process_cmd(
        {"states": [{"key": "light_brightness", "value": {"type": "INTEGER", "integer_value": "5"}}]}
    )

    assert result == []


@pytest.mark.parametrize("operation_list", [None, ["off", "Boil", "Heat"]])
def test_empty_states_yield_no_calls(operation_list: list[str] | None) -> None:
    """Пустой список ``states`` не порождает вызовов ни на одном из путей.

    Если сломается: пустая команда начнёт включать чайник — самый
    неприятный вид ложного срабатывания.
    """
    attrs = {} if operation_list is None else {"operation_list": operation_list}
    entity = _make_entity(state="off", **attrs)

    assert entity.process_cmd({"states": []}) == []


@pytest.mark.parametrize("operation_list", [None, ["off", "Boil", "Heat"]])
def test_on_off_with_wrong_value_type_ignored(operation_list: list[str] | None) -> None:
    """``on_off`` с типом не ``BOOL`` игнорируется на обоих путях.

    Если сломается: битый payload будет интерпретирован как «включить» и
    чайник вскипятит воду без команды пользователя.
    """
    attrs = {} if operation_list is None else {"operation_list": operation_list}
    entity = _make_entity(state="off", **attrs)

    result = entity.process_cmd({"states": [{"key": "on_off", "value": {"type": "INTEGER", "integer_value": "1"}}]})

    assert result == []


# ---------------------------------------------------------------------------
# Автоопределение режимов
# ---------------------------------------------------------------------------


def _resolved(entity: KettleEntity) -> tuple[str, str, str]:
    """Вернуть тройку разрешённых режимов (off, boil, heat).

    Args:
        entity: Сущность чайника.

    Returns:
        Кортеж значений ``resolved_*`` из блока опций панели.
    """
    block = entity.entity_options_state()
    return (
        str(block["resolved_off_mode"]),
        str(block["resolved_boil_mode"]),
        str(block["resolved_heat_mode"]),
    )


def test_autodetect_lowercase_names() -> None:
    """Список ``off/boil/heat`` распознаётся без единой настройки.

    Если сломается: типовой SkyKettle потребует ручной настройки, а до
    неё чайник из приложения Сбера управляться не будет.
    """
    entity = _make_entity(state="off", operation_list=["off", "boil", "heat"])

    assert _resolved(entity) == ("off", "boil", "heat")


def test_autodetect_is_case_insensitive_and_returns_original_names() -> None:
    """Сопоставление без учёта регистра, но в HA уходит исходное написание.

    Если сломается: мост пошлёт ``boil`` вместо ``Boil``, HA отвергнет
    значение как недопустимое и чайник не включится.
    """
    entity = _make_entity(state="Off", operation_list=["Off", "BOIL", "Heat"])

    assert _resolved(entity) == ("Off", "BOIL", "Heat")


def test_autodetect_prefers_heat_over_ha_constants() -> None:
    """При наличии ``heat`` он и есть режим нагрева, а не ``eco``.

    Если сломается: чайник с оптимизированным «эко»-режимом начнёт
    греть воду не тем режимом, который выбрал бы пользователь.
    """
    entity = _make_entity(state="off", operation_list=["off", "boil", "eco", "heat"])

    assert _resolved(entity)[2] == "heat"


def test_autodetect_electric_wins_over_eco() -> None:
    """Порядок кандидатов нагрева задан ТЗ: ``electric`` раньше ``eco``.

    Если сломается: приоритет режимов станет зависеть от порядка,
    в котором интеграция перечислила режимы, — поведение перестанет быть
    предсказуемым между перезапусками HA.
    """
    entity = _make_entity(state="off", operation_list=["eco", "electric"])

    assert _resolved(entity)[2] == "electric"


@pytest.mark.parametrize("heat_name", ["electric", "eco", "gas", "heat_pump", "high_demand", "performance"])
def test_autodetect_accepts_ha_standard_heat_modes(heat_name: str) -> None:
    """Каждая стандартная константа HA ``water_heater`` годится в нагрев.

    Если сломается: чайники на generic-интеграциях, использующих
    словарь HA, останутся без режима нагрева и уедут в фолбэк.
    """
    entity = _make_entity(state="off", operation_list=["off", "boil", heat_name])

    assert _resolved(entity)[2] == heat_name


def test_autodetect_finds_nothing_in_unknown_names() -> None:
    """Незнакомые (например, русские) имена режимов не «угадываются».

    Если сломается: мост выберет произвольный режим и чайник начнёт
    делать не то, что просил пользователь.
    """
    entity = _make_entity(state="Выключен", operation_list=["Выключен", "Кипячение", "Подогрев"])

    assert _resolved(entity) == ("", "", "")


def test_missing_operation_list_attribute_resolves_nothing() -> None:
    """Без атрибута ``operation_list`` разрешённых режимов нет вообще.

    Если сломается: панель покажет режимы у чайника, который их не
    поддерживает, и пользователь настроит заведомо нерабочую связку.
    """
    entity = _make_entity(state="off")

    assert _resolved(entity) == ("", "", "")
    assert entity.entity_options_state()["operation_list"] == []


def test_partial_operation_list_resolves_only_known_modes() -> None:
    """Отсутствующий в списке режим остаётся неразрешённым, остальные — нет.

    Если сломается: неразрешённый режим подменится соседним (например,
    нагрев кипячением) — вода будет кипеть вместо 70 °C.
    """
    entity = _make_entity(state="off", operation_list=["off", "boil"])

    assert _resolved(entity) == ("off", "boil", "")


# ---------------------------------------------------------------------------
# Ручной выбор режимов и его приоритет
# ---------------------------------------------------------------------------


def test_explicit_mode_overrides_autodetection() -> None:
    """Явно выбранный режим важнее автоопределённого.

    Если сломается: настройка пользователя молча игнорируется — самый
    обидный класс багов, потому что панель показывает одно, а мост
    делает другое.
    """
    entity = _make_entity(state="off", operation_list=["off", "boil", "heat", "eco"])
    entity.apply_entity_options({"heat_mode": "eco"})

    result = entity.process_cmd({"states": [_on_off_cmd(True), _temp_cmd(70)]})

    assert result == [
        _service_call("water_heater", "set_temperature", WATER_HEATER_ID, {"temperature": 70}),
        _service_call("water_heater", "set_operation_mode", WATER_HEATER_ID, {"operation_mode": "eco"}),
    ]


def test_explicit_off_mode_used_for_power_off() -> None:
    """Явный ``off_mode`` используется для выключения.

    Если сломается: чайник с нестандартным именем «выключено»
    невозможно выключить из приложения Сбера.
    """
    entity = _make_entity(state="Кипячение", operation_list=["Выключен", "Кипячение"])
    entity.apply_entity_options({"off_mode": "Выключен"})

    result = entity.process_cmd({"states": [_on_off_cmd(False)]})

    assert result == [
        _service_call("water_heater", "set_operation_mode", WATER_HEATER_ID, {"operation_mode": "Выключен"})
    ]


def test_options_applied_before_state_still_take_effect() -> None:
    """Опции, применённые до загрузки состояния, не теряются.

    ``SberEntityLoader`` применяет опции при загрузке сущности, а
    состояние HA приезжает позже.  Если сломается: после каждого
    перезапуска Home Assistant настройки чайника будут обнуляться до
    автоопределения.
    """
    entity = KettleEntity({"entity_id": WATER_HEATER_ID, "name": "Kettle"})
    entity.apply_entity_options({"off_mode": "Выключен", "boil_mode": "Кипячение", "heat_mode": "Подогрев"})
    entity.fill_by_ha_state(
        {
            "entity_id": WATER_HEATER_ID,
            "state": "Выключен",
            "attributes": {"operation_list": ["Выключен", "Кипячение", "Подогрев"]},
        }
    )

    assert _resolved(entity) == ("Выключен", "Кипячение", "Подогрев")
    assert entity.process_cmd({"states": [_on_off_cmd(True)]}) == [
        _service_call("water_heater", "set_operation_mode", WATER_HEATER_ID, {"operation_mode": "Кипячение"})
    ]


def test_empty_option_restores_autodetection() -> None:
    """Пустая строка в опции возвращает режим к автоопределению.

    Если сломается: пользователь не сможет отменить ошибочный выбор,
    не удалив и не заведя устройство заново.
    """
    entity = _make_entity(state="off", operation_list=["off", "boil", "heat", "eco"])
    entity.apply_entity_options({"heat_mode": "eco"})
    entity.apply_entity_options({"heat_mode": ""})

    assert _resolved(entity)[2] == "heat"
    assert entity.entity_options_state()["heat_mode"] == ""


def test_stale_explicit_mode_falls_back_to_autodetection_once(caplog: pytest.LogCaptureFixture) -> None:
    """Исчезнувший из прошивки режим не парализует чайник, WARNING — один раз.

    Если сломается: после обновления прошивки чайника мост будет слать
    несуществующий режим (тишина вместо нагрева) либо зальёт журнал HA
    предупреждениями на каждую команду.
    """
    entity = _make_entity(state="off", operation_list=["off", "boil", "heat"])
    entity.apply_entity_options({"boil_mode": "Кипячение"})

    with caplog.at_level(logging.WARNING, logger=KETTLE_LOGGER):
        first = entity.process_cmd({"states": [_on_off_cmd(True)]})
        second = entity.process_cmd({"states": [_on_off_cmd(True)]})

    expected = [_service_call("water_heater", "set_operation_mode", WATER_HEATER_ID, {"operation_mode": "boil"})]
    assert first == expected
    assert second == expected
    assert len(_warnings(caplog)) == 1


def test_apply_entity_options_ignores_garbage_values() -> None:
    """Нестроковое значение опции не ломает загрузку сущности.

    ``apply_entity_options`` работает на пути загрузки: исключение здесь
    убьёт всю интеграцию из-за одной кривой строки в ``entry.options``.
    """
    entity = _make_entity(state="off", operation_list=["off", "boil", "heat"])

    entity.apply_entity_options({"heat_mode": 42, "boil_mode": None, "off_mode": "   "})

    assert _resolved(entity) == ("off", "boil", "heat")


def test_apply_entity_options_ignores_unknown_keys() -> None:
    """Неизвестный ключ опций на пути загрузки просто игнорируется.

    Если сломается: откат интеграции на старую версию (в конфиге остался
    ключ от новой) не даст ей запуститься.
    """
    entity = _make_entity(state="off", operation_list=["off", "boil", "heat"])

    entity.apply_entity_options({"travel_time": 12.5})

    assert _resolved(entity) == ("off", "boil", "heat")


def test_entity_options_state_full_contract() -> None:
    """Блок опций для панели отдаётся полностью и точно.

    Панель строит выпадающие списки из ``operation_list`` и показывает
    разрешённые режимы.  Если сломается: пользователь получит поле
    свободного ввода и настроит режим, которого у чайника нет.
    """
    entity = _make_entity(state="off", operation_list=["off", "Boil", "Heat"])
    entity.apply_entity_options({"boil_mode": "Boil"})

    assert entity.entity_options_state() == {
        "off_mode": "",
        "boil_mode": "Boil",
        "heat_mode": "",
        "operation_list": ["off", "Boil", "Heat"],
        "resolved_off_mode": "off",
        "resolved_boil_mode": "Boil",
        "resolved_heat_mode": "Heat",
    }


def test_entity_options_contract_metadata() -> None:
    """Класс объявляет ровно три опции и свой блок в ``device_detail``.

    Если сломается: обобщённый механизм опций (WS-команда, экспорт /
    импорт, панель) перестанет видеть настройки чайника.
    """
    entity = _make_entity(state="off")

    assert KettleEntity.ENTITY_OPTION_KEYS == ("off_mode", "boil_mode", "heat_mode")
    assert KettleEntity.ENTITY_OPTIONS_BLOCK == "kettle_options"
    assert entity.supports_entity_options is True


# ---------------------------------------------------------------------------
# Валидация пользовательского ввода
# ---------------------------------------------------------------------------


def test_validate_rejects_mode_absent_from_operation_list() -> None:
    """Режим не из списка сущности отвергается с внятным текстом.

    Если сломается: HA молча проигнорирует недопустимый режим, чайник
    будет подтверждать команды и никогда не нагреваться — ровно тот
    случай, который отлаживать тяжелее всего.
    """
    entity = _make_entity(state="off", operation_list=["off", "Boil", "Heat"])

    with pytest.raises(ValueError, match="is not one of this kettle") as excinfo:
        entity.validate_entity_options({"heat_mode": "Кипячение"})

    message = str(excinfo.value)
    assert "Кипячение" in message
    assert "heat_mode" in message
    assert "Heat" in message


def test_validate_rejects_unknown_option_key() -> None:
    """Чужой ключ опции отвергается валидацией.

    Если сломается: опция ворот, отправленная в чайник, тихо осядет в
    конфиге и будет вечно ездить через экспорт / импорт.
    """
    entity = _make_entity(state="off", operation_list=["off", "boil", "heat"])

    with pytest.raises(ValueError, match="unknown option"):
        entity.validate_entity_options({"auto_close_time": 30})


def test_validate_rejects_non_string_mode() -> None:
    """Нестроковое значение режима отвергается валидацией.

    Если сломается: число уедет в ``set_operation_mode`` и HA будет
    ругаться на каждую команду.
    """
    entity = _make_entity(state="off", operation_list=["off", "boil", "heat"])

    with pytest.raises(ValueError, match="must be a mode name"):
        entity.validate_entity_options({"off_mode": 5})


def test_validate_rejects_modes_when_entity_has_none() -> None:
    """Задавать режимы чайнику без ``operation_list`` нельзя.

    Если сломается: пользователь настроит режимы «глупому» чайнику в
    розетке и будет ждать нагрева до 70 °C от обычного реле.
    """
    entity = _make_entity(state="off")

    with pytest.raises(ValueError, match="no operation modes"):
        entity.validate_entity_options({"boil_mode": "boil"})


def test_validate_accepts_empty_values_for_autodetection() -> None:
    """Пустые значения проходят валидацию даже без ``operation_list``.

    Если сломается: пользователь не сможет сохранить форму «всё по
    умолчанию» — панель будет показывать ошибку на пустых полях.
    """
    entity = _make_entity(state="off")

    entity.validate_entity_options({"off_mode": "", "boil_mode": None, "heat_mode": ""})


def test_validate_accepts_modes_from_the_list() -> None:
    """Корректный набор режимов проходит валидацию.

    Если сломается: настроить чайник станет невозможно вообще.
    """
    entity = _make_entity(state="off", operation_list=["Выключен", "Кипячение", "Подогрев"])

    entity.validate_entity_options({"off_mode": "Выключен", "boil_mode": "Кипячение", "heat_mode": "Подогрев"})


def test_validate_does_not_mutate_entity() -> None:
    """Валидация ничего не применяет — только проверяет.

    Если сломается: отвергнутая панелью форма всё равно изменит
    поведение работающего моста, и состояние моста разойдётся с
    сохранённым конфигом.
    """
    entity = _make_entity(state="off", operation_list=["off", "boil", "heat", "eco"])

    entity.validate_entity_options({"heat_mode": "eco"})

    assert entity.entity_options_state()["heat_mode"] == ""
    assert _resolved(entity)[2] == "heat"


# ---------------------------------------------------------------------------
# Матрица команд: точная последовательность вызовов
# ---------------------------------------------------------------------------

MODE_LIST = ["off", "Boil", "Heat"]
"""Типовой список режимов SkyKettle-подобного чайника."""


def _mode_entity(state: str = "off", **extra: object) -> KettleEntity:
    """Создать чайник с типовым набором режимов.

    Args:
        state: Значение HA state.
        **extra: Дополнительные атрибуты HA.

    Returns:
        Заполненная сущность с ``operation_list`` = :data:`MODE_LIST`.
    """
    return _make_entity(state=state, operation_list=list(MODE_LIST), **extra)


def _mode_call(mode: str) -> dict:
    """Ожидаемый вызов ``set_operation_mode``.

    Args:
        mode: Имя режима.

    Returns:
        Дескриптор сервисного вызова.
    """
    return _service_call("water_heater", "set_operation_mode", WATER_HEATER_ID, {"operation_mode": mode})


def _temp_call(temperature: int) -> dict:
    """Ожидаемый вызов ``set_temperature``.

    Args:
        temperature: Уставка в °C.

    Returns:
        Дескриптор сервисного вызова.
    """
    return _service_call("water_heater", "set_temperature", WATER_HEATER_ID, {"temperature": temperature})


def test_off_command_switches_to_off_mode() -> None:
    """``on_off=false`` переводит чайник в режим выключения одним вызовом.

    Если сломается: чайник не выключается из приложения Сбера — режим
    остаётся «кипячение».
    """
    entity = _mode_entity("Boil")

    assert entity.process_cmd({"states": [_on_off_cmd(False)]}) == [_mode_call("off")]


def test_off_command_wins_over_temperature_in_same_payload() -> None:
    """``on_off=false`` вместе с температурой означает только выключение.

    Если сломается: команда «выключить» приведёт к включению нагрева —
    ровно противоположный результат.
    """
    entity = _mode_entity("Heat")

    result = entity.process_cmd({"states": [_on_off_cmd(False), _temp_cmd(80)]})

    assert result == [_mode_call("off")]


def test_on_with_max_temperature_boils() -> None:
    """``on_off=true`` с максимальной уставкой означает кипячение.

    Если сломается: верх ползунка Сбера перестанет кипятить воду —
    основной сценарий использования чайника.
    """
    entity = _mode_entity("off")

    result = entity.process_cmd({"states": [_on_off_cmd(True), _temp_cmd(KETTLE_TEMPERATURE_MAX)]})

    assert result == [_mode_call("Boil")]


def test_on_without_temperature_boils() -> None:
    """``on_off=true`` без температуры означает кипячение.

    Если сломается: кнопка «включить» в приложении Сбера не сделает
    ничего либо включит нагрев до случайной уставки.
    """
    entity = _mode_entity("off")

    assert entity.process_cmd({"states": [_on_off_cmd(True)]}) == [_mode_call("Boil")]


def test_heating_below_max_must_switch_to_heat_mode() -> None:
    """Исходный баг: нагрев ниже максимума обязан включать режим нагрева.

    Голый ``set_temperature`` у SkyKettle-подобных чайников только
    двигает уставку и никогда не запускает нагрев.  Если сломается:
    чайник примет команду, покажет новую уставку и останется холодным —
    ради этого случая вся доработка и делалась.
    """
    entity = _mode_entity("off")

    result = entity.process_cmd({"states": [_on_off_cmd(True), _temp_cmd(70)]})

    assert _services(result) == ["set_temperature", "set_operation_mode"]
    assert result == [_temp_call(70), _mode_call("Heat")]


def test_heating_below_max_sets_temperature_before_mode() -> None:
    """Уставка выставляется ДО режима нагрева.

    Чайник начинает греть в момент установки режима и греет до той
    уставки, которая у него на этот момент.  Если сломается (режим
    первым): запрошенные 70 °C приведут к полному циклу кипячения по
    старой уставке — вода закипит там, где пользователь просил
    подогрев.
    """
    entity = _mode_entity("off")

    result = entity.process_cmd({"states": [_on_off_cmd(True), _temp_cmd(60)]})

    assert len(result) == 2
    assert result[0]["url"]["service"] == "set_temperature"
    assert result[0]["url"]["service_data"] == {"temperature": KETTLE_TEMPERATURE_MIN}
    assert result[1]["url"]["service"] == "set_operation_mode"
    assert result[1]["url"]["service_data"] == {"operation_mode": "Heat"}


def test_temperature_only_below_max_heats() -> None:
    """Команда с одной температурой ниже максимума запускает нагрев.

    Если сломается: движение ползунка у включённого чайника перестанет
    менять поведение — уставка есть, нагрева нет.
    """
    entity = _mode_entity("Boil")

    result = entity.process_cmd({"states": [_temp_cmd(90)]})

    assert result == [_temp_call(90), _mode_call("Heat")]


def test_temperature_only_at_max_boils() -> None:
    """Команда с одной максимальной температурой означает кипячение.

    Если сломается: ползунок, доведённый до 100 °C, оставит чайник в
    режиме подогрева и вода никогда не закипит.
    """
    entity = _mode_entity("Heat")

    result = entity.process_cmd({"states": [_temp_cmd(KETTLE_TEMPERATURE_MAX)]})

    assert result == [_mode_call("Boil")]


def test_just_below_max_is_still_heating() -> None:
    """99 °C — это нагрев, а не кипячение: граница ровно на максимуме.

    Если сломается: любая уставка будет трактоваться как кипячение и
    режим подогрева станет недостижим.
    """
    entity = _mode_entity("off")

    result = entity.process_cmd({"states": [_on_off_cmd(True), _temp_cmd(KETTLE_TEMPERATURE_MAX - 1)]})

    assert result == [_temp_call(KETTLE_TEMPERATURE_MAX - 1), _mode_call("Heat")]


def test_ha_max_temperature_becomes_the_boil_point() -> None:
    """Собственный максимум чайника из HA — это и есть «кипятить».

    SkyKettle-подобные чайники сообщают ``max_temp: 90`` и физически не
    принимают уставку выше.  Верх ползунка Сбера для такого чайника
    обязан означать кипячение.  Если сломается: верхняя позиция
    ползунка выдаст ``set_temperature(90)`` + режим подогрева — чайник
    перестанет кипятить и никогда не отрапортует кипячение.
    """
    entity = _mode_entity("off", max_temp=90)

    result = entity.process_cmd({"states": [_on_off_cmd(True), _temp_cmd(90)]})

    assert result == [_mode_call("Boil")]


@pytest.mark.parametrize(
    ("attributes", "case_id"),
    [
        ({}, "attribute-absent"),
        ({"max_temp": KETTLE_TEMPERATURE_MIN}, "equal-to-slider-min"),
        ({"max_temp": KETTLE_TEMPERATURE_MAX}, "equal-to-slider-max"),
        ({"max_temp": 120}, "above-slider-max"),
        ({"max_temp": "unknown"}, "not-a-number"),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_implausible_ha_max_keeps_the_standard_boil_point(attributes: dict, case_id: str) -> None:
    """Неправдоподобный ``max_temp`` не сдвигает точку кипения.

    Точка кипения подменяется только значением строго внутри диапазона
    ползунка (``KETTLE_TEMPERATURE_MIN`` < ``max_temp`` <
    ``KETTLE_TEMPERATURE_MAX``).  Если сломается: мусорный или
    отсутствующий атрибут либо схлопнет точку кипения в минимум ползунка
    (любой подогрев начнёт кипятить воду), либо поднимет её выше 100 °C
    (кипячение станет недостижимым).

    Args:
        attributes: Атрибуты HA-состояния для проверяемого случая.
        case_id: Читаемое имя случая (используется в идентификаторе теста).
    """
    entity = _mode_entity("off", **attributes)

    result = entity.process_cmd({"states": [_on_off_cmd(True), _temp_cmd(90)]})

    assert result == [_temp_call(90), _mode_call("Heat")], case_id


def test_ha_max_above_the_slider_still_boils_at_the_slider_top() -> None:
    """``max_temp`` выше ползунка не делает кипячение недостижимым.

    Ползунок Сбера заканчивается на :data:`KETTLE_TEMPERATURE_MAX`, и
    выше его пользователь запросить не может.  Если верхняя граница
    клампа исчезнет, чайник с ``max_temp: 120`` получит точку кипения
    120 °C: верх ползунка выдаст ``set_temperature(100)`` + подогрев, и
    режим кипячения станет недостижим из приложения.
    """
    entity = _mode_entity("off", max_temp=120)

    result = entity.process_cmd({"states": [_on_off_cmd(True), _temp_cmd(KETTLE_TEMPERATURE_MAX)]})

    assert result == [_mode_call("Boil")]


def test_payload_order_does_not_change_the_plan() -> None:
    """План не зависит от порядка элементов в ``states``.

    Sber не гарантирует порядок полей.  Если сломается: одна и та же
    команда будет то греть, то кипятить — воспроизводимость багов
    исчезнет.
    """
    entity = _mode_entity("off")

    forward = entity.process_cmd({"states": [_on_off_cmd(True), _temp_cmd(80)]})
    backward = entity.process_cmd({"states": [_temp_cmd(80), _on_off_cmd(True)]})

    assert forward == backward == [_temp_call(80), _mode_call("Heat")]


def test_proto3_elided_false_is_treated_as_off() -> None:
    """``{"type": "BOOL"}`` без поля — это ``false`` (proto3-элизия).

    Sber опускает поля со значением по умолчанию.  Если сломается:
    команда «выключить» будет прочитана как «включить» и чайник
    вскипятит воду вместо выключения.
    """
    entity = _mode_entity("Boil")

    result = entity.process_cmd({"states": [{"key": "on_off", "value": {"type": "BOOL"}}]})

    assert result == [_mode_call("off")]


def test_unresolved_boil_mode_falls_back_and_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    """Нераспознанный режим кипячения — фолбэк и ровно один WARNING.

    Если сломается: чайник с русскими именами режимов либо перестанет
    отвечать на команды вовсе, либо зальёт журнал HA предупреждениями
    на каждый запрос Сбера.
    """
    entity = _make_entity(state="Выключен", operation_list=["Выключен", "Кипячение"])

    with caplog.at_level(logging.WARNING, logger=KETTLE_LOGGER):
        first = entity.process_cmd({"states": [_on_off_cmd(True)]})
        second = entity.process_cmd({"states": [_on_off_cmd(True)]})

    assert first == [_service_call("water_heater", "turn_on", WATER_HEATER_ID)]
    assert second == first
    assert len(_warnings(caplog)) == 1


def test_unresolved_off_mode_falls_back_to_turn_off(caplog: pytest.LogCaptureFixture) -> None:
    """Нераспознанный режим выключения — фолбэк на ``turn_off``.

    Если сломается: чайник с нестандартным «выключено» нельзя будет
    выключить ни режимом, ни прежним способом.
    """
    entity = _make_entity(state="boil", operation_list=["boil", "heat"])

    with caplog.at_level(logging.WARNING, logger=KETTLE_LOGGER):
        result = entity.process_cmd({"states": [_on_off_cmd(False)]})

    assert result == [_service_call("water_heater", "turn_off", WATER_HEATER_ID)]
    assert len(_warnings(caplog)) == 1


def test_unresolved_heat_mode_falls_back_to_legacy_pair(caplog: pytest.LogCaptureFixture) -> None:
    """Без режима нагрева команда «нагреть» деградирует до прежней пары вызовов.

    Если сломается: чайник, у которого распознались только ``off`` и
    ``boil``, потеряет реакцию на команды с температурой.
    """
    entity = _make_entity(state="off", operation_list=["off", "boil"])

    with caplog.at_level(logging.WARNING, logger=KETTLE_LOGGER):
        result = entity.process_cmd({"states": [_on_off_cmd(True), _temp_cmd(70)]})

    assert result == [
        _service_call("water_heater", "turn_on", WATER_HEATER_ID),
        _temp_call(70),
    ]
    assert len(_warnings(caplog)) == 1


@pytest.mark.parametrize(
    ("operation_list", "expected_mode"),
    [
        (["off", "eco", "electric", "performance"], "electric"),
        (["off", "Boil+Heat", "Heat"], "Heat"),
    ],
    ids=["ha-standard-names", "skykettle-without-plain-boil"],
)
def test_missing_boil_mode_falls_back_to_the_heat_mode(
    operation_list: list[str],
    expected_mode: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Без режима «кипятить», но с режимом нагрева, включение греет, а не молчит.

    ``turn_on`` — ровно тот сервис, которого у чайника, управляемого
    режимами, НЕТ (он объявляется только с ``WaterHeaterEntityFeature``
    ``ON_OFF``).  Списки вида ``off/eco/electric/performance`` (штатные
    имена HA) и ``off/Boil+Heat/Heat`` не содержат буквального «boil»,
    хотя режим нагрева в них распознаётся.

    Если сломается: у таких чайников «включи» из приложения Сбера не
    сделает НИЧЕГО — вызов уйдёт в несуществующий ``turn_on``, а
    единственным следом останется строчка в журнале.
    """
    entity = _make_entity(state="off", operation_list=operation_list)

    with caplog.at_level(logging.WARNING, logger=KETTLE_LOGGER):
        first = entity.process_cmd({"states": [_on_off_cmd(True)]})
        second = entity.process_cmd({"states": [_on_off_cmd(True)]})

    assert first == [_mode_call(expected_mode)]
    assert second == first
    assert len(_warnings(caplog)) == 1


def test_elided_temperature_does_not_start_a_heating_cycle() -> None:
    """``{"type": "INTEGER"}`` без значения не запускает нагрев.

    Sber опускает поля со значением по умолчанию (proto3), поэтому такой
    элемент читается как 0 °C — вдвое ниже нижней границы 60 °C, которую
    сам класс объявляет в ``allowed_values``.  Пользователь такого
    запросить не мог.

    Если сломается: чайник переключится в режим нагрева, а уставку 0 °C
    интеграция, скорее всего, отвергнет — и цикл пойдёт на ПРЕЖНЕЙ
    уставке, которой у чайников этого класса обычно является кипение.
    """
    entity = _mode_entity("off")

    result = entity.process_cmd({"states": [{"key": "kitchen_water_temperature_set", "value": {"type": "INTEGER"}}]})

    assert result == [_temp_call(0)]


@pytest.mark.parametrize("temperature", [0, KETTLE_TEMPERATURE_MIN - 1, KETTLE_TEMPERATURE_MAX + 1])
def test_temperature_outside_the_advertised_range_never_picks_the_heat_mode(temperature: int) -> None:
    """Уставка вне объявленного диапазона не выбирает режим нагрева.

    ``create_allowed_values_list`` объявляет Сберу 60-100 °C, значит
    ползунок не может прислать ничего другого.  Такое значение — не
    запрос пользователя, и решать по нему «греть или кипятить» нельзя.

    Если сломается: мусорное значение начнёт управлять режимом работы
    чайника.
    """
    entity = _mode_entity("off")

    result = entity.process_cmd({"states": [_on_off_cmd(True), _temp_cmd(temperature)]})

    assert result == [_mode_call("Boil")]


# ---------------------------------------------------------------------------
# Публикуемое состояние
# ---------------------------------------------------------------------------


def _state_map(entity: KettleEntity) -> dict[str, dict]:
    """Свернуть публикуемое состояние в словарь ``feature -> value``.

    Args:
        entity: Сущность чайника.

    Returns:
        Отображение ключа фичи на значение Sber.
    """
    states = entity.to_sber_current_state()[entity.entity_id]["states"]
    return {item["key"]: item["value"] for item in states}


def test_mode_name_as_state_reports_kettle_on() -> None:
    """Имя режима в HA state — это включённый чайник.

    ``WaterHeaterEntity`` отдаёт текущий режим как state.  Если
    сломается: приложение Сбера будет показывать кипящий чайник
    выключенным.
    """
    entity = _mode_entity("Boil")

    assert _state_map(entity)["on_off"] == {"type": "BOOL", "bool_value": True}


def test_configured_off_mode_reports_kettle_off() -> None:
    """Нестандартный режим выключения публикуется как ``on_off=false``.

    Если сломается: выключенный чайник вечно висит в приложении Сбера
    включённым, и повторное выключение ничего не меняет.
    """
    entity = KettleEntity({"entity_id": WATER_HEATER_ID, "name": "Kettle"})
    entity.apply_entity_options({"off_mode": "Выключен"})
    entity.fill_by_ha_state(
        {
            "entity_id": WATER_HEATER_ID,
            "state": "Выключен",
            "attributes": {"operation_list": ["Выключен", "Кипячение"]},
        }
    )

    assert _state_map(entity)["on_off"] == {"type": "BOOL", "bool_value": False}


def test_operation_mode_attribute_wins_over_state() -> None:
    """Атрибут ``operation_mode`` важнее HA state при определении питания.

    Некоторые интеграции держат режим в атрибуте, а в state — фазу
    работы.  Если сломается: чайник в выключенном режиме будет
    публиковаться включённым.
    """
    entity = KettleEntity({"entity_id": WATER_HEATER_ID, "name": "Kettle"})
    entity.apply_entity_options({"off_mode": "Выключен"})
    entity.fill_by_ha_state(
        {
            "entity_id": WATER_HEATER_ID,
            "state": "heating",
            "attributes": {
                "operation_list": ["Выключен", "Кипячение"],
                "operation_mode": "Выключен",
            },
        }
    )

    assert _state_map(entity)["on_off"] == {"type": "BOOL", "bool_value": False}


def test_published_state_keys_are_exactly_the_kettle_set() -> None:
    """Публикуется ровно оговорённый спекой Sber набор состояний.

    Лишний ключ Sber молча отбрасывает вместе со всем устройством
    (история issue #44).  Если сломается: чайник исчезнет из приложения.
    """
    entity = _make_entity(
        state="Heat",
        operation_list=list(MODE_LIST),
        current_temperature=55,
        temperature=80,
        water_level=70,
        child_lock=True,
    )

    published = _state_map(entity)

    assert set(published) == {
        "online",
        "on_off",
        "kitchen_water_temperature",
        "kitchen_water_temperature_set",
        "kitchen_water_level",
        "kitchen_water_low_level",
        "child_lock",
    }
    assert published["kitchen_water_temperature"] == {"type": "INTEGER", "integer_value": "55"}
    assert published["kitchen_water_temperature_set"] == {"type": "INTEGER", "integer_value": "80"}
    assert published["kitchen_water_level"] == {"type": "INTEGER", "integer_value": "70"}
    assert published["kitchen_water_low_level"] == {"type": "BOOL", "bool_value": False}
    assert published["child_lock"] == {"type": "BOOL", "bool_value": True}
    assert published["online"] == {"type": "BOOL", "bool_value": True}


# ---------------------------------------------------------------------------
# Заморозка возможностей: фичи, allowed_values, model.id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attributes",
    [
        {},
        {"operation_list": ["off", "Boil", "Heat"]},
        {"operation_list": ["off", "Boil", "Heat"], "min_temp": 40, "max_temp": 90},
    ],
    ids=["legacy", "with-modes", "with-modes-and-ha-limits"],
)
def test_features_list_unchanged_by_modes(attributes: dict) -> None:
    """Режимы работы не добавляют и не убирают ни одной фичи Sber.

    Список фич входит в дайджест ``model.id``.  Если сломается: у всех
    существующих пользователей чайник переедет на новую модель в облаке
    Sber и потеряет комнату, имя и сценарии.
    """
    entity = _make_entity(state="off", **attributes)

    assert entity.get_final_features_list() == EXPECTED_FEATURES


@pytest.mark.parametrize(
    "attributes",
    [
        {},
        {"operation_list": ["off", "Boil", "Heat"]},
        {"operation_list": ["off", "Boil", "Heat"], "min_temp": 40, "max_temp": 90},
    ],
    ids=["legacy", "with-modes", "with-modes-and-ha-limits"],
)
def test_allowed_values_never_derived_from_ha_limits(attributes: dict) -> None:
    """Диапазон температур остаётся 60..100 шаг 10 при любых лимитах HA.

    ТЗ прямо запрещает тянуть ``min_temp`` / ``max_temp`` из HA в
    ``allowed_values``.  Если сломается: ``model.id`` станет
    устройство-специфичным и каждый пользователь получит новую модель.
    """
    entity = _make_entity(state="off", **attributes)

    assert entity.create_allowed_values_list() == EXPECTED_ALLOWED_VALUES
    assert (KETTLE_TEMPERATURE_MIN, KETTLE_TEMPERATURE_MAX, KETTLE_TEMPERATURE_STEP) == (60, 100, 10)


def test_model_id_digest_unchanged() -> None:
    """``model.id`` чайника не изменился с появлением режимов.

    Если сломается: Sber заведёт новую модель, а устройства
    пользователей окажутся привязаны к старой — управление отвалится до
    ручного переподключения.
    """
    legacy = _make_entity(state="off")
    with_modes = _make_entity(state="off", operation_list=["off", "Boil", "Heat"], max_temp=90)
    with_modes.apply_entity_options({"off_mode": "off", "boil_mode": "Boil", "heat_mode": "Heat"})

    assert legacy.to_sber_state()["model"]["id"] == EXPECTED_MODEL_ID
    assert with_modes.to_sber_state()["model"]["id"] == EXPECTED_MODEL_ID


def test_model_descriptor_shape_unchanged() -> None:
    """Дескриптор модели остаётся категорией ``kettle`` с теми же фичами.

    Если сломается: изменится состав ``model`` в конфигурации, и Sber
    отвергнет устройство целиком.
    """
    entity = _make_entity(state="off", operation_list=["off", "Boil", "Heat"])

    model = entity.to_sber_state()["model"]

    assert model["category"] == "kettle"
    assert model["features"] == EXPECTED_FEATURES
    assert model["allowed_values"] == EXPECTED_ALLOWED_VALUES
