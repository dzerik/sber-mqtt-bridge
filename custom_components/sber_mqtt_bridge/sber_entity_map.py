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
from dataclasses import dataclass

from .devices.base_entity import BaseEntity
from .devices.climate import ClimateEntity
from .devices.curtain import CurtainEntity
from .devices.door_sensor import DoorSensorEntity
from .devices.gas_sensor import GasSensorEntity
from .devices.gate import GateEntity
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
from .devices.sensor_temp import SensorTempEntity
from .devices.smoke_sensor import SmokeSensorEntity
from .devices.socket_entity import SocketEntity
from .devices.tv import TvEntity
from .devices.vacuum_cleaner import VacuumCleanerEntity
from .devices.valve import ValveEntity
from .devices.water_leak_sensor import WaterLeakSensorEntity
from .devices.window_blind import WindowBlindEntity

_LOGGER = logging.getLogger(__name__)


# Categories available for user overrides in Options Flow
OVERRIDABLE_CATEGORIES: list[str] = [
    "light",
    "led_strip",
    "relay",
    "socket",
    "curtain",
    "window_blind",
    "gate",
    "hvac_ac",
    "hvac_radiator",
    "hvac_heater",
    "hvac_boiler",
    "hvac_underfloor_heating",
    "hvac_fan",
    "valve",
    "hvac_humidifier",
    "scenario_button",
    "hvac_air_purifier",
    "kettle",
    "tv",
    "vacuum_cleaner",
    "intercom",
]
"""Sber categories that users can select as type overrides."""


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
        cls: Entity class to instantiate for this category.  Serves as the
            single source of truth for both auto-detection (pick by domain)
            and user overrides (pick by explicit category name).
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
    """

    cls: type[BaseEntity]
    domains: tuple[str, ...]
    device_classes: tuple[str, ...] | None = None
    preferred_rank: int = 50
    fallback_when_no_device_class: bool = False

    def matches(self, domain: str, device_class: str | None) -> bool:
        """Return True if an HA entity of ``(domain, device_class)`` promotes here."""
        if domain not in self.domains:
            return False
        if self.device_classes is None:
            return True
        dc = device_class or ""
        if dc in self.device_classes:
            return True
        return self.fallback_when_no_device_class and dc == ""


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
        cls=GateEntity,
        domains=("cover",),
        device_classes=("gate", "garage_door", "garage", "door"),
        preferred_rank=3,
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


CATEGORY_GROUPS: tuple[tuple[str, str], ...] = (
    ("control", "Control"),
    ("sensors", "Sensors"),
    ("automations", "Automations"),
)
"""Ordered list of ``(group_id, label)`` for Step 1 grid grouping."""


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
