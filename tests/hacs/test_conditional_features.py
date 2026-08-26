"""Conditionally-obligatory (``✔︎*``) Sber features: table + validator rule.

Sber marks some features with ``✔︎*`` and footnotes them as an "at least
one of" group — a gate must describe *some* way to open, an air sensor
must report *some* measurement.  Declaring none of the group is exactly
as fatal as omitting a strictly obligatory feature: the cloud drops the
device without a word, which is the failure mode issue #44 was about.

Until now that marker was scraped into
``tests/hacs/__snapshots__/sber_full_spec.json`` and then thrown away —
``tools/codegen.py`` rendered only the strict table, so nothing in the
running code knew the rule existed.  These tests lock both halves of the
fix: the generated table, and the validator check built on it.

The check is deliberately keyed on the device's **declared features**
rather than on a state payload.  A group member can be command-only —
Sber's own page for ``open_set`` says "Не хранит состояние устройства" —
so an impulse gate that satisfies the rule perfectly publishes not one
member of the group.  Validating the payload would flag every such
device; that inversion is what
:class:`TestValidatorChecksDeclarationsNotStates` pins down.
"""

from __future__ import annotations

import pytest

from custom_components.sber_mqtt_bridge._generated.category_features import CATEGORY_REFERENCE_FEATURES
from custom_components.sber_mqtt_bridge._generated.conditional_features import CATEGORY_CONDITIONAL_FEATURES
from custom_components.sber_mqtt_bridge._generated.feature_types import FEATURE_TYPES
from custom_components.sber_mqtt_bridge._generated.obligatory_features import CATEGORY_OBLIGATORY_FEATURES
from custom_components.sber_mqtt_bridge.schema_validator import validate_publish

ONLINE_STATE = {"key": "online", "value": {"type": "BOOL", "bool_value": True}}
"""Minimal well-formed state, enough to keep unrelated checks quiet."""

OPEN_STATE = {"key": "open_state", "value": {"type": "ENUM", "enum_value": "close"}}
"""A closed gate — what an impulse gate publishes besides ``online``."""


def _types(entity_id: str, category: str, states: list[dict], declared: list[str] | None) -> list[str]:
    """Return the issue types one publish produces, in order.

    Args:
        entity_id: Device id to validate under.
        category: Sber category.
        states: Payload state dicts.
        declared: Feature list from the config publish, or ``None``.

    Returns:
        ``type`` of every issue raised.
    """
    return [
        i.type
        for i in validate_publish(entity_id=entity_id, category=category, states=states, declared_features=declared)
    ]


