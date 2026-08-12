"""Регистрация импульсных ворот (issue #53): карта категорий, реестр ролей, мастер.

Файл покрывает три границы, через которые пара «импульсное реле + геркон»
попадает в облако Sber:

1. :data:`CATEGORY_DOMAIN_MAP` / :func:`categories_for_domain` — какие
   категории предлагаются для домена и что автодетект НЕ меняется;
2. реестр :data:`ALL_LINKABLE_ROLES` — новая роль ``open_state`` и её
   изоляция от остальных категорий;
3. мастер (:class:`HaDeviceGrouper`) и ``sber_mqtt_bridge/add_ha_device`` —
   классификация геркона и обязательность связи.

Юнит-тесты самого класса ``ImpulseGateEntity`` (фичи, allowed_values,
команды, cooldown) живут отдельно; здесь проверяется только «проводка».

Ожидания выведены из дизайна issue #53 и из спеки Sber ``gate``, а не из
текущего вывода кода: каждое утверждение — точное значение или полное
множество, чтобы мутация исходника роняла тест.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from _ws_dispatch import dispatch

from custom_components.sber_mqtt_bridge.device_grouper import (
    DeviceGroup,
    EntityRole,
    HaDeviceGrouper,
)
from custom_components.sber_mqtt_bridge.devices.base_entity import (
    ALL_LINKABLE_ROLES,
    GATE_LINK_ROLES,
    ROLE_OPEN_STATE,
    ROLE_SIGNAL,
    BaseEntity,
    LinkableRole,
    resolve_link_role,
)
from custom_components.sber_mqtt_bridge.devices.gate import (
    GateEntity,
    ImpulseGateEntity,
    make_gate_entity,
)
from custom_components.sber_mqtt_bridge.sber_entity_map import (
    CATEGORY_DOMAIN_MAP,
    CategorySpec,
    categories_for_domain,
    create_sber_entity,
)
from custom_components.sber_mqtt_bridge.websocket_api.devices_grouped import ws_add_ha_device
from custom_components.sber_mqtt_bridge.websocket_api.status import ws_device_detail

_WS_MODULE = "custom_components.sber_mqtt_bridge.websocket_api.devices_grouped"

_STATUS_MODULE = "custom_components.sber_mqtt_bridge.websocket_api.status"

#: Реле импульсных ворот — первичная сущность Sber-устройства.
RELAY_ID = "switch.gate"
#: Геркон, единственный источник правды о положении створки.
CONTACT_ID = "binary_sensor.gate_contact"


# ---------------------------------------------------------------------------
# Хелперы: заглушки HA-реестров (те же, что в test_device_grouper.py, но
# локальные — файл обязан быть самодостаточным)
# ---------------------------------------------------------------------------


def _make_entity(
    entity_id: str,
    *,
    device_id: str | None = None,
    original_device_class: str | None = None,
    device_class: str | None = None,
    original_name: str | None = None,
    disabled_by: str | None = None,
) -> MagicMock:
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.domain = entity_id.split(".", 1)[0]
    entry.device_id = device_id
    entry.original_device_class = original_device_class
    # HA-овский «Show as»: None, пока пользователь не переопределил класс.
    entry.device_class = device_class
    entry.name = None
    entry.original_name = original_name
    entry.area_id = None
    entry.disabled_by = disabled_by
    entry.hidden_by = None
    entry.entity_category = None
    entry.platform = "test"
    entry.unique_id = entity_id
    return entry


def _make_device(device_id: str, *, name: str = "") -> MagicMock:
    device = MagicMock()
    device.id = device_id
    device.name = name or device_id
    device.name_by_user = None
    device.manufacturer = ""
    device.model = ""
    device.area_id = None
    device.disabled_by = None
    device.identifiers = set()
    return device


@pytest.fixture
def hass():
    """Заглушка ``hass`` с асинхронным перезапуском записи конфигурации.

    WebSocket-обработчики ворот пишут опции через
    ``config_entries.async_update_entry`` и просят перезагрузку, поэтому
    в тестах важны именно эти два вызова.
    """
    hass_ = MagicMock()
    hass_.config_entries.async_update_entry = MagicMock()
    hass_.config_entries.async_reload = AsyncMock()
    return hass_


@pytest.fixture
def connection():
    """Заглушка WebSocket-соединения: ловит ``send_result`` / ``send_error``."""
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


@pytest.fixture
def mock_registries():
    """Подменяет три HA-реестра внутри модуля ``device_grouper``."""
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
        yield entity_reg, device_reg, area_reg


def _load(entity_reg, device_reg, entities: list[MagicMock], devices: list[MagicMock]) -> None:
    entity_reg.entities = {e.entity_id: e for e in entities}
    device_reg.devices = {d.id: d for d in devices}
    device_reg.async_get.side_effect = lambda did: device_reg.devices.get(did)


def _group_for(hass_, category: str, device_id: str) -> DeviceGroup:
    """Единственная группа мастера для устройства ``device_id``."""
    groups = [g for g in HaDeviceGrouper(hass_).list_for_category(category) if g.device_id == device_id]
    assert len(groups) == 1, f"мастер вернул {len(groups)} групп для {device_id}/{category}"
    return groups[0]


def _entry(options: dict | None = None) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.options = options if options is not None else {}
    return entry


async def _add_device(
    hass_,
    connection_,
    *,
    entity_reg_map: dict[str, MagicMock],
    msg: dict,
    entry: MagicMock | None = None,
) -> MagicMock:
    """Прогоняет ``add_ha_device`` через настоящую цепочку декораторов."""
    entry = entry if entry is not None else _entry()
    entity_reg = MagicMock()
    entity_reg.async_get.side_effect = entity_reg_map.get
    bridge = MagicMock()
    bridge.is_connected = False
    with (
        patch(f"{_WS_MODULE}.get_config_entry", return_value=entry),
        patch(f"{_WS_MODULE}.get_bridge", return_value=bridge),
        patch("homeassistant.helpers.entity_registry.async_get", return_value=entity_reg),
    ):
        await dispatch(ws_add_ha_device, hass_, connection_, msg)
    return entry


# ---------------------------------------------------------------------------
# 1. Карта категорий
# ---------------------------------------------------------------------------


class TestCategoryPromotion:
    """Кто и в какую Sber-категорию продвигается после появления импульсных ворот."""

    def test_plain_switch_still_autodetects_as_relay(self):
        """Обычное реле обязано остаться relay, а gate — лишь ручной альтернативой.

        Если gate перехватит автодетект (например, вернут preferred_rank=3),
        КАЖДЫЙ голый switch у всех пользователей после обновления уедет в
        категорию «ворота»: пропадут выключатели, а Sber получит устройства
        с обязательной фичей open_state, которой у реле нет.
        """
        assert categories_for_domain("switch", None) == ["relay", "intercom", "gate", "kettle"]

    def test_switch_device_class_none_and_empty_string_behave_identically(self):
        """HA отдаёт отсутствующий device_class и как ``None``, и как ``""``.

        Расхождение между этими двумя формами означало бы, что gate виден в
        мастере для части реле и невидим для другой — «плавающий» баг.
        """
        assert categories_for_domain("switch", "") == categories_for_domain("switch", None)

    def test_outlet_switch_never_offers_gate(self):
        """Умная розетка не должна попадать в список «ворот».

        Fallback без device_class обязан срабатывать ТОЛЬКО при пустом
        device_class; иначе розетки и любые размеченные switch засорят
        Step 2 мастера воротами.
        """
        assert categories_for_domain("switch", "outlet") == ["socket", "relay", "intercom", "kettle"]

    def test_switch_marked_garage_door_offers_gate_without_stealing_autodetect(self):
        """switch с device_class=garage_door: gate доступен, но автодетект — relay.

        Это ровно сценарий issue #53 после того, как пользователь пометил
        реле в HA. Если бы gate стал первым, реле молча сменило бы Sber-
        категорию (и model.id) при обновлении интеграции.
        """
        result = categories_for_domain("switch", "garage_door")
        assert result == ["relay", "intercom", "gate", "kettle"]
        assert result[0] == "relay"

    @pytest.mark.parametrize("domain", ["button", "script"])
    def test_button_and_script_offer_relay_then_gate(self, domain):
        """Кнопка и скрипт — легальные источники импульса, но тоже не автодетектом.

        Падение = мастер не покажет button/script в категории «ворота»
        (пользователь не сможет добавить ворота на кнопке) либо, наоборот,
        все скрипты станут воротами.
        """
        assert categories_for_domain(domain, None) == ["relay", "gate"]

    def test_cover_without_device_class_is_curtain_only(self):
        """Голый cover обязан остаться шторой — gate туда не лезет.

        Ради этого и введено ``no_device_class_domains``. Если поле
        перестанет ограничивать fallback, у всех существующих пользователей
        безклассовые cover получат вторую категорию, а мастер начнёт
        предлагать шторы в списке ворот.
        """
        assert categories_for_domain("cover", None) == ["curtain"]
        assert categories_for_domain("cover", "") == ["curtain"]

    @pytest.mark.parametrize("device_class", ["gate", "garage_door", "garage", "door"])
    def test_cover_with_gate_device_class_maps_to_gate_only(self, device_class):
        """Классический HA-cover ворот адресуется ровно в gate — поведение до #53.

        Падение означает регресс уже работающей у пользователей связки
        cover→gate (сменится Sber-категория, облако потеряет устройство).
        """
        assert categories_for_domain("cover", device_class) == ["gate"]

    def test_binary_sensor_contact_is_not_promotable_to_gate(self):
        """Геркон сам по себе — не ворота, а датчик двери.

        Если геркон начнёт продвигаться в gate, пользователь добавит его
        отдельным Sber-устройством, и облако получит «ворота», которыми
        невозможно управлять.
        """
        assert categories_for_domain("binary_sensor", "garage_door") == ["sensor_door"]
        assert "gate" not in categories_for_domain("binary_sensor", "door")

    def test_gate_spec_shape_is_pinned(self):
        """Полная фиксация CategorySpec категории gate.

        Каждое поле здесь несёт нагрузку: ``domains[0] == "cover"`` держит
        probe-хелперы параметризованных тестов на старом пути, ранг 35
        удерживает gate вне автодетекта, ``no_device_class_domains``
        защищает cover.
        """
        spec = CATEGORY_DOMAIN_MAP["gate"]
        assert spec.cls is make_gate_entity
        assert spec.domains == ("cover", "switch", "button", "script")
        assert spec.domains[0] == "cover"
        assert spec.device_classes == ("gate", "garage_door", "garage", "door")
        assert spec.preferred_rank == 35
        assert spec.fallback_when_no_device_class is True
        assert spec.no_device_class_domains == ("switch", "button", "script")

    def test_gate_rank_is_worse_than_every_other_switch_category(self):
        """gate обязан быть последним по приоритету среди switch-категорий, кроме kettle.

        Инвариант, выведенный из рангов, а не из хардкода списка: если
        кто-то поднимет ранг gate, автодетект switch сменится молча.
        """
        gate_rank = CATEGORY_DOMAIN_MAP["gate"].preferred_rank
        assert gate_rank > CATEGORY_DOMAIN_MAP["relay"].preferred_rank
        assert gate_rank > CATEGORY_DOMAIN_MAP["intercom"].preferred_rank
        assert gate_rank > CATEGORY_DOMAIN_MAP["socket"].preferred_rank

    def test_factory_routes_cover_and_relay_to_different_classes(self):
        """Одна категория gate — два физически разных устройства.

        cover обязан оставаться :class:`GateEntity` (позиция, stop,
        неизменный model.id у действующих пользователей), всё остальное —
        :class:`ImpulseGateEntity`.
        """
        cover_entity = create_sber_entity("cover.gate", {"entity_id": "cover.gate"}, sber_category="gate")
        relay_entity = create_sber_entity(RELAY_ID, {"entity_id": RELAY_ID}, sber_category="gate")
        assert type(cover_entity) is GateEntity
        assert type(relay_entity) is ImpulseGateEntity
        assert cover_entity.category == "gate"
        assert relay_entity.category == "gate"


# ---------------------------------------------------------------------------
# 2. Новое поле no_device_class_domains
# ---------------------------------------------------------------------------


class TestNoDeviceClassDomains:
    """Поле обязано ограничивать fallback и ничего не менять там, где оно пустое."""

    def test_only_gate_restricts_its_fallback(self):
        """Ограничение введено точечно — остальные категории его не объявляют.

        Пустой кортеж = историческое поведение. Если ограничение приедет
        ещё куда-то (например, в relay), часть безклассовых сущностей
        перестанет распознаваться вообще.
        """
        restricted = {name for name, spec in CATEGORY_DOMAIN_MAP.items() if spec.no_device_class_domains}
        assert restricted == {"gate"}

    def test_empty_restriction_keeps_fallback_on_all_domains(self):
        """Для всех прочих fallback-категорий поведение обязано быть прежним.

        Проверяется прямым перебором: каждая категория с
        ``fallback_when_no_device_class`` и пустым ограничением принимает
        сущность без device_class в ЛЮБОМ своём домене.
        """
        for name, spec in CATEGORY_DOMAIN_MAP.items():
            if not spec.fallback_when_no_device_class or spec.no_device_class_domains:
                continue
            for domain in spec.domains:
                assert spec.matches(domain, None) is True, f"{name}/{domain} потерял fallback"
                assert spec.matches(domain, "") is True, f"{name}/{domain} потерял fallback"

    def test_restriction_limits_fallback_to_listed_domains_only(self):
        """Семантика поля на изолированном CategorySpec.

        Домен в списке принимает пустой device_class, домен вне списка —
        нет; явный device_class продолжает работать в обоих доменах.
        Если поле перестанет учитываться в ``matches``, тест поймает это
        независимо от содержимого CATEGORY_DOMAIN_MAP.
        """
        spec = CategorySpec(
            cls=make_gate_entity,
            domains=("cover", "switch"),
            device_classes=("gate",),
            fallback_when_no_device_class=True,
            no_device_class_domains=("switch",),
        )
        assert spec.matches("switch", "") is True
        assert spec.matches("switch", None) is True
        assert spec.matches("cover", "") is False
        assert spec.matches("cover", None) is False
        assert spec.matches("cover", "gate") is True
        assert spec.matches("switch", "gate") is True
        assert spec.matches("switch", "outlet") is False
        assert spec.matches("light", "") is False

    def test_restriction_alone_never_enables_fallback(self):
        """Без ``fallback_when_no_device_class`` перечень доменов ничего не открывает.

        Иначе список доменов стал бы вторым, неявным способом включить
        fallback — и категория начала бы ловить чужие сущности.
        """
        spec = CategorySpec(
            cls=make_gate_entity,
            domains=("switch",),
            device_classes=("gate",),
            fallback_when_no_device_class=False,
            no_device_class_domains=("switch",),
        )
        assert spec.matches("switch", "") is False
        assert spec.matches("switch", "gate") is True

    def test_domain_only_categories_ignore_the_restriction(self):
        """``device_classes=None`` означает «любой класс» — ограничение неприменимо.

        Если ограничение начнёт резать и такие категории, relay перестанет
        принимать голые switch, то есть отвалится базовый сценарий моста.
        """
        spec = CategorySpec(
            cls=make_gate_entity,
            domains=("switch", "script"),
            device_classes=None,
            fallback_when_no_device_class=True,
            no_device_class_domains=("switch",),
        )
        assert spec.matches("script", "") is True
        assert spec.matches("script", "whatever") is True


# ---------------------------------------------------------------------------
# 3. Реестр связываемых ролей
# ---------------------------------------------------------------------------


def _declared_pairs(role: LinkableRole) -> set[tuple[str, str]]:
    return {(domain, dc) for domain in role.domains for dc in role.device_classes}


class TestOpenStateRole:
    """Новая роль ``open_state`` и инварианты глобального реестра."""

    def test_role_shape_is_exact(self):
        """Полная фиксация домена и множества device_class роли.

        Расширение множества (например, ``window``) немедленно превратит
        оконные герконы в кандидатов на роль ворот; сужение — оставит
        часть пользователей без предложения связать датчик.
        """
        assert ROLE_OPEN_STATE.role == "open_state"
        assert ROLE_OPEN_STATE.domains == frozenset({"binary_sensor"})
        assert ROLE_OPEN_STATE.device_classes == frozenset({"garage_door", "door", "opening"})

    def test_role_is_registered_globally(self):
        """Роль обязана лежать в ``ALL_LINKABLE_ROLES``.

        Реестр собирается из констант, объявленных ВЫШЕ присваивания
        ``ALL_LINKABLE_ROLES``. Объявление ниже даёт молчаливый отказ:
        класс роль принимает, а мастер и ``resolve_link_role`` про неё не
        знают — геркон навсегда останется в «Not usable».
        """
        assert ROLE_OPEN_STATE in ALL_LINKABLE_ROLES
        assert [r.role for r in ALL_LINKABLE_ROLES].count("open_state") == 1

    @pytest.mark.parametrize("device_class", ["garage_door", "door", "opening"])
    def test_contact_resolves_to_open_state(self, device_class):
        """Три класса герконов ворот резолвятся именно в ``open_state``.

        Падение = мастер не предложит датчик, а ``add_ha_device`` отвергнет
        его как ``linked_role_not_accepted``: ворота станет невозможно
        добавить вообще (роль обязательная).
        """
        assert resolve_link_role("binary_sensor", device_class) == "open_state"

    @pytest.mark.parametrize(
        ("domain", "device_class"),
        [
            ("binary_sensor", "window"),
            ("binary_sensor", ""),
            ("binary_sensor", "motion"),
            ("binary_sensor", "smoke"),
            ("sensor", "garage_door"),
            ("cover", "garage_door"),
        ],
    )
    def test_non_gate_contacts_do_not_resolve_to_open_state(self, domain, device_class):
        """Оконный геркон и прочие датчики не должны считаться датчиком ворот.

        ``window`` исключён намеренно: иначе каждое окно в доме станет
        предлагаемым «положением ворот», и пользователь свяжет не тот
        датчик — ворота будут врать о положении и не откроются из-за
        гарда «уже открыто».
        """
        assert resolve_link_role(domain, device_class) != "open_state"

    def test_registry_has_no_ambiguous_pairs(self):
        """Ни одна пара (domain, device_class) не должна принадлежать двум ролям.

        На этом инварианте держится однозначность ``resolve_link_role`` и
        собственный цикл ``ws_auto_link_all``. Нарушение = связь уедет в
        случайную роль в зависимости от порядка объявления.
        """
        owner: dict[tuple[str, str], str] = {}
        for role in ALL_LINKABLE_ROLES:
            for pair in _declared_pairs(role):
                assert pair not in owner, f"{pair} заявлена и ролью {owner[pair]}, и ролью {role.role}"
                owner[pair] = role.role

    def test_every_declared_pair_resolves_back_to_its_role(self):
        """Резолвер обязан возвращать ту роль, которая пару объявила.

        Проверяет реестр целиком, а не только новую роль: добавление
        ``open_state`` не должно перехватить чужие пары.
        """
        for role in ALL_LINKABLE_ROLES:
            for domain, device_class in _declared_pairs(role):
                assert resolve_link_role(domain, device_class) == role.role

    def test_gate_link_roles_are_exactly_contact_and_signal(self):
        """У Sber-категории gate нет battery — набор ролей фиксирован.

        Лишняя роль battery привела бы к публикации незадекларированной
        фичи (Sber молча отклоняет такие устройства), пропавшая
        ``open_state`` — к воротам без источника положения.
        """
        assert GATE_LINK_ROLES == (ROLE_OPEN_STATE, ROLE_SIGNAL)
        assert ImpulseGateEntity.LINKABLE_ROLES == GATE_LINK_ROLES
        assert {r.role for r in ImpulseGateEntity.LINKABLE_ROLES} == {"open_state", "signal_strength"}

    def test_open_state_role_is_accepted_only_by_the_impulse_gate(self):
        """Ни один другой класс устройства не принимает роль ``open_state``.

        Изоляция: иначе геркон начнёт автоматически привязываться к
        шторам/реле (``auto_link_all`` идёт по LINKABLE_ROLES примари) и
        подменять их состояние.
        """
        accepting = {
            cls
            for spec in CATEGORY_DOMAIN_MAP.values()
            for cls in spec.entity_classes
            if any(role.role == "open_state" for role in cls.LINKABLE_ROLES)
        }
        assert accepting == {ImpulseGateEntity}

    def test_required_link_roles_default_is_empty_everywhere_but_impulse_gate(self):
        """Обязательная связь — только у импульсных ворот.

        Если ``REQUIRED_LINK_ROLES`` появится у другого класса, мастер
        начнёт отказывать в добавлении обычных устройств с кодом
        ``missing_required_role``.
        """
        assert BaseEntity.REQUIRED_LINK_ROLES == ()
        assert ImpulseGateEntity.REQUIRED_LINK_ROLES == ("open_state",)
        assert GateEntity.REQUIRED_LINK_ROLES == ()
        with_required = {
            cls.__name__: cls.REQUIRED_LINK_ROLES
            for spec in CATEGORY_DOMAIN_MAP.values()
            for cls in spec.entity_classes
            if cls.REQUIRED_LINK_ROLES
        }
        assert with_required == {"ImpulseGateEntity": ("open_state",)}

    def test_required_roles_are_a_subset_of_accepted_roles(self):
        """Обязательная роль обязана быть в числе принимаемых.

        Иначе получится нерешаемая задача: мастер требует связь, которую
        сам же отвергает как ``linked_role_not_accepted``.
        """
        for spec in CATEGORY_DOMAIN_MAP.values():
            for cls in spec.entity_classes:
                accepted = {role.role for role in cls.LINKABLE_ROLES}
                assert set(cls.REQUIRED_LINK_ROLES) <= accepted, cls.__name__


# ---------------------------------------------------------------------------
# 4. Мастер: классификация пары «реле + геркон»
# ---------------------------------------------------------------------------


class TestWizardClassification:
    """Step 2 мастера для TS0603-подобного устройства."""

    def test_relay_is_primary_and_contact_is_preselected_open_state(self, hass, mock_registries):
        """Пара на одном device_id: реле — примари, геркон — предвыбранная связь.

        Это единственный путь, которым пользователь может собрать ворота в
        UI. Падение = геркон уедет в «Not usable», связь не будет
        предложена, и добавить ворота станет невозможно (роль обязательная).
        """
        entity_reg, device_reg, _ = mock_registries
        _load(
            entity_reg,
            device_reg,
            [
                _make_entity(RELAY_ID, device_id="dev_gate", original_name="Gate relay"),
                _make_entity(
                    CONTACT_ID,
                    device_id="dev_gate",
                    original_device_class="garage_door",
                    original_name="Gate contact",
                ),
            ],
            [_make_device("dev_gate", name="Garage opener")],
        )

        group = _group_for(hass, "gate", "dev_gate")

        assert group.primary.entity_id == RELAY_ID
        assert group.primary.role == EntityRole.PRIMARY
        assert group.primary.sber_category == "gate"
        assert group.primary.preselected is True
        assert group.primary_alternatives == []

        assert [e.entity_id for e in group.linked_native] == [CONTACT_ID]
        contact = group.linked_native[0]
        assert contact.link_role == "open_state"
        assert contact.preselected is True
        assert contact.role == EntityRole.LINKED_NATIVE
        assert contact.is_cross_device is False
        assert group.unsupported == []

    def test_same_device_under_relay_category_keeps_contact_unsupported(self, hass, mock_registries):
        """Та же пара в категории relay: геркон остаётся неподдерживаемым.

        Доказательство изоляции роли. Если бы роль просочилась в другие
        категории, обычное реле начало бы получать связанный датчик и
        менять из-за него набор публикуемых фич.
        """
        entity_reg, device_reg, _ = mock_registries
        _load(
            entity_reg,
            device_reg,
            [
                _make_entity(RELAY_ID, device_id="dev_gate"),
                _make_entity(CONTACT_ID, device_id="dev_gate", original_device_class="garage_door"),
            ],
            [_make_device("dev_gate")],
        )

        group = _group_for(hass, "relay", "dev_gate")

        assert group.primary.entity_id == RELAY_ID
        assert group.linked_native == []
        assert group.linked_compatible == []
        assert [e.entity_id for e in group.unsupported] == [CONTACT_ID]
        assert group.unsupported[0].link_role is None
        assert group.unsupported[0].preselected is False

    def test_window_contact_on_the_same_device_is_not_offered(self, hass, mock_registries):
        """Оконный геркон рядом с реле не предлагается как положение ворот.

        Иначе пользователь одним кликом свяжет окно с воротами и получит
        ворота, которые «уже открыты» и потому не реагируют на команду.
        """
        entity_reg, device_reg, _ = mock_registries
        _load(
            entity_reg,
            device_reg,
            [
                _make_entity(RELAY_ID, device_id="dev_gate"),
                _make_entity("binary_sensor.window", device_id="dev_gate", original_device_class="window"),
            ],
            [_make_device("dev_gate")],
        )

        group = _group_for(hass, "gate", "dev_gate")

        assert group.linked_native == []
        assert [e.entity_id for e in group.unsupported] == ["binary_sensor.window"]

    def test_user_show_as_override_makes_the_contact_linkable(self, hass, mock_registries):
        """«Show as: Garage door» в HA обязан учитываться при подборе роли.

        Самодельные шаблонные герконы часто без device_class; пользователь
        выставляет его руками. Игнор override (issue #50/#51) вернёт
        датчик в «Not usable».
        """
        entity_reg, device_reg, _ = mock_registries
        _load(
            entity_reg,
            device_reg,
            [
                _make_entity(RELAY_ID, device_id="dev_gate"),
                _make_entity(
                    "binary_sensor.diy_contact",
                    device_id="dev_gate",
                    original_device_class=None,
                    device_class="garage_door",
                ),
            ],
            [_make_device("dev_gate")],
        )

        group = _group_for(hass, "gate", "dev_gate")

        assert [(e.entity_id, e.link_role) for e in group.linked_native] == [
            ("binary_sensor.diy_contact", "open_state")
        ]

    def test_cross_device_contact_is_compatible_but_not_preselected(self, hass, mock_registries):
        """Геркон с другого устройства предлагается, но без галочки по умолчанию.

        Частый монтаж: реле Zigbee + отдельный датчик. Молчаливый
        предвыбор чужого датчика привязал бы случайную дверь к воротам,
        поэтому ``preselected`` обязан быть False.
        """
        entity_reg, device_reg, _ = mock_registries
        _load(
            entity_reg,
            device_reg,
            [
                _make_entity(RELAY_ID, device_id="dev_relay"),
                _make_entity(CONTACT_ID, device_id="dev_contact", original_device_class="garage_door"),
            ],
            [_make_device("dev_relay"), _make_device("dev_contact", name="Contact")],
        )

        group = _group_for(hass, "gate", "dev_relay")

        assert group.linked_native == []
        assert [e.entity_id for e in group.linked_compatible] == [CONTACT_ID]
        candidate = group.linked_compatible[0]
        assert candidate.link_role == "open_state"
        assert candidate.preselected is False
        assert candidate.is_cross_device is True
        assert candidate.origin_device_id == "dev_contact"
        assert candidate.role == EntityRole.LINKED_COMPATIBLE

    def test_cover_gate_does_not_consume_the_contact(self, hass, mock_registries):
        """Классические cover-ворота не принимают роль ``open_state``.

        У cover положение приходит от самой сущности. Если бы GateEntity
        начал принимать геркон, у действующих пользователей поменялся бы
        набор связей и, как следствие, публикуемая конфигурация.
        """
        entity_reg, device_reg, _ = mock_registries
        _load(
            entity_reg,
            device_reg,
            [
                _make_entity("cover.gate", device_id="dev_cover", original_device_class="garage_door"),
                _make_entity(CONTACT_ID, device_id="dev_cover", original_device_class="garage_door"),
                _make_entity("sensor.gate_battery", device_id="dev_cover", original_device_class="battery"),
            ],
            [_make_device("dev_cover")],
        )

        group = _group_for(hass, "gate", "dev_cover")

        assert group.primary.entity_id == "cover.gate"
        assert [(e.entity_id, e.link_role) for e in group.linked_native] == [("sensor.gate_battery", "battery")]
        assert [e.entity_id for e in group.unsupported] == [CONTACT_ID]

    def test_gate_device_is_listed_for_the_gate_category(self, hass, mock_registries):
        """Устройство «реле+геркон» вообще обязано появиться в списке Step 2.

        Если fallback для switch отключить, устройство исчезнет из
        категории «ворота» и пользователю нечего будет выбирать.
        """
        entity_reg, device_reg, _ = mock_registries
        _load(
            entity_reg,
            device_reg,
            [
                _make_entity(RELAY_ID, device_id="dev_gate"),
                _make_entity(CONTACT_ID, device_id="dev_gate", original_device_class="garage_door"),
            ],
            [_make_device("dev_gate")],
        )

        groups = HaDeviceGrouper(hass).list_for_category("gate")
        assert [g.device_id for g in groups] == ["dev_gate"]


# ---------------------------------------------------------------------------
# 5. WebSocket add_ha_device: обязательность роли
# ---------------------------------------------------------------------------


class TestAddHaDeviceRequiredRole:
    """``sber_mqtt_bridge/add_ha_device`` для импульсных ворот."""

    @pytest.fixture
    def gate_registry(self):
        """Реестр HA с парой «импульсное реле + геркон» на одном устройстве.

        Ровно та топология, ради которой заведена issue #53: геркон
        помечен ``device_class=garage_door``, поэтому мастер обязан
        предложить его в роли ``open_state``.
        """
        return {
            RELAY_ID: _make_entity(RELAY_ID, device_id="dev_gate", original_name="Gate"),
            CONTACT_ID: _make_entity(CONTACT_ID, device_id="dev_gate", original_device_class="garage_door"),
        }

    async def test_pair_is_accepted_and_stored_by_role(self, hass, connection, gate_registry):
        """Принятая пара обязана лечь в options ровно тремя записями.

        Именно из ``entity_links`` мост строит положение ворот. Ошибка в
        форме записи = ворота публикуют выдуманное ``close`` и не
        обновляются с геркона.
        """
        entry = await _add_device(
            hass,
            connection,
            entity_reg_map=gate_registry,
            msg={
                "id": 1,
                "device_id": "dev_gate",
                "primary_entity_id": RELAY_ID,
                "category": "gate",
                "linked_entity_ids": [CONTACT_ID],
            },
        )

        connection.send_error.assert_not_called()
        connection.send_result.assert_called_once()
        payload = connection.send_result.call_args[0][1]
        assert payload["success"] is True
        assert payload["category"] == "gate"
        assert payload["primary_entity_id"] == RELAY_ID
        assert payload["linked_count"] == 1

        hass.config_entries.async_update_entry.assert_called_once()
        options = hass.config_entries.async_update_entry.call_args[1]["options"]
        assert options["exposed_entities"] == [RELAY_ID]
        assert options["entity_type_overrides"] == {RELAY_ID: "gate"}
        assert options["entity_links"] == {RELAY_ID: {"open_state": CONTACT_ID}}
        assert CONTACT_ID not in options["exposed_entities"]
        assert entry.options == {}, "options должны меняться только через async_update_entry"

    async def test_impulse_gate_without_contact_is_rejected(self, hass, connection, gate_registry):
        """Ворота без геркона добавить нельзя — ошибка ``missing_required_role``.

        Без датчика устройство публиковало бы выдуманное положение, а гард
        «уже открыто» работал бы по фикции. Половинчатое устройство в
        облаке хуже, чем отказ в добавлении.
        """
        await _add_device(
            hass,
            connection,
            entity_reg_map=gate_registry,
            msg={
                "id": 2,
                "device_id": "dev_gate",
                "primary_entity_id": RELAY_ID,
                "category": "gate",
            },
        )

        connection.send_result.assert_not_called()
        connection.send_error.assert_called_once()
        assert connection.send_error.call_args[0][1] == "missing_required_role"
        assert "open_state" in connection.send_error.call_args[0][2]
        hass.config_entries.async_update_entry.assert_not_called()

    async def test_rejection_also_applies_to_an_empty_link_list(self, hass, connection, gate_registry):
        """Явный пустой список связей — тот же отказ, что и отсутствие ключа.

        Панель отправляет ``linked_entity_ids: []``, когда пользователь
        снял галочку; путь обязан быть неотличим от «ключа нет».
        """
        await _add_device(
            hass,
            connection,
            entity_reg_map=gate_registry,
            msg={
                "id": 3,
                "device_id": "dev_gate",
                "primary_entity_id": RELAY_ID,
                "category": "gate",
                "linked_entity_ids": [],
            },
        )

        connection.send_error.assert_called_once()
        assert connection.send_error.call_args[0][1] == "missing_required_role"
        hass.config_entries.async_update_entry.assert_not_called()

    async def test_signal_sensor_alone_does_not_satisfy_the_requirement(self, hass, connection):
        """Связь по другой роли не заменяет обязательную ``open_state``.

        Проверка обязана смотреть на конкретную роль, а не на «есть хоть
        одна связь»: иначе ворота с одним лишь датчиком RSSI пройдут
        валидацию и приедут в облако без положения.
        """
        registry = {
            RELAY_ID: _make_entity(RELAY_ID, device_id="dev_gate"),
            "sensor.gate_rssi": _make_entity(
                "sensor.gate_rssi", device_id="dev_gate", original_device_class="signal_strength"
            ),
        }
        await _add_device(
            hass,
            connection,
            entity_reg_map=registry,
            msg={
                "id": 4,
                "device_id": "dev_gate",
                "primary_entity_id": RELAY_ID,
                "category": "gate",
                "linked_entity_ids": ["sensor.gate_rssi"],
            },
        )

        connection.send_error.assert_called_once()
        assert connection.send_error.call_args[0][1] == "missing_required_role"
        hass.config_entries.async_update_entry.assert_not_called()

    async def test_two_contacts_are_a_role_conflict(self, hass, connection):
        """Два геркона на одну роль — существующая ошибка ``role_conflict``.

        Молчаливое «побеждает последний» дало бы недетерминированный
        источник положения ворот.
        """
        registry = {
            RELAY_ID: _make_entity(RELAY_ID, device_id="dev_gate"),
            CONTACT_ID: _make_entity(CONTACT_ID, device_id="dev_gate", original_device_class="garage_door"),
            "binary_sensor.second": _make_entity(
                "binary_sensor.second", device_id="dev_gate", original_device_class="door"
            ),
        }
        await _add_device(
            hass,
            connection,
            entity_reg_map=registry,
            msg={
                "id": 5,
                "device_id": "dev_gate",
                "primary_entity_id": RELAY_ID,
                "category": "gate",
                "linked_entity_ids": [CONTACT_ID, "binary_sensor.second"],
            },
        )

        connection.send_error.assert_called_once()
        assert connection.send_error.call_args[0][1] == "role_conflict"
        hass.config_entries.async_update_entry.assert_not_called()

    async def test_window_contact_is_not_accepted_as_position_source(self, hass, connection):
        """Оконный геркон отвергается до проверки обязательных ролей.

        Код ошибки важен для UI: пользователь должен понять, что датчик
        не подходит, а не что «связь не выбрана».
        """
        registry = {
            RELAY_ID: _make_entity(RELAY_ID, device_id="dev_gate"),
            "binary_sensor.window": _make_entity(
                "binary_sensor.window", device_id="dev_gate", original_device_class="window"
            ),
        }
        await _add_device(
            hass,
            connection,
            entity_reg_map=registry,
            msg={
                "id": 6,
                "device_id": "dev_gate",
                "primary_entity_id": RELAY_ID,
                "category": "gate",
                "linked_entity_ids": ["binary_sensor.window"],
            },
        )

        connection.send_error.assert_called_once()
        assert connection.send_error.call_args[0][1] == "linked_role_not_accepted"
        hass.config_entries.async_update_entry.assert_not_called()

    async def test_cover_gate_is_still_added_without_any_link(self, hass, connection):
        """Обратная совместимость: cover-ворота добавляются без связей, как раньше.

        Если проверка обязательных ролей заденет cover-путь, действующие
        пользователи не смогут переподключить свои ворота.
        """
        registry = {
            "cover.gate": _make_entity("cover.gate", device_id="dev_cover", original_device_class="garage_door"),
        }
        await _add_device(
            hass,
            connection,
            entity_reg_map=registry,
            msg={
                "id": 7,
                "device_id": "dev_cover",
                "primary_entity_id": "cover.gate",
                "category": "gate",
            },
        )

        connection.send_error.assert_not_called()
        connection.send_result.assert_called_once()
        options = hass.config_entries.async_update_entry.call_args[1]["options"]
        assert options["exposed_entities"] == ["cover.gate"]
        assert options["entity_links"] == {}

    @pytest.mark.parametrize("category", sorted(CATEGORY_DOMAIN_MAP))
    async def test_every_other_category_adds_without_links_as_before(self, hass, connection, category):
        """Сквозная проверка: новая валидация не задела ни одну категорию.

        Для каждой зарегистрированной категории берётся probe-сущность её
        первого домена и добавляется без связей. Любой ``send_error``
        здесь означает, что часть устройств стала неподключаемой.
        """
        spec = CATEGORY_DOMAIN_MAP[category]
        domain = spec.domains[0]
        device_class = spec.device_classes[0] if spec.device_classes else None
        probe_id = f"{domain}.probe"
        registry = {probe_id: _make_entity(probe_id, device_id="dev_probe", original_device_class=device_class)}

        await _add_device(
            hass,
            connection,
            entity_reg_map=registry,
            msg={
                "id": 8,
                "device_id": "dev_probe",
                "primary_entity_id": probe_id,
                "category": category,
            },
        )

        assert not connection.send_error.called, (
            f"категория {category} перестала добавляться: {connection.send_error.call_args}"
        )
        connection.send_result.assert_called_once()
        options = hass.config_entries.async_update_entry.call_args[1]["options"]
        assert options["entity_type_overrides"] == {probe_id: category}

    async def test_impulse_gate_probe_is_the_only_rejected_promotion(self, hass, connection):
        """Тот же probe-прогон, но для не-cover домена gate — обязан отказать.

        Контрольная точка к предыдущему тесту: он проходит по
        ``domains[0] == "cover"`` и сам по себе не доказал бы, что
        проверка вообще работает.
        """
        registry = {RELAY_ID: _make_entity(RELAY_ID, device_id="dev_gate")}
        await _add_device(
            hass,
            connection,
            entity_reg_map=registry,
            msg={
                "id": 9,
                "device_id": "dev_gate",
                "primary_entity_id": RELAY_ID,
                "category": "gate",
            },
        )
        connection.send_result.assert_not_called()
        assert connection.send_error.call_args[0][1] == "missing_required_role"

    async def test_schema_still_guards_the_gate_payload(self, hass, connection, gate_registry):
        """Схема команды не ослаблена ради ворот.

        ``linked_entity_ids`` обязан оставаться списком entity_id: строка
        «binary_sensor.gate_contact» без списка тихо разложилась бы в
        символы и записала мусор в options.
        """
        with pytest.raises(vol.Invalid):
            await _add_device(
                hass,
                connection,
                entity_reg_map=gate_registry,
                msg={
                    "id": 10,
                    "device_id": "dev_gate",
                    "primary_entity_id": RELAY_ID,
                    "category": "gate",
                    "linked_entity_ids": ["not an entity id"],
                },
            )
        hass.config_entries.async_update_entry.assert_not_called()


# ---------------------------------------------------------------------------
# 6. WebSocket device_detail: блок gate_options для панели
# ---------------------------------------------------------------------------


class TestDeviceDetailGateSection:
    """``sber_mqtt_bridge/device_detail`` отдаёт настройки импульсных ворот.

    Панель (``sber-detail-dialog.js``) рисует переключатель полярности
    геркона и выбор сервиса импульса ровно по этому блоку: пропадёт блок —
    настройки станут недоступны из UI, приедет он для обычного устройства —
    пользователь получит органы управления, которых у устройства нет.
    """

    @staticmethod
    async def _detail(entity, *, links: dict[str, str] | None = None) -> dict:
        """Прогнать ``ws_device_detail`` для готовой сущности и вернуть ответ."""
        hass = MagicMock()
        ha_state = MagicMock()
        ha_state.state = "off"
        ha_state.attributes = {}
        hass.states.get = MagicMock(return_value=ha_state)

        bridge = MagicMock()
        bridge.entities = {entity.entity_id: entity}
        bridge.entity_links = {entity.entity_id: dict(links or {})}
        bridge.redefinitions = {}

        connection = MagicMock()
        with (
            patch(f"{_STATUS_MODULE}.get_bridge", return_value=bridge),
            patch(f"{_STATUS_MODULE}.er") as mock_er,
            patch(f"{_STATUS_MODULE}.dr"),
            patch(f"{_STATUS_MODULE}.ar") as mock_ar,
        ):
            mock_er.async_get.return_value.async_get.return_value = None
            mock_ar.async_get.return_value.async_get_area.return_value = None
            await dispatch(ws_device_detail, hass, connection, {"id": 1, "entity_id": entity.entity_id})
        assert not connection.send_error.called, connection.send_error.call_args
        return connection.send_result.call_args[0][1]

    @staticmethod
    def _make_gate(options: dict | None = None) -> ImpulseGateEntity:
        """Собрать импульсные ворота со связанным герконом."""
        entity = make_gate_entity({"entity_id": RELAY_ID, "name": "Gate"})
        assert isinstance(entity, ImpulseGateEntity)
        if options:
            entity.apply_gate_options(options)
        entity.register_link("open_state", CONTACT_ID)
        entity.fill_by_ha_state({"entity_id": RELAY_ID, "state": "off", "attributes": {}})
        entity.update_linked_data("open_state", {"entity_id": CONTACT_ID, "state": "on"})
        return entity

    async def test_detail_exposes_exact_gate_option_block(self):
        """Ключи блока — РОВНО те четыре, что читает панель.

        Лишний ключ панель молча проигнорирует, а недостающий приведёт к
        неопределённому состоянию контрола (переключатель без значения).
        ``travel_time`` добавлен вместе с эмуляцией хода створки: панель
        рисует поле только при `g.travel_time !== undefined`, а форма
        отправляет все поля разом — без ключа контрол не появится вовсе.
        """
        detail = await self._detail(self._make_gate(), links={"open_state": CONTACT_ID})

        assert detail["gate_options"] == {
            "invert_contact": False,
            "impulse_service": "auto",
            "contact_stale": False,
            "travel_time": 0.0,
        }

    async def test_detail_reflects_saved_options(self):
        """Сохранённые опции обязаны доезжать до панели как есть.

        Иначе пользователь включит инверсию, откроет карточку и увидит
        выключенный переключатель — и выключит инверсию «обратно».
        """
        entity = self._make_gate({"invert_contact": True, "impulse_service": "turn_on"})

        detail = await self._detail(entity, links={"open_state": CONTACT_ID})

        assert detail["gate_options"]["invert_contact"] is True
        assert detail["gate_options"]["impulse_service"] == "turn_on"

    async def test_detail_reports_stale_contact(self):
        """Пропавший геркон обязан быть виден в карточке устройства.

        Положение при этом продолжает публиковаться последним известным —
        без этого флага пользователь не отличит «реально закрыто» от
        «датчик молчит уже сутки».
        """
        entity = self._make_gate()
        entity.update_linked_data("open_state", {"entity_id": CONTACT_ID, "state": "unavailable"})

        detail = await self._detail(entity, links={"open_state": CONTACT_ID})

        assert detail["gate_options"]["contact_stale"] is True
        assert detail["sber_states"], "состояние обязано публиковаться и при молчащем герконе"

    async def test_cover_gate_has_no_gate_options_block(self):
        """У ворот-``cover`` этих настроек нет — ключа быть не должно.

        Геркон и импульсный сервис к позиционному приводу неприменимы;
        показать их — предложить пользователю настройку-пустышку.
        """
        entity = make_gate_entity({"entity_id": "cover.gate", "name": "Gate"})
        assert isinstance(entity, GateEntity)
        entity.fill_by_ha_state({"entity_id": "cover.gate", "state": "open", "attributes": {}})

        detail = await self._detail(entity)

        assert "gate_options" not in detail
