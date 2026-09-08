"""Две законные причины не публиковать заявленную функцию.

Обе найдены на живом стенде: панель показала предупреждения
``declared_not_published`` там, где мост вёл себя правильно, — и там,
где он вёл себя неправильно, но починить надо было не публикацию.

* **Выключенный кондиционер и ``hvac_work_mode``.** В словаре Sber нет
  значения «выключено»: он предлагает cooling / heating / ventilation и
  прочие режимы работы, а состояние «выключен» передаётся отдельной
  функцией ``on_off``. Выключенный прибор может либо промолчать, либо
  выдумать режим, в котором не находится. Мост молчит — и предупреждать
  об этом не за что.

* **Умная колонка и ``channel_int``.** Здесь наоборот: предупреждение
  было по делу, но лечится оно снятием функции, а не публикацией.
  Каналов у колонки нет и не будет, так что значение взять неоткуда, а
  объявленная функция превращается в элемент управления, который
  никогда не оживёт.
"""

from __future__ import annotations

import pytest

from custom_components.sber_mqtt_bridge.devices.tv import CHANNELLESS_DEVICE_CLASSES
from custom_components.sber_mqtt_bridge.sber_entity_map import CATEGORY_DOMAIN_MAP
from custom_components.sber_mqtt_bridge.schema_validator import validate_publish

_AC_ATTRS = {
    "hvac_modes": ["cool", "heat", "off"],
    "temperature": 24,
    "current_temperature": 26,
    "min_temp": 16,
    "max_temp": 30,
    "fan_modes": ["auto", "low"],
    "fan_mode": "auto",
}
"""Обычный кондиционер: столько атрибутов отдаёт любая интеграция."""


def _publish(category: str, domain: str, attrs: dict, state: str) -> tuple[list[str], list, list[str]]:
    """Собрать сущность и провести её публикацию через валидатор.

    Args:
        category: Категория Sber из :data:`CATEGORY_DOMAIN_MAP`.
        domain: Домен HA для ``entity_id``.
        attrs: Атрибуты состояния HA.
        state: Состояние HA.

    Returns:
        Тройка «объявленные функции, замечания валидатора,
        опубликованные ключи».
    """
    entity = CATEGORY_DOMAIN_MAP[category].cls(
        {"entity_id": f"{domain}.probe", "name": "Probe", "original_device_class": "", "device_class": ""}
    )
    entity.fill_by_ha_state({"state": state, "attributes": attrs})
    declared = [getattr(f, "value", f) for f in entity.get_final_features_list()]
    states = [
        {"key": getattr(item["key"], "value", item["key"]), "value": item["value"]}
        for payload in entity.to_sber_current_state().values()
        for item in payload["states"]
    ]
    issues = validate_publish(
        entity_id=f"{domain}.probe",
        category=category,
        states=states,
        declared_features=declared,
        check_completeness=True,
    )
    return declared, issues, [s["key"] for s in states]


class TestSwitchedOffAppliance:
    """Выключенный прибор не обязан сообщать режим работы."""

    def test_off_air_conditioner_raises_no_warning(self) -> None:
        """Выключенный кондиционер не даёт замечаний.

        Именно это видел владелец на своём стенде: два выключенных
        кондиционера были помечены предупреждением, хотя работали
        штатно. Если тест упадёт, панель снова начнёт обвинять
        исправную технику, и настоящие находки утонут в шуме.
        """
        declared, issues, published = _publish("hvac_ac", "climate", _AC_ATTRS, "off")

        assert "hvac_work_mode" in declared, "функция объявляется — это не изменилось"
        assert "hvac_work_mode" not in published, "у выключенного прибора режима нет"
        assert [i.type for i in issues] == [], f"ожидалась тишина, получено: {[(i.type, i.key) for i in issues]}"

    def test_running_air_conditioner_publishes_its_mode(self) -> None:
        """Включённый кондиционер режим публикует.

        Поблажка не должна превратиться в дыру: работающий прибор обязан
        сообщать режим, иначе в приложении будет мёртвый переключатель.
        """
        _, issues, published = _publish("hvac_ac", "climate", {**_AC_ATTRS, "hvac_mode": "cool"}, "cool")

        assert "hvac_work_mode" in published
        assert [i.type for i in issues] == []

    def test_exemption_needs_on_off_to_say_false(self) -> None:
        """Поблажка действует только при явном ``on_off: false``.

        Публикация, в которой ``on_off`` вообще нет, ничего не говорит о
        том, выключен ли прибор, и молчание о режиме в ней остаётся
        поводом для замечания.
        """
        issues = validate_publish(
            entity_id="climate.no_on_off",
            category="hvac_ac",
            states=[{"key": "online", "value": {"type": "BOOL", "bool_value": True}}],
            declared_features=["online", "on_off", "hvac_temp_set", "hvac_work_mode"],
            check_completeness=True,
        )

        assert "hvac_work_mode" in [i.key for i in issues if i.type == "declared_not_published"]


class TestChannellessMediaPlayers:
    """Колонке не нужен номер канала."""

    @pytest.mark.parametrize("device_class", sorted(CHANNELLESS_DEVICE_CLASSES))
    def test_speaker_does_not_advertise_channel_int(self, device_class: str) -> None:
        """Колонка и ресивер не объявляют ``channel_int``.

        На стенде владельца две Яндекс.Станции были помечены
        предупреждением: функция объявлена, а значения для неё не
        существует в природе. Если тест упадёт, в приложении Сбера у
        колонок снова появится номер канала, который никогда не
        обновится.
        """
        declared, issues, _ = _publish(
            "tv",
            "media_player",
            {"volume_level": 0.3, "is_volume_muted": False, "device_class": device_class},
            "playing",
        )

        assert "channel_int" not in declared
        assert [i.type for i in issues] == []

    def test_television_keeps_channel_int(self) -> None:
        """Телевизору номер канала оставляем."""
        declared, _, published = _publish(
            "tv",
            "media_player",
            {
                "volume_level": 0.3,
                "is_volume_muted": False,
                "device_class": "tv",
                "media_content_id": "5",
                "media_content_type": "channel",
            },
            "playing",
        )

        assert "channel_int" in declared
        assert "channel_int" in published

    def test_missing_device_class_keeps_channel_int(self) -> None:
        """Без указанного класса устройства функцию не отнимаем.

        Многие интеграции класс не проставляют вовсе. Отнять у них
        рабочий элемент управления хуже, чем оставить его там, где он не
        пригодится: неизвестность — не повод считать устройство
        колонкой.
        """
        declared, _, published = _publish(
            "tv",
            "media_player",
            {"volume_level": 0.3, "is_volume_muted": False, "media_content_id": "7"},
            "playing",
        )

        assert "channel_int" in declared
        assert "channel_int" in published