class TestGeneratedTable:
    """The table must mirror the scraped spec exactly, not approximately."""

    def test_exact_groups(self) -> None:
        """Пинает точное содержимое таблицы условно-обязательных функций.

        Если тест упадёт, значит кодоген либо потерял категорию, либо
        добавил лишнюю — и валидатор начнёт либо молчать там, где Sber
        отбросит устройство, либо ругаться на исправное.  Обновлять этот
        тест можно только вместе с пересканированием документации.
        """
        expected = {
            "curtain": frozenset({"open_percentage", "open_set"}),
            "gate": frozenset({"open_percentage", "open_set"}),
            "sensor_air": frozenset(
                {"co2", "hcho_float", "humidity", "pm10", "pm1_0", "pm2_5", "temperature", "tvoc_float"}
            ),
            "sensor_temp": frozenset({"humidity", "temperature"}),
            "valve": frozenset({"open_percentage", "open_set"}),
            "window_blind": frozenset({"open_percentage", "open_set"}),
        }
        assert expected == CATEGORY_CONDITIONAL_FEATURES

    def test_categories_without_a_group_are_absent_not_empty(self) -> None:
        """Отсутствие ключа и пустая группа — разные вещи.

        Пустой ``frozenset()`` в таблице означал бы «нужна хотя бы одна
        из ничего» — условие, которое нельзя выполнить.  Валидатор
        отличает эти случаи, и таблица обязана быть на его стороне.
        """
        assert "light" not in CATEGORY_CONDITIONAL_FEATURES
        assert "relay" not in CATEGORY_CONDITIONAL_FEATURES
        assert all(group for group in CATEGORY_CONDITIONAL_FEATURES.values()), "пустая группа невыполнима"

    @pytest.mark.parametrize("category", sorted(CATEGORY_CONDITIONAL_FEATURES))
    def test_members_are_real_features(self, category: str) -> None:
        """Каждый член группы обязан быть настоящей функцией Sber.

        Опечатка в имени сделала бы правило невыполнимым: устройство
        никогда не смогло бы объявить несуществующую функцию, и мост
        ругался бы на исправные устройства вечно.
        """
        unknown = sorted(f for f in CATEGORY_CONDITIONAL_FEATURES[category] if f not in FEATURE_TYPES)
        assert unknown == [], f"{category}: функции нет в каталоге Sber — {unknown}"

    @pytest.mark.parametrize("category", sorted(CATEGORY_CONDITIONAL_FEATURES))
    def test_members_belong_to_the_category(self, category: str) -> None:
        """Член группы обязан входить в набор функций своей категории."""
        reference = CATEGORY_REFERENCE_FEATURES.get(category, frozenset())
        stray = sorted(CATEGORY_CONDITIONAL_FEATURES[category] - reference)
        assert stray == [], f"{category}: функция вне справочного набора — {stray}"

    @pytest.mark.parametrize("category", sorted(CATEGORY_CONDITIONAL_FEATURES))
    def test_never_overlaps_the_strict_table(self, category: str) -> None:
        """``✔︎`` и ``✔︎*`` взаимоисключающи.

        Функция, попавшая в обе таблицы, требовалась бы безусловно — и
        смягчение мая 2026 года, ради которого группы и появились,
        оказалось бы отменено втихую.
        """
        strict = CATEGORY_OBLIGATORY_FEATURES.get(category, frozenset())
        both = sorted(CATEGORY_CONDITIONAL_FEATURES[category] & strict)
        assert both == [], f"{category}: функция и обязательная, и условная — {both}"


