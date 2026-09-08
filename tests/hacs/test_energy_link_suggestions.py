"""Автопривязка энергосенсоров умной розетки (мощность / напряжение / ток).

Что проверяется и что ломается у пользователя, если тесты упадут:

* Розетка Zigbee2MQTT / Tuya / Shelly отдаёт мощность, напряжение и ток
  **отдельными сущностями** ``sensor.*`` того же HA-устройства, а не
  атрибутами выключателя.  Если мастер не предложит их связать, в
  приложении Сбера у розетки не будет ни ватт, ни вольт, ни ампер —
  ровно та дыра, из-за которой пользователь держал вторую интеграцию.
* Накопленная энергия (``device_class: energy``, кВт·ч) — это НЕ
  мощность.  Если она попадёт в кандидаты, Сберу уедет счётчик расхода
  вместо текущей мощности.
* На многоканальной колодке (2–4 розетки в одном HA-устройстве) у
  каждого канала свой сенсор мощности.  Если мастер предложит один и тот
  же сенсор всем каналам — пользователь увидит в приложении мощность
  соседней розетки, а ``add_ha_device`` вообще откажет с ``role_conflict``.
* Сенсор мощности **чужого** HA-устройства не должен оказаться
  предвыбранным ни в мастере, ни в ``auto_link_all``: иначе розетка
  начнёт отчитываться о потреблении другого прибора.

Имена ролей ``power`` / ``voltage`` / ``current`` здесь записаны
литералами намеренно.  Это идентификаторы функций из спецификации Sber,
а не производная от нашего кода: если взять их из
``SocketEntity.LINKABLE_ROLES``, то удаление ролей из ядра сделает
проверки пустыми и молча зелёными вместо того, чтобы уронить тесты.
Бэкенд мастера при этом имён ролей не хардкодит — он читает
``LINKABLE_ROLES`` примари, — так что тесты проверяют именно связку
«ядро объявило роль → мастер её предлагает».
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _ws_dispatch import dispatch

from custom_components.sber_mqtt_bridge.const import CONF_ENTITY_LINKS
from custom_components.sber_mqtt_bridge.device_grouper import HaDeviceGrouper
from custom_components.sber_mqtt_bridge.devices.socket_entity import SocketEntity
from custom_components.sber_mqtt_bridge.websocket_api.devices_grouped import ws_suggest_links
from custom_components.sber_mqtt_bridge.websocket_api.links import ws_auto_link_all

ENERGY_ROLES: frozenset[str] = frozenset({"power", "voltage", "current"})
"""Имена трёх энергетических функций Sber-розетки.

