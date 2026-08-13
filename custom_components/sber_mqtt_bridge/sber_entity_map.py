"""Mapping from HA entity domains to Sber device entity classes.

Provides factory functions that create the appropriate Sber entity
subclass based on the HA entity domain and device class.
Supports user-defined overrides via ``sber_category`` parameter.

Also hosts the **single source of truth** for Sber category → HA domain
promotion: :data:`CATEGORY_DOMAIN_MAP` + :func:`categories_for_domain` +
:data:`CATEGORY_UI_META` drive the device-centric wizard introduced in
v1.26.0.  See ``docs/DEVICE_WIZARD_PLAN.md`` for the full design.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .devices.base_entity import BaseEntity
from .devices.climate import ClimateEntity
from .devices.curtain import CurtainEntity
from .devices.door_sensor import DoorSensorEntity
from .devices.gas_sensor import GasSensorEntity
from .devices.gate import make_gate_entity
from .devices.humidifier import HumidifierEntity
from .devices.humidity_sensor import HumiditySensorEntity
from .devices.hvac_air_purifier import HvacAirPurifierEntity
from .devices.hvac_boiler import HvacBoilerEntity
from .devices.hvac_fan import HvacFanEntity
from .devices.hvac_heater import HvacHeaterEntity
from .devices.hvac_radiator import HvacRadiatorEntity
from .devices.hvac_underfloor_heating import HvacUnderfloorEntity
from .devices.intercom import IntercomEntity
from .devices.kettle import KettleEntity
from .devices.led_strip import LedStripEntity
from .devices.light import LightEntity
from .devices.motion_sensor import MotionSensorEntity
from .devices.relay import RelayEntity
from .devices.scenario_button import ScenarioButtonEntity
from .devices.sensor_air import SensorAirEntity
from .devices.sensor_temp import SensorTempEntity
from .devices.smoke_sensor import SmokeSensorEntity
from .devices.socket_entity import SocketEntity
from .devices.tv import TvEntity
from .devices.vacuum_cleaner import VacuumCleanerEntity
from .devices.valve import ValveEntity
from .devices.water_leak_sensor import WaterLeakSensorEntity
from .devices.window_blind import WindowBlindEntity

if TYPE_CHECKING:
    from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Category promotion registry — v1.26.0 device-centric wizard
# ---------------------------------------------------------------------------
#
# CATEGORY_DOMAIN_MAP answers the question:
#   "Given a Sber category the user picked in Step 1 of the wizard, which
#    HA (domain, device_class) combinations can be promoted into it?"
#
# This is the inverse of CATEGORY_CONSTRUCTORS / ENTITY_CONSTRUCTORS — those
# give you a *class* when you already know what you want to build.
# CATEGORY_DOMAIN_MAP lets the wizard *filter* HA devices to just those
# compatible with the chosen category before showing them.


@dataclass(frozen=True, slots=True)
class CategorySpec:
    """Rules for promoting an HA entity to a specific Sber category.

    Attributes:
        cls: Factory building the Sber entity for this category.  The
            contract is ``cls(entity_data: dict) -> BaseEntity`` — every
            registered value must accept the entity-registry data dict as
            its single positional argument (leaf device classes do; the
            abstract bases like ``BaseEntity`` / ``OnOffEntity`` take
            ``(category, entity_data)`` and therefore must NOT be
            registered directly).  Serves as the single source of truth
            for both auto-detection (pick by domain) and user overrides
            (pick by explicit category name).
        domains: HA domains that can match this category.  Order matters for
            presentation but not correctness — any listed domain is accepted.
        device_classes: If ``None`` — the category matches any device_class
            inside the allowed domains (domain-only match).  If a tuple — the
            entity must have one of these ``original_device_class`` values.
            Use an empty string ``""`` in the tuple to also accept entities
            without a declared device_class.
        preferred_rank: Tie-breaking priority when the same ``(domain,
            device_class)`` pair matches several categories.  Lower wins.
            Mirrors the domain rank used for primary-entity selection.
        fallback_when_no_device_class: When ``True`` and the entity has no
            declared ``device_class`` at all, this category accepts it as a
            fallback.  Used by ``relay`` so that a plain ``switch`` without
            device_class becomes a relay rather than silently unmatched.
        no_device_class_domains: Restricts ``fallback_when_no_device_class``
            to the listed domains.  Empty (default) keeps the historical
            behaviour — the fallback applies to every domain of the
            category.  Needed by ``gate``, which must accept a bare
            ``switch`` (impulse relay, issue #53) while leaving a bare
            ``cover`` to ``curtain`` exactly as before.
    """

    cls: Callable[[dict[str, Any]], BaseEntity]
    domains: tuple[str, ...]
    device_classes: tuple[str, ...] | None = None
    preferred_rank: int = 50
    fallback_when_no_device_class: bool = False
    no_device_class_domains: tuple[str, ...] = ()

    @property
    def entity_classes(self) -> tuple[type[BaseEntity], ...]:
        """Concrete entity classes this category can instantiate.

        :attr:`cls` is only required to be *callable*, and the ``gate``
        category uses that freedom: one Sber category covers two very
        different devices (an HA ``cover`` and an impulse relay), so its
        ``cls`` is the :func:`~devices.gate.make_gate_entity` factory.
        Introspection — "does this category produce an ``OnOffEntity``?",
        "does any of its classes override the publish wrapper?" — must go
        through this property instead of assuming ``cls`` is a class.

        A factory advertises what it can build via a ``produces`` tuple
        attribute; a plain class advertises itself.

        Returns:
            Tuple of concrete :class:`BaseEntity` subclasses, empty when a
            factory does not declare ``produces``.
        """
        if isinstance(self.cls, type):
            return (self.cls,)
        return tuple(getattr(self.cls, "produces", ()))

    def matches(self, domain: str, device_class: str | None) -> bool:
        """Return True if an HA entity of ``(domain, device_class)`` promotes here."""
        if domain not in self.domains:
            return False
        if self.device_classes is None:
            return True
        dc = device_class or ""
        if dc in self.device_classes:
            return True
        if not self.fallback_when_no_device_class or dc != "":
            return False
        return not self.no_device_class_domains or domain in self.no_device_class_domains


CATEGORY_DOMAIN_MAP: dict[str, CategorySpec] = {
    # ── Lights ──────────────────────────────────────────────────────────
    "light": CategorySpec(cls=LightEntity, domains=("light",), preferred_rank=1),
    "led_strip": CategorySpec(cls=LedStripEntity, domains=("light",), preferred_rank=5),
    # ── Switches / outlets / relays ────────────────────────────────────
    "socket": CategorySpec(
        cls=SocketEntity,
        domains=("switch",),
        device_classes=("outlet",),
        preferred_rank=8,
    ),
    "relay": CategorySpec(
        cls=RelayEntity,
        domains=("switch", "script", "button"),
        device_classes=None,
        preferred_rank=10,
        fallback_when_no_device_class=True,
    ),
    "scenario_button": CategorySpec(
        cls=ScenarioButtonEntity,
        domains=("input_boolean",),
        preferred_rank=12,
    ),
    # ── Covers ──────────────────────────────────────────────────────────
    "gate": CategorySpec(
        # ``cover`` MUST stay first: probe helpers build ``f"{domains[0]}.probe"``
        # and the factory routes ``cover.*`` to the historical GateEntity.
        cls=make_gate_entity,
        domains=("cover", "switch", "button", "script"),
        device_classes=("gate", "garage_door", "garage", "door"),
        # Rank 35 keeps gate *out* of auto-detection for a plain switch
        # (relay 10 → intercom 30 → gate 35 → kettle 40): an impulse gate
        # is only reachable by picking the category explicitly.
        preferred_rank=35,
        fallback_when_no_device_class=True,
        no_device_class_domains=("switch", "button", "script"),
    ),
    "window_blind": CategorySpec(
        cls=WindowBlindEntity,
        domains=("cover",),
        device_classes=("blind", "shade", "shutter"),
        preferred_rank=4,
    ),
    "curtain": CategorySpec(
        cls=CurtainEntity,
        domains=("cover",),
        device_classes=("curtain", "awning"),
        preferred_rank=6,
        fallback_when_no_device_class=True,
    ),
    # ── Climate ─────────────────────────────────────────────────────────
    "hvac_radiator": CategorySpec(
        cls=HvacRadiatorEntity,
        domains=("climate",),
        device_classes=("radiator",),
        preferred_rank=3,
    ),
    "hvac_heater": CategorySpec(
        cls=HvacHeaterEntity,
        domains=("climate",),
        device_classes=("heater",),
        preferred_rank=4,
    ),
    "hvac_underfloor_heating": CategorySpec(
        cls=HvacUnderfloorEntity,
        domains=("climate",),
        device_classes=("underfloor", "underfloor_heating"),
        preferred_rank=5,
    ),
    "hvac_ac": CategorySpec(
        cls=ClimateEntity,
        domains=("climate",),
        device_classes=None,
        preferred_rank=6,
        fallback_when_no_device_class=True,
    ),
    "hvac_boiler": CategorySpec(
        cls=HvacBoilerEntity,
        domains=("water_heater",),
        preferred_rank=5,
    ),
    # ── Fan / air purifier / humidifier ────────────────────────────────
    "hvac_air_purifier": CategorySpec(
        cls=HvacAirPurifierEntity,
        domains=("fan",),
        device_classes=("purifier", "air_purifier"),
        preferred_rank=4,
    ),
    "hvac_fan": CategorySpec(
        cls=HvacFanEntity,
        domains=("fan",),
        device_classes=None,
        preferred_rank=6,
        fallback_when_no_device_class=True,
    ),
    "hvac_humidifier": CategorySpec(
        cls=HumidifierEntity,
        domains=("humidifier",),
        preferred_rank=5,
    ),
    # ── Valves / kitchen ───────────────────────────────────────────────
    "valve": CategorySpec(
        cls=ValveEntity,
        domains=("valve",),
        preferred_rank=5,
    ),
    "kettle": CategorySpec(
        # Kettle is a niche promotion: a water_heater or plain switch can
        # become one, but socket (rank 8) / relay (rank 10) / hvac_boiler
        # (rank 5) win for their respective domains.  Users still access
        # kettle by explicitly picking it in Step 1 of the wizard — rank
        # only affects auto-detection, not category filtering.
        cls=KettleEntity,
        domains=("water_heater", "switch"),
        device_classes=None,
        preferred_rank=40,
        fallback_when_no_device_class=True,
    ),
    # ── Media / appliances ──────────────────────────────────────────────
    "tv": CategorySpec(
        cls=TvEntity,
        domains=("media_player",),
        device_classes=None,
        preferred_rank=5,
        fallback_when_no_device_class=True,
    ),
    "vacuum_cleaner": CategorySpec(
        cls=VacuumCleanerEntity,
        domains=("vacuum",),
        preferred_rank=5,
    ),
    "intercom": CategorySpec(
        cls=IntercomEntity,
        domains=("lock", "switch"),
        device_classes=None,
        preferred_rank=30,
    ),
    # ── Read-only sensors ──────────────────────────────────────────────
    "sensor_temp": CategorySpec(
        cls=SensorTempEntity,
        domains=("sensor",),
        device_classes=("temperature",),
        preferred_rank=30,
    ),
    "sensor_humidity": CategorySpec(
        cls=HumiditySensorEntity,
        domains=("sensor",),
        device_classes=("humidity",),
        preferred_rank=30,
    ),
    "sensor_air": CategorySpec(
        cls=SensorAirEntity,
        domains=("sensor",),
        # Subset of devices/sensor_air.py::_DEVICE_CLASS_ROUTING.  Do NOT
        # "complete" this tuple for symmetry: "temperature" / "humidity"
        # deliberately route to sensor_temp / sensor_humidity, and
        # "volatile_organic_compounds_parts" (HCHO) is a linked-role-only
        # class — as a primary it would yield a sensor_air device with no
        # populated primary field (locked by test_category_domain_map.py).
        device_classes=(
            "carbon_dioxide",
            "pm1",
            "pm25",
            "pm10",
            "volatile_organic_compounds",
        ),
        # Lower rank than sensor_temp (30) so a truly ambiguous entity
        # (impossible today — no overlap in device_classes) would prefer
        # sensor_air. Room-quality devices are less common than plain
        # temp sensors, so we still put it below light/relay.
        preferred_rank=25,
    ),
    # ── Binary sensors ─────────────────────────────────────────────────
    "sensor_pir": CategorySpec(
        cls=MotionSensorEntity,
        domains=("binary_sensor",),
        device_classes=("motion", "occupancy", "presence"),
        preferred_rank=20,
    ),
    "sensor_door": CategorySpec(
        cls=DoorSensorEntity,
        domains=("binary_sensor",),
        device_classes=("door", "window", "garage_door", "opening"),
        preferred_rank=20,
    ),
    "sensor_water_leak": CategorySpec(
        cls=WaterLeakSensorEntity,
        domains=("binary_sensor",),
        device_classes=("moisture", "water"),
        preferred_rank=20,
    ),
    "sensor_smoke": CategorySpec(
        cls=SmokeSensorEntity,
        domains=("binary_sensor",),
        device_classes=("smoke",),
        preferred_rank=20,
    ),
    "sensor_gas": CategorySpec(
        cls=GasSensorEntity,
        domains=("binary_sensor",),
        device_classes=("gas", "carbon_monoxide"),
        preferred_rank=20,
    ),
}
"""Authoritative Sber-category → HA-entity-class promotion table.

Every entry carries its own entity constructor via :attr:`CategorySpec.cls`,
so this single dict drives both auto-detection (by HA domain/device_class)
and user overrides (by explicit category id).
"""


OVERRIDABLE_CATEGORIES: list[str] = sorted(CATEGORY_DOMAIN_MAP)
"""Sber categories a user may pick as an explicit type override.

Derived from :data:`CATEGORY_DOMAIN_MAP` so it can never drift from the
authoritative registry.  This is the **only** definition — the Options
Flow selector and every WebSocket schema (``set_override``,
``add_ha_device``, ``import``) import it from here (see
``websocket_api/_common.py`` re-export).  Do NOT hand-write category
lists elsewhere; the JS panel should fetch categories via the
``sber_mqtt_bridge/list_categories`` WS command.
"""


SUPPORTED_DOMAINS: list[str] = sorted({domain for spec in CATEGORY_DOMAIN_MAP.values() for domain in spec.domains})
"""HA entity domains that can be exported to Sber Smart Home.

Computed as the union of :attr:`CategorySpec.domains` across
:data:`CATEGORY_DOMAIN_MAP` — adding a category with a new domain
automatically makes that domain selectable in the Options Flow
fallback paths (manual select, by-domain, by-label, add-all).

The two presentation-level tables that must follow this list —
``config_flow.DOMAIN_PRIORITY`` (device deduplication) and
``config_flow.DOMAIN_LABELS`` (human-readable captions) — cannot be
derived from it (priority is a cross-domain "richness" judgement, labels
are prose), so their completeness is machine-checked instead by
``tests/hacs/test_config_flow_options.py``.  A new domain therefore
fails the suite until both tables are extended.
"""


@dataclass(frozen=True, slots=True)
class CategoryUiMeta:
    """Presentation metadata for a Sber category in the wizard UI.

    Attributes:
        icon: Unicode emoji shown in the Step 1 grid tile.
        group: UI group identifier (``"control"`` / ``"sensors"`` /
            ``"automations"``) for collapsed grouping.
        label_key: Translation key suffix; frontend resolves it against
            its i18n table.  For the panel which currently uses hard-coded
            strings, this is also used as a short English fallback label.
        user_selectable: When ``False``, the category is excluded from the
            Step 1 grid — it still participates in grouping classification
            (``sensor_humidity`` is a concrete subcategory of the user-
            visible ``sensor_temp``, etc.) but the user doesn't pick it
            explicitly.
    """

    icon: str
    group: str
    label_key: str
    user_selectable: bool = True


CATEGORY_UI_META: dict[str, CategoryUiMeta] = {
    "light": CategoryUiMeta("💡", "control", "Light"),
    "led_strip": CategoryUiMeta("🎚️", "control", "LED strip"),
    "relay": CategoryUiMeta("🔌", "control", "Relay"),
    "socket": CategoryUiMeta("🔋", "control", "Socket"),
    "hvac_ac": CategoryUiMeta("❄️", "control", "Air conditioner"),
    "hvac_radiator": CategoryUiMeta("🔥", "control", "Radiator"),
    "hvac_heater": CategoryUiMeta("♨️", "control", "Heater"),
    "hvac_underfloor_heating": CategoryUiMeta("🧱", "control", "Underfloor heating"),
    "hvac_boiler": CategoryUiMeta("🫖", "control", "Boiler"),
    "hvac_humidifier": CategoryUiMeta("💧", "control", "Humidifier"),
    "hvac_air_purifier": CategoryUiMeta("🌬️", "control", "Air purifier"),
    "hvac_fan": CategoryUiMeta("🌀", "control", "Fan"),
    "kettle": CategoryUiMeta("☕", "control", "Kettle"),
    "vacuum_cleaner": CategoryUiMeta("🤖", "control", "Vacuum"),
    "valve": CategoryUiMeta("🚰", "control", "Valve"),
    "curtain": CategoryUiMeta("🟨", "control", "Curtain"),
    "window_blind": CategoryUiMeta("🪟", "control", "Window blind"),
    "gate": CategoryUiMeta("🚪", "control", "Gate / Garage"),
    "tv": CategoryUiMeta("📺", "control", "TV / Media player"),
    "intercom": CategoryUiMeta("🔔", "control", "Intercom"),
    "sensor_temp": CategoryUiMeta("🌡️", "sensors", "Temperature"),
    "sensor_humidity": CategoryUiMeta("💦", "sensors", "Humidity", user_selectable=False),
    "sensor_air": CategoryUiMeta("🌫️", "sensors", "Air quality"),
    "sensor_pir": CategoryUiMeta("🚶", "sensors", "Motion"),
    "sensor_door": CategoryUiMeta("🚪", "sensors", "Door / Window"),
    "sensor_water_leak": CategoryUiMeta("🌊", "sensors", "Water leak"),
    "sensor_smoke": CategoryUiMeta("💨", "sensors", "Smoke"),
    "sensor_gas": CategoryUiMeta("⚠️", "sensors", "Gas"),
    "scenario_button": CategoryUiMeta("🔔", "automations", "Scenario button"),
}
"""Presentation data for each Sber category in the wizard UI.

Keys must be a subset of :data:`CATEGORY_DOMAIN_MAP`.  See the consistency
test ``test_category_domain_map.py::test_ui_meta_is_subset_of_domain_map``.
"""


UI_OVERRIDABLE_CATEGORIES: list[str] = sorted(
    cat for cat in CATEGORY_DOMAIN_MAP if (meta := CATEGORY_UI_META.get(cat)) is None or meta.user_selectable
)
"""Subset of :data:`OVERRIDABLE_CATEGORIES` offered in user-facing pickers.

:data:`OVERRIDABLE_CATEGORIES` stays the **validation** vocabulary — every
key of :data:`CATEGORY_DOMAIN_MAP` is a legal override value, and the
WebSocket schemas must keep accepting all of them (the wizard itself
stores e.g. ``sensor_humidity``).  This list drops the categories flagged
``user_selectable=False`` in :data:`CATEGORY_UI_META`, i.e. the ones the
bridge resolves on its own from ``device_class``, so the Options Flow
dropdown does not offer meaningless picks.

Consumers must still union in the entity's *current* override before
building a selector — otherwise a value set through the WebSocket API
would sit outside the offered options and ``vol.In`` would reject the
unchanged form on submit.
"""


CATEGORY_GROUPS: tuple[tuple[str, str], ...] = (
    ("control", "Control"),
    ("sensors", "Sensors"),
    ("automations", "Automations"),
)
"""Ordered list of ``(group_id, label)`` for Step 1 grid grouping."""


def category_label(category: str) -> str:
    """Return the human-readable label for a Sber category.

    Single source of truth for category labels — resolves against
    :data:`CATEGORY_UI_META` (``label_key`` doubles as the English
    fallback label) so the Options Flow and the wizard never disagree.

    Args:
        category: Sber category id (e.g. ``"hvac_ac"``).

    Returns:
        Human-readable label, or the raw category id when unknown.
    """
    meta = CATEGORY_UI_META.get(category)
    return meta.label_key if meta is not None else category


def categories_for_domain(
    domain: str,
    device_class: str | None = None,
) -> list[str]:
    """Return all Sber categories matching the given HA ``(domain, device_class)``.

    Result is sorted by :attr:`CategorySpec.preferred_rank` ascending — so
    the first item is the auto-detected category, subsequent items are
    alternatives the user could pick.

    Args:
        domain: HA entity domain (e.g. ``"light"``, ``"sensor"``).
        device_class: Optional ``original_device_class`` value.

    Returns:
        List of Sber category IDs.  Empty when no category matches.
    """
    matches = [(category, spec) for category, spec in CATEGORY_DOMAIN_MAP.items() if spec.matches(domain, device_class)]
    matches.sort(key=lambda pair: pair[1].preferred_rank)
    return [category for category, _ in matches]


def create_sber_entity(
    entity_id: str,
    entity_data: dict,
    sber_category: str | None = None,
) -> BaseEntity | None:
    """Create a Sber device entity from HA entity data.

    Uses :data:`CATEGORY_DOMAIN_MAP` as the single source of truth.  When
    ``sber_category`` is provided, it resolves directly against the map;
    otherwise :func:`categories_for_domain` picks the best-ranked match
    for the entity's ``(domain, device_class)``.

    Args:
        entity_id: HA entity ID (e.g., ``"light.living_room"``).
        entity_data: Dict with entity registry data (entity_id, device_id,
            area_id, original_device_class, etc.).
        sber_category: Optional Sber category override (e.g. ``"light"``,
            ``"relay"``).  Takes precedence over the domain-based pick.

    Returns:
        BaseEntity subclass instance, or ``None`` if no category matches.
    """
    dc = entity_data.get("original_device_class", "")

    if sber_category:
        # UX convenience: when a user picks "sensor_temp" but the HA entity
        # is actually a humidity sensor, silently route to sensor_humidity
        # so the resulting device emits the right Sber key.  Both categories
        # live in CATEGORY_DOMAIN_MAP so this is just a category rewrite.
        if sber_category == "sensor_temp" and dc == "humidity":
            sber_category = "sensor_humidity"
        spec = CATEGORY_DOMAIN_MAP.get(sber_category)
        if spec is not None:
            entity = spec.cls(entity_data)
            _LOGGER.debug("Entity %s → Sber %s (override)", entity_id, entity.category)
            return entity
        _LOGGER.warning(
            "Unknown Sber category override '%s' for %s, falling back to domain mapping",
            sber_category,
            entity_id,
        )

    domain = entity_id.split(".")[0]
    matches = categories_for_domain(domain, dc)
    if not matches:
        _LOGGER.debug(
            "No Sber category for entity %s (domain=%s, device_class=%s)",
            entity_id,
            domain,
            dc,
        )
        return None
    spec = CATEGORY_DOMAIN_MAP[matches[0]]
    entity = spec.cls(entity_data)
    _LOGGER.debug(
        "Entity %s → Sber %s (domain=%s, device_class=%s)",
        entity_id,
        entity.category,
        domain,
        dc,
    )
    return entity


def build_probe_entity_data(entry: er.RegistryEntry) -> dict[str, Any]:
    """Build the ``entity_data`` dict for a throw-away (probe) Sber entity.

    Several call sites only need a Sber entity in order to *inspect* it —
    to read its resolved ``category``, its ``LINKABLE_ROLES`` or its
    feature list — and never publish it.  They used to hand-roll this dict
    with slightly different key sets, so a newly required field could be
    forgotten in one copy.  This is the single builder for that shape.

    The result is intentionally a subset of the full registry payload
    assembled by :meth:`SberEntityLoader._load_entities` (no ``area_id``
    resolution, no ``icon`` / ``entity_category``) — probes never leave
    the process.

    Args:
        entry: HA entity-registry entry to describe.

    Returns:
        Dict accepted by every :attr:`CategorySpec.cls` constructor.
    """
    return {
        "entity_id": entry.entity_id,
        "original_device_class": entry.original_device_class or "",
        "device_id": entry.device_id,
        "name": entry.name or entry.original_name or entry.entity_id,
        "original_name": entry.original_name,
        "platform": entry.platform,
        "unique_id": entry.unique_id,
        "disabled_by": entry.disabled_by,
        "hidden_by": entry.hidden_by,
    }


def build_probe_entity(
    entry: er.RegistryEntry,
    sber_category: str | None = None,
) -> BaseEntity | None:
    """Create a throw-away Sber entity from an HA registry entry.

    Thin wrapper over :func:`build_probe_entity_data` +
    :func:`create_sber_entity` for the inspect-only call sites (Options
    Flow preview / type-override step, wizard link suggestions).

    Args:
        entry: HA entity-registry entry to promote.
        sber_category: Optional explicit category override; when ``None``
            the category is auto-detected from domain/device_class.

    Returns:
        The probe entity, or ``None`` when no Sber category matches.
    """
    return create_sber_entity(entry.entity_id, build_probe_entity_data(entry), sber_category)