class TestValidatorChecksDeclarationsNotStates:
    """Правило смотрит на объявленные функции, а не на состояния."""

    def test_impulse_gate_is_clean(self) -> None:
        """Импульсные ворота удовлетворяют правилу, ничего из группы не публикуя.

        Это главный регресс-тест всей затеи.  ``open_set`` — командная
        функция, состояния у неё нет, поэтому в публикации её никогда не
        будет.  Проверяй правило по состояниям — и каждые импульсные
        ворота (issue #53) получили бы ошибку на ровном месте.
        """
        assert _types("switch.gate", "gate", [ONLINE_STATE, OPEN_STATE], ["online", "open_set", "open_state"]) == []

    def test_gate_without_any_way_to_open_is_flagged(self) -> None:
        """Ворота, не объявившие ни одного способа открытия, — ошибка.

        Ровно это Sber молча отбрасывает, и ровно этого мост до сих пор
        не замечал.
        """
        issues = validate_publish(
            entity_id="switch.gate",
            category="gate",
            states=[ONLINE_STATE, OPEN_STATE],
            declared_features=["online", "open_state"],
        )
        conditional = [i for i in issues if i.type == "missing_conditional"]
        assert len(conditional) == 1, "ровно одна ошибка на группу, а не по одной на каждого члена"
        issue = conditional[0]
        assert issue.severity == "error"
        assert issue.key is None, "ошибка относится к группе целиком, а не к конкретной функции"
        assert issue.details == {"expected_any_of": ["open_percentage", "open_set"]}
        assert "open_percentage" in issue.description
        assert "open_set" in issue.description

    def test_curtain_with_percentage_is_clean(self) -> None:
        """Второй член группы засчитывается наравне с первым."""
        assert (
            _types("cover.c", "curtain", [ONLINE_STATE, OPEN_STATE], ["online", "open_percentage", "open_state"]) == []
        )

    def test_both_members_are_clean(self) -> None:
        """«Либо одно, либо другое, либо оба» — оба тоже допустимы."""
        declared = ["online", "open_percentage", "open_set", "open_state"]
        assert _types("cover.c", "curtain", [ONLINE_STATE, OPEN_STATE], declared) == []

    def test_unknown_declarations_stay_silent(self) -> None:
        """Без списка объявленных функций правило молчит, а не гадает.

        Синтетические полезные нагрузки (DevTools, реплей) приходят без
        конфигурации устройства.  Ругаться на них — значит завалить
        журнал ложными ошибками.
        """
        assert "missing_conditional" not in _types("switch.gate", "gate", [ONLINE_STATE, OPEN_STATE], None)

    def test_category_without_a_group_is_never_flagged(self) -> None:
        """У категории без ``✔︎*`` правило не срабатывает никогда."""
        assert "missing_conditional" not in _types("light.l", "light", [ONLINE_STATE], ["online", "on_off"])

    def test_unknown_category_is_never_flagged(self) -> None:
        """Незнакомая категория не должна порождать ошибку правила."""
        assert "missing_conditional" not in _types("x.y", "no_such_category", [ONLINE_STATE], ["online"])

    @pytest.mark.parametrize("member", ["temperature", "humidity"])
    def test_sensor_temp_needs_just_one_measurement(self, member: str) -> None:
        """Датчику температуры достаточно одного из двух измерений.

        Смягчение мая 2026 года: датчик, умеющий только температуру,
        обязан считаться исправным.  Иначе мост начнёт браковать самый
        массовый тип устройства в интеграции.
        """
        assert _types("sensor.t", "sensor_temp", [ONLINE_STATE], ["online", member]) == []

    def test_sensor_temp_measuring_nothing_is_flagged(self) -> None:
        """Датчик без единого измерения бесполезен и будет отброшен."""
        assert _types("sensor.t", "sensor_temp", [ONLINE_STATE], ["online"]) == ["missing_conditional"]


class TestOurOwnDevicesSatisfyTheRule:
    """Живой guard: наши классы устройств обязаны правилу удовлетворять."""

    @pytest.mark.parametrize("category", sorted(CATEGORY_CONDITIONAL_FEATURES))
    def test_every_category_declares_a_group_member(self, category: str) -> None:
        """Каждая наша категория с группой объявляет хотя бы одного члена.

        Тест ловит не чужую документацию, а собственную регрессию: если
        рефакторинг выкинет ``open_set`` у ворот или измерение у датчика
        воздуха, устройства перестанут приниматься облаком молча — без
        ошибки в журнале и без падения любого другого теста.
        """
        from custom_components.sber_mqtt_bridge.sber_entity_map import CATEGORY_DOMAIN_MAP

        spec = CATEGORY_DOMAIN_MAP[category]
        device_class = (spec.device_classes or ("",))[0]
        entity = spec.cls(
            {
                "entity_id": f"{spec.domains[0]}.probe",
                "name": "Probe",
                "original_device_class": device_class,
                "device_class": device_class,
            }
        )
        # Measurement categories carry their reading in the entity *state*,
        # not in an attribute — a probe stuck on "on" would leave every
        # field empty and fail for the wrong reason.
        state = "600" if spec.domains[0] == "sensor" else "on"
        entity.fill_by_ha_state(
            {
                "state": state,
                "attributes": {
                    # Home Assistant repeats device_class in the state
                    # attributes, and that is where the air sensor reads it
                    # from to decide which measurement it is holding.
                    "device_class": device_class,
                    "current_position": 60,
                    "current_temperature": 21,
                    "temperature": 21,
                    "humidity": 45,
                },
            }
        )
        declared = set(entity.get_final_features_list())
        group = CATEGORY_CONDITIONAL_FEATURES[category]
        assert group & declared, (
            f"{category}: не объявлено ни одного из {sorted(group)} — Sber молча отбросит устройство"
        )