Совпадают с HA ``device_class`` тех же величин, поэтому отдельная
таблица соответствия не нужна."""


# ---------------------------------------------------------------------------
# Заглушки реестров HA (тот же приём, что в test_device_grouper.py)
# ---------------------------------------------------------------------------


def _make_device(device_id: str, *, name: str = "", disabled_by: str | None = None) -> MagicMock:
    device = MagicMock()
    device.id = device_id
    device.name = name or device_id
    device.name_by_user = None
    device.manufacturer = ""
    device.model = ""
    device.area_id = None
    device.disabled_by = disabled_by
    device.identifiers = set()
    return device


def _make_entity(
    entity_id: str,
    *,
    device_id: str | None = None,
    original_device_class: str | None = None,
    disabled: bool = False,
) -> MagicMock:
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.domain = entity_id.split(".")[0]
    entry.device_id = device_id
    entry.original_device_class = original_device_class
    entry.device_class = None
    entry.name = None
    entry.original_name = entity_id.split(".")[1]
    entry.area_id = None
    entry.disabled_by = "user" if disabled else None
    entry.disabled = disabled
    entry.hidden_by = None
    entry.entity_category = None
    entry.platform = "mqtt"
    entry.unique_id = entity_id
    return entry


@pytest.fixture
def hass() -> MagicMock:
    hass_ = MagicMock()
    hass_.config_entries.async_update_entry = MagicMock()
    hass_.config_entries.async_reload = AsyncMock()
    return hass_


@pytest.fixture
def mock_registries():
    """Подменяет три реестра HA на уровне модуля ``device_grouper``."""
    with (
        patch("custom_components.sber_mqtt_bridge.device_grouper.er") as mock_er,
        patch("custom_components.sber_mqtt_bridge.device_grouper.dr") as mock_dr,
        patch("custom_components.sber_mqtt_bridge.device_grouper.ar") as mock_ar,
    ):
        entity_reg = MagicMock()
        entity_reg.entities = {}
        mock_er.async_get.return_value = entity_reg
        device_reg = MagicMock()
        device_reg.devices = {}
        device_reg.async_get.side_effect = lambda did: device_reg.devices.get(did)
        mock_dr.async_get.return_value = device_reg
        area_reg = MagicMock()
        area_reg.async_get_area.side_effect = lambda _aid: None
        mock_ar.async_get.return_value = area_reg
        yield entity_reg, device_reg


def _load(entity_reg, device_reg, devices, entities) -> None:
    device_reg.devices = {d.id: d for d in devices}
    device_reg.async_get.side_effect = lambda did: device_reg.devices.get(did)
    entity_reg.entities = {e.entity_id: e for e in entities}
    entity_reg.async_get.side_effect = lambda eid: entity_reg.entities.get(eid)


# ---------------------------------------------------------------------------
# Реалистичные наборы устройств
# ---------------------------------------------------------------------------


def _z2m_plug() -> tuple[list[MagicMock], list[MagicMock]]:
    """Розетка Zigbee2MQTT TS011F: выключатель + 4 сенсора."""
    devices = [_make_device("plug_dev", name="Plug")]
    entities = [
        _make_entity("switch.plug", device_id="plug_dev", original_device_class="outlet"),
        _make_entity("sensor.plug_power", device_id="plug_dev", original_device_class="power"),
        _make_entity("sensor.plug_voltage", device_id="plug_dev", original_device_class="voltage"),
        _make_entity("sensor.plug_current", device_id="plug_dev", original_device_class="current"),
        _make_entity("sensor.plug_energy", device_id="plug_dev", original_device_class="energy"),
        _make_entity("sensor.plug_linkquality", device_id="plug_dev", original_device_class="signal_strength"),
    ]
    return devices, entities


def _two_gang_strip() -> tuple[list[MagicMock], list[MagicMock]]:
    """Двухканальная колодка: у каждого канала свой сенсор мощности."""
    devices = [_make_device("strip_dev", name="Strip")]
    entities = [
        _make_entity("switch.strip_l1", device_id="strip_dev", original_device_class="outlet"),
        _make_entity("switch.strip_l2", device_id="strip_dev", original_device_class="outlet"),
        _make_entity("sensor.strip_l1_power", device_id="strip_dev", original_device_class="power"),
        _make_entity("sensor.strip_l2_power", device_id="strip_dev", original_device_class="power"),
    ]
    return devices, entities


def _preselected(group, role: str) -> list[str]:
    return [e.entity_id for e in group.linked_native if e.link_role == role and e.preselected]


# ---------------------------------------------------------------------------
# Мастер: список кандидатов и предвыбор
# ---------------------------------------------------------------------------


class TestWizardOffersEnergySensors:
    def test_power_voltage_current_are_offered_and_preselected(self, hass, mock_registries) -> None:
        """Три энергосенсора розетки должны быть предложены с галочками.

        Упадёт — пользователь добавит розетку через мастер и не получит
        в приложении Сбера ни мощности, ни напряжения, ни тока.
        """
        entity_reg, device_reg = mock_registries
        _load(entity_reg, device_reg, *_z2m_plug())

        group = HaDeviceGrouper(hass).list_for_category("socket")[0]

        by_role = {e.link_role: e for e in group.linked_native}
        assert by_role["power"].entity_id == "sensor.plug_power"
        assert by_role["voltage"].entity_id == "sensor.plug_voltage"
        assert by_role["current"].entity_id == "sensor.plug_current"
        assert all(by_role[role].preselected for role in ENERGY_ROLES)

    def test_accepted_roles_are_exposed_to_the_panel(self, hass, mock_registries) -> None:
        """Панель должна узнать полный список ролей, которые берёт розетка.

        Из него рисуется шаг мастера «сенсоры энергомониторинга» — с
        пустыми слотами для ролей, под которые кандидатов не нашлось.
        Упадёт — панели нечем отличить «сенсора нет» от «роль не
        поддерживается», и шаг мастера построить нельзя.
        """
        entity_reg, device_reg = mock_registries
        _load(entity_reg, device_reg, *_z2m_plug())

        group = HaDeviceGrouper(hass).list_for_category("socket")[0]

        assert set(group.accepted_roles) >= ENERGY_ROLES
        assert set(group.to_dict()["accepted_roles"]) >= ENERGY_ROLES

    def test_cumulative_energy_sensor_is_never_a_link_candidate(self, hass, mock_registries) -> None:
        """``sensor.plug_energy`` (кВт·ч) — расход, а не мощность.

        Упадёт — в приложении Сбера в поле «текущая мощность» поедет
        накопленный расход за всё время, то есть заведомо неверные ватты.
        """
        entity_reg, device_reg = mock_registries
        _load(entity_reg, device_reg, *_z2m_plug())

        group = HaDeviceGrouper(hass).list_for_category("socket")[0]

        assert "sensor.plug_energy" not in {e.entity_id for e in group.linked_native}
        assert "sensor.plug_energy" not in {e.entity_id for e in group.linked_compatible}
        assert "sensor.plug_energy" in {e.entity_id for e in group.unsupported}

    def test_each_channel_gets_its_own_power_sensor(self, hass, mock_registries) -> None:
        """На двухканальной колодке предвыбирается сенсор своего канала.

        Упадёт — мастер отметит галочками оба сенсора мощности сразу, и
        ``add_ha_device`` откажет с ``role_conflict``; а если конфликт
        разрулит пользователь наугад — розетка L1 покажет мощность L2.
        """
        entity_reg, device_reg = mock_registries
        _load(entity_reg, device_reg, *_two_gang_strip())

        group = HaDeviceGrouper(hass).list_for_category("socket")[0]

        assert group.primary.entity_id == "switch.strip_l1"
        assert _preselected(group, "power") == ["sensor.strip_l1_power"]
        # Сенсор соседнего канала всё равно предложен — но без галочки,
        # чтобы пользователь мог переназначить его вручную.
        assert "sensor.strip_l2_power" in {e.entity_id for e in group.linked_native}

    def test_ambiguous_candidates_are_offered_but_not_preselected(self, hass, mock_registries) -> None:
        """Если по имени канал не угадать — не предвыбираем ничего.

        Молча выбрать «первый попавшийся» из двух сенсоров мощности
        нельзя: в половине случаев это чужая нагрузка.  Упадёт —
        вернётся угадайка вместо явного выбора пользователя.
        """
        entity_reg, device_reg = mock_registries
        _load(
            entity_reg,
            device_reg,
            [_make_device("meter_dev", name="Meter")],
            [
                _make_entity("switch.socket", device_id="meter_dev", original_device_class="outlet"),
                _make_entity("sensor.channel_a_power", device_id="meter_dev", original_device_class="power"),
                _make_entity("sensor.channel_b_power", device_id="meter_dev", original_device_class="power"),
            ],
        )

        group = HaDeviceGrouper(hass).list_for_category("socket")[0]

        assert _preselected(group, "power") == []
        assert {e.entity_id for e in group.linked_native if e.link_role == "power"} == {
            "sensor.channel_a_power",
            "sensor.channel_b_power",
        }


class TestForeignSensorsAreNotForced:
    def test_power_sensor_of_another_device_is_not_offered_at_all(self, hass, mock_registries) -> None:
        """Ваттметр чужого прибора не попадает в кандидаты вообще.

        Батарейку или градусник соседнего HA-устройства предложить
        осмысленно (батарейный отсек привода штор часто отдельный узел),
        а ваттметр меряет ровно ту розетку, в которую впаян.  Если
        пускать их в кросс-девайсные кандидаты, то на 20 счётчиках в
        доме карточка КАЖДОГО обычного выключателя получает 60 лишних
        строк, и мастер рисует их в блоке «Энергомониторинг» — то есть
        приглашает отметить ваттметр соседнего прибора.

        Упадёт — вернётся и мусор в карточках, и раздутый WS-ответ шага
        мастера.  Ручная привязка внешнего счётчика остаётся доступной
        через диалог связей.
        """
        entity_reg, device_reg = mock_registries
        _load(
            entity_reg,
            device_reg,
            [_make_device("plug_dev", name="Plug"), _make_device("meter_dev", name="Meter")],
            [
                _make_entity("switch.plug", device_id="plug_dev", original_device_class="outlet"),
                # Имя нарочно совпадает с розеткой — совпадение имён не
                # должно давать привязку, раз устройство другое.
                _make_entity("sensor.plug_power", device_id="meter_dev", original_device_class="power"),
            ],
        )

        group = HaDeviceGrouper(hass).list_for_category("socket")[0]

        assert group.linked_native == []
        assert group.linked_compatible == []

    def test_plain_relay_without_a_meter_gets_no_candidates(self, hass, mock_registries) -> None:
        """Обычное реле рядом с чужими счётчиками остаётся чистым.

        Роли ``power`` / ``voltage`` / ``current`` объявлены у
        ``RelayEntity``, то есть их берут ОБЕ категории — и ``socket``, и
        ``relay``.  Упадёт — на доме с десятком розеток-счётчиков
        карточка каждого обычного выключателя в мастере обрастёт
        десятками чужих строк, и блок «Энергомониторинг» предложит
        отметить ваттметр соседнего прибора.
        """
        entity_reg, device_reg = mock_registries
        plug_devices, plug_entities = _z2m_plug()
        _load(
            entity_reg,
            device_reg,
            [*plug_devices, _make_device("relay_dev", name="Relay")],
            [*plug_entities, _make_entity("switch.relay", device_id="relay_dev")],
        )

        groups = HaDeviceGrouper(hass).list_for_category("relay")
        relay_group = next(g for g in groups if g.primary.entity_id == "switch.relay")

        assert relay_group.linked_native == []
        assert relay_group.linked_compatible == []
        # Роли всё равно объявлены — привязать внешний счётчик руками
        # через диалог связей по-прежнему можно.
        assert set(relay_group.accepted_roles) >= ENERGY_ROLES

    def test_orphan_socket_still_announces_its_roles(self, hass, mock_registries) -> None:
        """Розетка без HA-устройства (template, SmartIR) — тоже розетка.

        У такой сущности нет ни соседей, ни устройства, поэтому связывать
        автоматически нечего.  Но список ролей панель обязана получить,
        иначе шаг «энергомониторинг» для неё не построить и привязать
        сенсор руками будет некуда.  Упадёт — карточка такой розетки
        поедет в панель в другой форме, чем все остальные.
        """
        entity_reg, device_reg = mock_registries
        _load(
            entity_reg,
            device_reg,
            [],
            [_make_entity("switch.template_plug", device_id=None, original_device_class="outlet")],
        )

        group = HaDeviceGrouper(hass).list_for_category("socket")[0]

        assert group.device_id == "switch.template_plug"
        assert set(group.accepted_roles) >= ENERGY_ROLES
        assert set(group.to_dict()["accepted_roles"]) >= ENERGY_ROLES
        assert group.linked_native == []
        assert group.linked_compatible == []


# ---------------------------------------------------------------------------
# WS: suggest_links (перередактирование уже добавленной розетки)
# ---------------------------------------------------------------------------


async def _suggest(hass, entity_id: str, *, existing_links: dict[str, dict[str, str]] | None = None) -> dict:
    """Вызвать ``suggest_links``, опционально с уже сохранёнными связями.

    Args:
        hass: Заглушка HA.
        entity_id: Сущность, для которой открыт диалог связей.
        existing_links: Содержимое ``bridge.entity_links``; ``None`` —
            моста нет вовсе (мастер до добавления устройства).

    Returns:
        Тело WS-ответа.
    """
    connection = MagicMock()
    bridge = None
    if existing_links is not None:
        bridge = MagicMock()
        bridge.entity_links = existing_links
    with (
        patch(
            "custom_components.sber_mqtt_bridge.websocket_api.devices_grouped.get_bridge",
            return_value=bridge,
        ),
        patch("homeassistant.helpers.entity_registry.async_get") as ha_er,
    ):
        from custom_components.sber_mqtt_bridge import device_grouper as dg

        ha_er.return_value = dg.er.async_get(hass)
        await dispatch(ws_suggest_links, hass, connection, {"id": 1, "entity_id": entity_id, "category": "socket"})
    return connection.send_result.call_args[0][1]


class TestSuggestLinksForExistingSocket:
    async def test_candidates_belong_to_the_requested_channel(self, hass, mock_registries) -> None:
        """Диалог связей открыт для L2 — значит и предвыбор для L2.

        Упадёт — при правке второй розетки колодки диалог предложит
        сенсоры первой, и пользователь свяжет чужую мощность.
        """
        entity_reg, device_reg = mock_registries
        _load(entity_reg, device_reg, *_two_gang_strip())

        result = await _suggest(hass, "switch.strip_l2")

        preselected = [c["entity_id"] for c in result["candidates"] if c["preselected"]]
        assert preselected == ["sensor.strip_l2_power"]
        # Соседний канал — самостоятельная Sber-розетка, а не сенсор.
        assert "switch.strip_l1" not in {c["entity_id"] for c in result["candidates"]}

    async def test_accepted_roles_are_returned(self, hass, mock_registries) -> None:
        """Диалогу нужен полный список ролей розетки, а не только занятые.

        Упадёт — в диалоге нельзя будет назначить роль сенсору, для
        которой кандидатов не нашлось автоматически.
        """
        entity_reg, device_reg = mock_registries
        _load(entity_reg, device_reg, *_z2m_plug())

        result = await _suggest(hass, "switch.plug")

        assert set(result["accepted_roles"]) >= ENERGY_ROLES

    async def test_a_role_linked_by_hand_is_not_suggested_again(self, hass, mock_registries) -> None:
        """Что человек выбрал руками, бэкенд не переигрывает.

        Пользователь мог сознательно завести мощность розетки на внешний
        клещевой ваттметр.  Диалог связей отмечает галочками сначала
        сохранённые связи, потом подсказки ``preselected`` — и если
        подсказка придёт на уже занятую роль, в ответ уедут ДВЕ сущности
        на одну роль, то есть ``role_conflict`` при сохранении.
        Упадёт — открыть диалог связей у розетки с ручной привязкой
        станет нельзя без переделки выбора вручную.
        """
        entity_reg, device_reg = mock_registries
        _load(entity_reg, device_reg, *_z2m_plug())

        result = await _suggest(
            hass,
            "switch.plug",
            existing_links={"switch.plug": {"power": "sensor.external_meter"}},
        )

        by_id = {c["entity_id"]: c for c in result["candidates"]}
        assert by_id["sensor.plug_power"]["preselected"] is False
        # Остальные роли свободны — их подсказки на месте.
        assert by_id["sensor.plug_voltage"]["preselected"] is True
        assert by_id["sensor.plug_current"]["preselected"] is True


# ---------------------------------------------------------------------------
# WS: auto_link_all
# ---------------------------------------------------------------------------


async def _auto_link(hass, entity_reg, exposed: dict[str, object], options: dict) -> dict:
    connection = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry"
    entry.options = options
    bridge = MagicMock()
    bridge.entities = exposed
    module = "custom_components.sber_mqtt_bridge.websocket_api.links"
    with (
        patch(f"{module}.get_config_entry", return_value=entry),
        patch(f"{module}.get_bridge", return_value=bridge),
        patch(f"{module}.er") as mock_er,
    ):
        mock_er.async_get.return_value = entity_reg
        await dispatch(ws_auto_link_all, hass, connection, {"id": 1})
    updated = hass.config_entries.async_update_entry.call_args
    return updated.kwargs["options"][CONF_ENTITY_LINKS] if updated else {}


class TestAutoLinkAll:
    async def test_each_socket_is_linked_to_its_own_channel(self, hass, mock_registries) -> None:
        """«Связать всё автоматически» не путает каналы колодки.

        Упадёт — обе розетки колодки получат один и тот же сенсор
        мощности, и в приложении Сбера они покажут одинаковые ватты.
        """
        entity_reg, device_reg = mock_registries
        _load(entity_reg, device_reg, *_two_gang_strip())
        exposed = {
            eid: SocketEntity({"entity_id": eid, "original_device_class": "outlet"})
            for eid in ("switch.strip_l1", "switch.strip_l2")
        }

        links = await _auto_link(hass, entity_reg, exposed, {})

        assert links == {
            "switch.strip_l1": {"power": "sensor.strip_l1_power"},
            "switch.strip_l2": {"power": "sensor.strip_l2_power"},
        }

    async def test_foreign_power_sensor_is_never_auto_linked(self, hass, mock_registries) -> None:
        """Автопривязка идёт только по общему HA-устройству.

        Упадёт — розетке автоматически прицепится ваттметр соседнего
        прибора, и пользователь этого даже не заметит.
        """
        entity_reg, device_reg = mock_registries
        _load(
            entity_reg,
            device_reg,
            [_make_device("plug_dev"), _make_device("meter_dev")],
            [
                _make_entity("switch.plug", device_id="plug_dev", original_device_class="outlet"),
                _make_entity("sensor.plug_power", device_id="meter_dev", original_device_class="power"),
            ],
        )
        exposed = {"switch.plug": SocketEntity({"entity_id": "switch.plug", "original_device_class": "outlet"})}

        links = await _auto_link(hass, entity_reg, exposed, {})

        assert links == {}

    async def test_single_plug_gets_all_three_energy_links(self, hass, mock_registries) -> None:
        """Обычная розетка получает мощность, напряжение и ток разом.

        Упадёт — кнопка «связать всё» перестанет закрывать главный
        сценарий, ради которого энергомониторинг и делался.
        """
        entity_reg, device_reg = mock_registries
        _load(entity_reg, device_reg, *_z2m_plug())
        exposed = {"switch.plug": SocketEntity({"entity_id": "switch.plug", "original_device_class": "outlet"})}

        links = await _auto_link(hass, entity_reg, exposed, {})

        assert links["switch.plug"]["power"] == "sensor.plug_power"
        assert links["switch.plug"]["voltage"] == "sensor.plug_voltage"
        assert links["switch.plug"]["current"] == "sensor.plug_current"
        assert "sensor.plug_energy" not in links["switch.plug"].values()

    async def test_ambiguous_power_sensors_are_left_unlinked(self, hass, mock_registries) -> None:
        """Два неразличимых сенсора мощности → не привязываем ничего.

        Осознанный компромисс: «первый попавшийся» в половине случаев
        оказался бы чужим каналом, и пользователь увидел бы в приложении
        Сбера правдоподобные, но неверные ватты — ошибку, которую почти
        невозможно заметить.  Упадёт (или начнёт возвращать связь) —
        вернулась угадайка; упадёт с исключением — кнопка «связать всё»
        перестанет работать целиком.
        """
        entity_reg, device_reg = mock_registries
        _load(
            entity_reg,
            device_reg,
            [_make_device("meter_dev")],
            [
                _make_entity("switch.socket", device_id="meter_dev", original_device_class="outlet"),
                _make_entity("sensor.channel_a_power", device_id="meter_dev", original_device_class="power"),
                _make_entity("sensor.channel_b_power", device_id="meter_dev", original_device_class="power"),
            ],
        )
        exposed = {"switch.socket": SocketEntity({"entity_id": "switch.socket", "original_device_class": "outlet"})}

        links = await _auto_link(hass, entity_reg, exposed, {})

        assert links == {}

    async def test_shelly_naming_single_channel_still_links(self, hass, mock_registries) -> None:
        """Схема имён Shelly (``..._relay_0`` + ``..._power``) — один канал.

        Тай-брейк по префиксу object_id тут не срабатывает: имя сенсора
        не начинается с имени выключателя.  Пока канал один, это неважно
        — единственный кандидат берётся без тай-брейка.  Тест фиксирует
        границу компромисса: на многоканальном Shelly предвыбора не
        будет вовсе (см. тест выше), и это лучше, чем угадать не тот
        канал.  Упадёт — самая распространённая однорозеточная Shelly
        перестанет получать мощность автоматически.
        """
        entity_reg, device_reg = mock_registries
        _load(
            entity_reg,
            device_reg,
            [_make_device("shelly_dev")],
            [
                _make_entity("switch.shellyplug_relay_0", device_id="shelly_dev", original_device_class="outlet"),
                _make_entity("sensor.shellyplug_power", device_id="shelly_dev", original_device_class="power"),
            ],
        )
        exposed = {
            "switch.shellyplug_relay_0": SocketEntity(
                {"entity_id": "switch.shellyplug_relay_0", "original_device_class": "outlet"}
            )
        }

        links = await _auto_link(hass, entity_reg, exposed, {})

        assert links == {"switch.shellyplug_relay_0": {"power": "sensor.shellyplug_power"}}
