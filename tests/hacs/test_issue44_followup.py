"""Regression tests for the issue #44 follow-up report (multi-channel Zigbee lamp).

The reporter's chandelier (``zhimei_v2``, HA model_id ``0x8CB0 / 4``)
exposes two HA light entities backed by one HA device:

* ``light.svet_v_zale_main_light`` — ``supported_color_modes: ["color_temp"]``
* ``light.svet_v_zale_second_light`` — ``supported_color_modes: ["onoff"]``

Two independent defects fell out of that:

1. **Undeclared states.**  The on/off-only channel advertised
   ``[online, on_off]`` but published ``light_brightness`` (the HA
   ``brightness`` attribute is absent, so the linear converter floors it
   to the Sber minimum ``100``, which is non-zero and slipped past
   ``LightEntity``'s ``!= 0`` guard) plus ``light_mode``.  Our own
   :mod:`~custom_components.sber_mqtt_bridge.schema_validator` flagged it
   as ``not_declared``.  Fixed once for all 28 categories by
   :meth:`BaseEntity._filter_undeclared_states`.

2. **Model collision.**  ``model.id`` was ``{ha_model_id}_{category}``,
   so both channels claimed the id ``0x8CB0 / 4_light``.  Sber cloud
   keeps one model per id and merged the interfaces, painting the on/off
   channel as a colour lamp whose controls hung.  Fixed by
   :meth:`BaseEntity._capability_digest`.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from custom_components.sber_mqtt_bridge._generated.obligatory_features import (
    CATEGORY_OBLIGATORY_FEATURES,
)
from custom_components.sber_mqtt_bridge.devices.base_entity import (
    ALWAYS_PUBLISHED_FEATURES,
    BaseEntity,
)
from custom_components.sber_mqtt_bridge.devices.light import LightEntity
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.sber_entity_map import CATEGORY_DOMAIN_MAP
from custom_components.sber_mqtt_bridge.schema_validator import validate_publish

_BASE_ENTITY_LOGGER = "custom_components.sber_mqtt_bridge.devices.base_entity"

REPO_ROOT = Path(__file__).resolve().parents[2]

CHANDELIER_MODEL_ID = "0x8CB0 / 4"
"""HA ``model_id`` shared by both channels of the reporter's chandelier."""


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _light(
    entity_id: str,
    color_modes: list[str],
    *,
    device_id: str = "zhimei-device",
    model_id: str = CHANDELIER_MODEL_ID,
    state: str = "on",
    extra_attrs: dict[str, Any] | None = None,
) -> LightEntity:
    """Build a filled :class:`LightEntity` linked to a HA device.

    Args:
        entity_id: HA entity id of the light channel.
        color_modes: Value of the HA ``supported_color_modes`` attribute.
        device_id: HA device registry id both channels share.
        model_id: HA device registry ``model_id``.
        state: HA state string (``"on"`` / ``"off"``).
        extra_attrs: Additional HA attributes merged into the state.

    Returns:
        A ``LightEntity`` ready for ``to_sber_state`` / ``to_sber_current_state``.
    """
    entity = LightEntity({"entity_id": entity_id, "device_id": device_id, "original_name": entity_id, "name": None})
    entity.link_device(
        {
            "id": device_id,
            "name": "Свет в зале",
            "model_id": model_id,
            "manufacturer": "zhimei",
            "model": "zhimei_v2",
            "area_id": "zal",
        }
    )
    attrs: dict[str, Any] = {"supported_color_modes": color_modes, "color_mode": color_modes[0]}
    if extra_attrs:
        attrs.update(extra_attrs)
    entity.fill_by_ha_state({"state": state, "attributes": attrs})
    return entity


def _relay(
    entity_id: str,
    *,
    device_id: str = "sonoff-device",
    model_id: str = "SONOFF",
    extra_features: list[str] | None = None,
    removed_features: list[str] | None = None,
) -> RelayEntity:
    """Build a filled :class:`RelayEntity` with optional feature overrides.

    ``RelayEntity`` is the cleanest probe for override behaviour: it
    advertises no ``allowed_values`` at all, so any change in its
    ``model.id`` can only come from the feature list.

    Args:
        entity_id: HA entity id of the switch.
        device_id: HA device registry id.
        model_id: HA device registry ``model_id``.
        extra_features: Value for ``sber_features_add`` override.
        removed_features: Value for ``sber_features_remove`` override.

    Returns:
        A ``RelayEntity`` ready for ``to_sber_state``.
    """
    entity = RelayEntity({"entity_id": entity_id, "device_id": device_id, "original_name": entity_id, "name": None})
    entity.link_device(
        {
            "id": device_id,
            "name": "Реле",
            "model_id": model_id,
            "manufacturer": "SONOFF",
            "model": "MINI",
            "area_id": "hall",
        }
    )
    entity.fill_by_ha_state({"state": "on", "attributes": {}})
    if extra_features:
        entity.extra_features = extra_features
    if removed_features:
        entity.removed_features = removed_features
    return entity


def _published_keys(entity: BaseEntity) -> list[str]:
    """Return the feature keys of a device's published state payload."""
    payload = entity.to_sber_current_state()[entity.entity_id]["states"]
    return [str(state["key"]) for state in payload]


def _model_id(entity: BaseEntity) -> str:
    """Return the ``model.id`` a device would advertise to Sber."""
    return entity.to_sber_state()["model"]["id"]


# ---------------------------------------------------------------------------
#  The reporter's exact scenario
# ---------------------------------------------------------------------------


class TestMultiChannelChandelier:
    """End-to-end reproduction of issue #44 with the reporter's two channels."""

    def test_channels_declare_different_features(self) -> None:
        """Precondition: the two channels really do differ in capability."""
        main = _light("light.svet_v_zale_main_light", ["color_temp"])
        second = _light("light.svet_v_zale_second_light", ["onoff"])
        assert main.get_final_features_list() == ["online", "on_off", "light_brightness", "light_colour_temp"]
        assert second.get_final_features_list() == ["online", "on_off"]

    def test_channels_get_distinct_model_ids(self) -> None:
        """Different capabilities under one HA model_id must not share a Sber model."""
        main = _light("light.svet_v_zale_main_light", ["color_temp"])
        second = _light("light.svet_v_zale_second_light", ["onoff"])
        assert _model_id(main) != _model_id(second)

    def test_model_ids_keep_the_ha_model_and_category_prefix(self) -> None:
        """The digest is a suffix — the human-readable prefix survives."""
        second = _light("light.svet_v_zale_second_light", ["onoff"])
        model_id = _model_id(second)
        assert model_id.startswith(f"{CHANDELIER_MODEL_ID}_light_")
        digest = model_id.rsplit("_", 1)[1]
        assert len(digest) == 8
        assert all(char in "0123456789abcdef" for char in digest)

    def test_onoff_channel_publishes_only_declared_features(self) -> None:
        """The on/off channel must not leak brightness or light_mode."""
        second = _light("light.svet_v_zale_second_light", ["onoff"])
        keys = _published_keys(second)
        assert "light_brightness" not in keys
        assert "light_mode" not in keys
        assert keys == ["online", "on_off"]

    def test_onoff_channel_stays_clean_when_off(self) -> None:
        """Boundary: the 'off' branch of LightEntity must stay clean too."""
        second = _light("light.svet_v_zale_second_light", ["onoff"], state="off")
        assert _published_keys(second) == ["online", "on_off"]

    def test_color_temp_channel_drops_undeclared_light_mode(self) -> None:
        """A color_temp-only lamp declares no ``light_mode`` — nor may it publish one.

        ``light_mode`` is only declared alongside ``light_colour``; the
        reporter's dimmable channel has neither.
        """
        main = _light("light.svet_v_zale_main_light", ["color_temp"])
        assert "light_mode" not in main.get_final_features_list()
        assert "light_mode" not in _published_keys(main)

    def test_color_temp_channel_still_publishes_its_own_features(self) -> None:
        """The filter must not eat legitimately declared states."""
        main = _light(
            "light.svet_v_zale_main_light",
            ["color_temp"],
            extra_attrs={"brightness": 128, "color_temp_kelvin": 3000},
        )
        keys = _published_keys(main)
        assert "light_brightness" in keys
        assert "light_colour_temp" in keys

    def test_colour_lamp_keeps_light_mode(self) -> None:
        """A lamp that *does* declare light_colour keeps publishing light_mode."""
        colour = _light(
            "light.svet_v_zale_rgb",
            ["hs"],
            extra_attrs={"brightness": 200, "hs_color": [120, 50]},
        )
        assert "light_mode" in colour.get_final_features_list()
        keys = _published_keys(colour)
        assert "light_mode" in keys
        assert "light_colour" in keys

    @pytest.mark.parametrize(
        ("entity_id", "color_modes"),
        [
            ("light.svet_v_zale_main_light", ["color_temp"]),
            ("light.svet_v_zale_second_light", ["onoff"]),
        ],
    )
    def test_schema_validator_reports_no_not_declared(self, entity_id: str, color_modes: list[str]) -> None:
        """The real validator must find nothing to complain about."""
        entity = _light(entity_id, color_modes)
        issues = validate_publish(
            entity_id=entity.entity_id,
            category=entity.category,
            states=entity.to_sber_current_state()[entity.entity_id]["states"],
            declared_features=entity.get_final_features_list(),
        )
        assert [issue for issue in issues if issue.type == "not_declared"] == []
        assert issues == [], [issue.description for issue in issues]


# ---------------------------------------------------------------------------
#  Capability digest
# ---------------------------------------------------------------------------


class TestCapabilityDigest:
    """``model.id`` identifies a *capability set*, not a piece of hardware."""

    def test_identical_lamps_on_different_devices_share_a_model(self) -> None:
        """Two same-capability lamps must still reuse one Sber model."""
        left = _light("light.left", ["color_temp"], device_id="dev-left", model_id="TRADFRI")
        right = _light("light.right", ["color_temp"], device_id="dev-right", model_id="TRADFRI")
        assert _model_id(left) == _model_id(right)

    def test_same_capabilities_different_hardware_still_differ(self) -> None:
        """The HA model_id prefix keeps distinct hardware distinguishable."""
        ikea = _light("light.a", ["onoff"], device_id="dev-a", model_id="TRADFRI")
        zhimei = _light("light.b", ["onoff"], device_id="dev-b", model_id=CHANDELIER_MODEL_ID)
        assert _model_id(ikea) != _model_id(zhimei)

    def test_digest_is_stable_across_calls(self) -> None:
        """Repeated serialization of one entity yields one model id."""
        lamp = _light("light.a", ["color_temp"])
        assert _model_id(lamp) == _model_id(lamp) == _model_id(lamp)

    def test_digest_ignores_feature_order(self) -> None:
        """Feature declaration order must not change the model identity."""
        first = BaseEntity._capability_digest(["online", "on_off", "light_brightness"], {})
        second = BaseEntity._capability_digest(["light_brightness", "online", "on_off"], {})
        assert first == second

    def test_digest_ignores_allowed_values_key_order(self) -> None:
        """Dict insertion order must not change the model identity."""
        forward = {
            "light_brightness": {"type": "INTEGER", "integer_values": {"min": "100", "max": "900", "step": "1"}},
            "light_colour": {"type": "COLOUR"},
        }
        backward = {
            "light_colour": {"type": "COLOUR"},
            "light_brightness": {"integer_values": {"step": "1", "max": "900", "min": "100"}, "type": "INTEGER"},
        }
        features = ["online", "on_off", "light_brightness", "light_colour"]
        assert BaseEntity._capability_digest(features, forward) == BaseEntity._capability_digest(features, backward)

    def test_digest_ignores_duplicate_features(self) -> None:
        """A duplicated feature name is not a different capability set."""
        assert BaseEntity._capability_digest(["online", "on_off"], {}) == BaseEntity._capability_digest(
            ["online", "on_off", "on_off"], {}
        )

    def test_digest_separates_features_from_allowed_values(self) -> None:
        """Different feature sets must never collide."""
        assert BaseEntity._capability_digest(["online"], {}) != BaseEntity._capability_digest(["on_off"], {})

    def test_digest_reacts_to_allowed_values_only(self) -> None:
        """Same features, different limits → different model."""
        features = ["online", "on_off", "hvac_temp_set"]
        cold = {"hvac_temp_set": {"type": "INTEGER", "integer_values": {"min": "5", "max": "30", "step": "1"}}}
        hot = {"hvac_temp_set": {"type": "INTEGER", "integer_values": {"min": "5", "max": "35", "step": "1"}}}
        assert BaseEntity._capability_digest(features, cold) != BaseEntity._capability_digest(features, hot)

    def test_digest_reacts_to_non_ascii_allowed_values(self) -> None:
        """Cyrillic enum values (Sber's own docs use them) still discriminate."""
        features = ["online", "source"]
        first = {"source": {"type": "ENUM", "enum_values": {"values": ["Телевизор"]}}}
        second = {"source": {"type": "ENUM", "enum_values": {"values": ["Приставка"]}}}
        assert BaseEntity._capability_digest(features, first) != BaseEntity._capability_digest(features, second)

    def test_digest_survives_a_process_restart(self) -> None:
        """The digest must not depend on ``PYTHONHASHSEED``.

        ``hash()`` is randomized per process, so a digest built on it
        would give the same device a different ``model.id`` after every
        Home Assistant restart and spam Sber with new models.
        """
        script = (
            "from custom_components.sber_mqtt_bridge.devices.base_entity import BaseEntity;"
            "print(BaseEntity._capability_digest("
            "['online', 'on_off', 'light_brightness'],"
            "{'light_brightness': {'type': 'INTEGER', 'integer_values': {'min': '100', 'max': '900'}}}))"
        )
        digests = {
            subprocess.run(  # noqa: S603 — fixed argv, no shell
                [sys.executable, "-c", script],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
                env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": seed, "HOME": str(REPO_ROOT)},
            ).stdout.strip()
            for seed in ("0", "12345")
        }
        assert len(digests) == 1, f"digest varies with PYTHONHASHSEED: {digests}"
        assert digests == {
            BaseEntity._capability_digest(
                ["online", "on_off", "light_brightness"],
                {"light_brightness": {"type": "INTEGER", "integer_values": {"min": "100", "max": "900"}}},
            )
        }


class TestCapabilityDigestFollowsUserOverrides:
    """``model.id`` must be keyed on the **final** feature list.

    Feature overrides (``sber_features_add`` / ``sber_features_remove``,
    see :mod:`~custom_components.sber_mqtt_bridge.custom_capabilities`)
    are a first-class user-facing feature, so two entities of the same
    hardware model can end up advertising different feature lists
    without any difference in their HA capabilities.  If the digest were
    computed from :meth:`BaseEntity._create_features_list` instead of
    :meth:`BaseEntity.get_final_features_list`, those entities would
    collapse onto one ``model.id`` and Sber cloud would merge their
    interfaces — exactly the issue #44 breakage, just reached through
    the override branch instead of the ``supported_color_modes`` branch.

    All probes below deliberately use features that carry **no**
    ``allowed_values`` (``on_off`` and relay ``power``), so the digest can
    only differ through the feature list itself: an override that also
    moved an ``allowed_values`` entry would mask the defect.
    """

    def test_removed_feature_changes_the_model_id(self) -> None:
        """``sber_features_remove`` must yield a different Sber model."""
        plain = _relay("switch.plain")
        stripped = _relay("switch.stripped", removed_features=["on_off"])
        assert plain.create_allowed_values_list() == stripped.create_allowed_values_list() == {}
        assert plain.get_final_features_list() != stripped.get_final_features_list()
        assert _model_id(plain) != _model_id(stripped)

    def test_added_feature_changes_the_model_id(self) -> None:
        """``sber_features_add`` must yield a different Sber model."""
        plain = _relay("switch.plain")
        metered = _relay("switch.metered", extra_features=["power"])
        assert plain.create_allowed_values_list() == metered.create_allowed_values_list() == {}
        assert _model_id(plain) != _model_id(metered)

    def test_three_override_variants_get_three_models(self) -> None:
        """The reporter's failure mode, reached through overrides."""
        variants = [
            _relay("switch.a"),
            _relay("switch.b", extra_features=["power"]),
            _relay("switch.c", removed_features=["on_off"]),
        ]
        assert len({tuple(v.get_final_features_list()) for v in variants}) == 3
        assert len({_model_id(v) for v in variants}) == 3

    def test_removed_feature_changes_the_model_id_for_the_reporters_class(self) -> None:
        """Same binding on ``LightEntity`` itself, not just on a relay."""
        plain = _light("light.a", ["onoff"], device_id="dev-a")
        stripped = _light("light.b", ["onoff"], device_id="dev-b")
        stripped.removed_features = ["on_off"]
        assert _model_id(plain) != _model_id(stripped)

    def test_identical_overrides_still_share_one_model(self) -> None:
        """Negative control: the digest must not turn into a per-entity id."""
        left = _relay("switch.left", device_id="dev-left", extra_features=["power"])
        right = _relay("switch.right", device_id="dev-right", extra_features=["power"])
        assert _model_id(left) == _model_id(right)


class TestModelIdStability:
    """``model.id`` reacts to capabilities only — never to plain values.

    Config publish happens far less often than state publish, so a
    ``model.id`` that drifted with the current brightness/temperature
    would register a new Sber model on every reconnect.
    """

    def test_light_model_id_survives_value_changes(self) -> None:
        """on → off and brightness 1 → 255 keep one model (boundary values)."""
        lamp = _light("light.dim", ["brightness"], extra_attrs={"brightness": 1})
        first = _model_id(lamp)
        lamp.fill_by_ha_state(
            {"state": "on", "attributes": {"supported_color_modes": ["brightness"], "brightness": 255}}
        )
        assert _model_id(lamp) == first
        lamp.fill_by_ha_state({"state": "off", "attributes": {"supported_color_modes": ["brightness"]}})
        assert _model_id(lamp) == first

    def test_relay_model_id_survives_toggling(self) -> None:
        """A plain on/off device keeps one model across toggles."""
        relay = _relay("switch.toggle")
        first = _model_id(relay)
        relay.fill_by_ha_state({"state": "off", "attributes": {}})
        assert _model_id(relay) == first

    def test_capability_loss_does_change_the_model_id(self) -> None:
        """Documented trade-off: fewer capabilities means a different model.

        A light that stops advertising ``brightness`` genuinely
        advertises a smaller feature list, so it must not keep claiming
        the dimmable model — that is the whole point of the fix.  The
        practical consequence (an ``unavailable`` entity registers a
        stripped-down model until the next config republish) is tracked
        as a known limitation of capability-keyed model ids.
        """
        lamp = _light("light.dim", ["brightness"], extra_attrs={"brightness": 128})
        rich = _model_id(lamp)
        lamp.fill_by_ha_state({"state": "unavailable", "attributes": {}})
        assert _model_id(lamp) != rich


# ---------------------------------------------------------------------------
#  Declared-feature publish filter — protocol-wide anti-regression
# ---------------------------------------------------------------------------


_PROBE_ATTRS: dict[str, Any] = {
    # light
    "supported_color_modes": ["hs", "color_temp"],
    "color_mode": "hs",
    "brightness": 128,
    "hs_color": [120, 50],
    "color_temp_kelvin": 3000,
    # climate / water_heater
    "current_temperature": 21.5,
    "temperature": 23,
    "min_temp": 5,
    "max_temp": 35,
    "target_temp_step": 1,
    "hvac_modes": ["off", "cool", "heat", "auto"],
    "hvac_action": "cooling",
    "fan_mode": "auto",
    "fan_modes": ["auto", "low", "high"],
    "swing_mode": "off",
    "swing_modes": ["off", "vertical"],
    "preset_mode": "boost",
    "preset_modes": ["boost", "sleep"],
    "operation_list": ["eco", "performance"],
    # humidifier / air quality
    "humidity": 55,
    "current_humidity": 48,
    "min_humidity": 30,
    "max_humidity": 80,
    "available_modes": ["normal", "sleep"],
    "mode": "normal",
    # fan / vacuum
    "percentage": 40,
    "percentage_step": 10,
    "oscillating": False,
    "fan_speed": "turbo",
    "fan_speed_list": ["quiet", "standard", "turbo"],
    # cover / valve
    "current_position": 60,
    "current_tilt_position": 30,
    # media_player
    "volume_level": 0.3,
    "is_volume_muted": False,
    "source": "HDMI 1",
    "source_list": ["HDMI 1", "TV"],
    # sensors
    "battery_level": 77,
    "signal_strength": -55,
    "sensitivity": "high",
    "carbon_dioxide": 600,
    "pm25": 12,
}
"""Kitchen-sink HA attributes so every probe entity declares as much as it can."""


def _probe_entity(category: str) -> BaseEntity:
    """Build a maximally-capable probe entity for a Sber category.

    Args:
        category: Key of :data:`CATEGORY_DOMAIN_MAP`.

    Returns:
        A filled entity of that category.
    """
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
    entity.fill_by_ha_state({"state": "on", "attributes": dict(_PROBE_ATTRS)})
    return entity


class TestDeclaredFeatureFilterAcrossCategories:
    """No Sber category may publish a state key it did not advertise."""

    @pytest.mark.parametrize("category", sorted(CATEGORY_DOMAIN_MAP))
    def test_published_keys_are_declared(self, category: str) -> None:
        declared = set(_probe_entity(category).get_final_features_list()) | ALWAYS_PUBLISHED_FEATURES
        undeclared = [key for key in _published_keys(_probe_entity(category)) if key not in declared]
        assert undeclared == [], f"{category} publishes undeclared keys {undeclared}"

    @pytest.mark.parametrize("category", sorted(CATEGORY_DOMAIN_MAP))
    def test_obligatory_features_survive_the_filter(self, category: str) -> None:
        """The filter must never strip a feature Sber declares obligatory.

        A dropped obligatory feature would mean ``_create_features_list``
        forgot to advertise it — Sber then silently discards the device.
        """
        entity = _probe_entity(category)
        obligatory = CATEGORY_OBLIGATORY_FEATURES.get(entity.category, frozenset())
        missing = sorted(obligatory - set(_published_keys(entity)))
        assert missing == [], f"{category}: obligatory features {missing} absent from publish"

    @pytest.mark.parametrize("category", sorted(CATEGORY_DOMAIN_MAP))
    def test_online_is_always_declared(self, category: str) -> None:
        """``online`` is obligatory everywhere, so the bypass is a safety net only."""
        assert "online" in CATEGORY_OBLIGATORY_FEATURES.get(_probe_entity(category).category, frozenset())
        assert "online" in _probe_entity(category).get_final_features_list()

    @pytest.mark.parametrize("category", sorted(CATEGORY_DOMAIN_MAP))
    def test_schema_validator_is_clean_for_every_category(self, category: str) -> None:
        """The real validator must report no ``not_declared`` for any category."""
        entity = _probe_entity(category)
        issues = validate_publish(
            entity_id=entity.entity_id,
            category=entity.category,
            states=entity.to_sber_current_state()[entity.entity_id]["states"],
            declared_features=entity.get_final_features_list(),
        )
        assert [issue.key for issue in issues if issue.type == "not_declared"] == []


class TestDeclaredFeatureFilterSemantics:
    """Edge cases and negative cases of :meth:`BaseEntity._filter_undeclared_states`."""

    def test_user_removed_feature_stops_being_published(self) -> None:
        """``sber_features_remove`` must silence the corresponding state."""
        lamp = _light("light.dimmable", ["brightness"], extra_attrs={"brightness": 200})
        assert "light_brightness" in _published_keys(lamp)
        lamp.removed_features = ["light_brightness"]
        assert "light_brightness" not in _published_keys(lamp)
        assert "on_off" in _published_keys(lamp)

    def test_user_added_feature_lets_its_state_through(self) -> None:
        """The filter reads the *final* list, so ``sber_features_add`` re-opens a key."""
        lamp = _light("light.plain", ["onoff"])
        lamp.extra_features = ["light_brightness"]
        assert "light_brightness" in _published_keys(lamp)

    def test_online_survives_even_when_the_user_removes_it(self) -> None:
        """Removing the obligatory ``online`` would make Sber drop the device."""
        lamp = _light("light.plain", ["onoff"])
        lamp.removed_features = ["online", "on_off"]
        assert lamp.get_final_features_list() == []
        assert _published_keys(lamp) == ["online"]
        assert set(ALWAYS_PUBLISHED_FEATURES) == {"online"}

    def test_filtering_is_reflected_in_change_detection(self) -> None:
        """``has_significant_change`` diffs the filtered payload, not the raw one."""
        lamp = _light("light.plain", ["onoff"])
        lamp.mark_state_published()
        assert lamp.has_significant_change() is False
        lamp.fill_by_ha_state({"state": "off", "attributes": {"supported_color_modes": ["onoff"]}})
        assert lamp.has_significant_change() is True

    def test_raw_hook_output_is_not_leaked_by_reference(self) -> None:
        """A second publish must produce the same filtered payload, not a shrinking one."""
        lamp = _light("light.plain", ["onoff"])
        assert _published_keys(lamp) == _published_keys(lamp)

    def test_dropped_key_is_logged_once_at_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        """DEBUG visibility without per-publish log spam."""
        lamp = _light("light.plain", ["onoff"])
        with caplog.at_level(logging.DEBUG, logger=_BASE_ENTITY_LOGGER):
            lamp.to_sber_current_state()
            lamp.to_sber_current_state()
            lamp.to_sber_current_state()
        brightness_records = [r for r in caplog.records if "light_brightness" in r.getMessage()]
        assert len(brightness_records) == 1
        assert brightness_records[0].levelno == logging.DEBUG
        assert "light.plain" in brightness_records[0].getMessage()

    def test_nothing_is_logged_when_nothing_is_dropped(self, caplog: pytest.LogCaptureFixture) -> None:
        """Negative case: a clean device must stay silent."""
        lamp = _light("light.rgb", ["hs"], extra_attrs={"brightness": 200, "hs_color": [10, 90]})
        with caplog.at_level(logging.DEBUG, logger=_BASE_ENTITY_LOGGER):
            keys = _published_keys(lamp)
        assert set(keys) <= set(lamp.get_final_features_list())
        assert [r for r in caplog.records if "dropping state" in r.getMessage()] == []

    def test_malformed_payload_is_passed_through(self) -> None:
        """Edge case: a hook returning a non-states block must not explode."""
        lamp = _light("light.plain", ["onoff"])
        payload = {"light.plain": {"error": "boom"}, "other": None}
        assert lamp._filter_undeclared_states(payload) == payload

    def test_states_without_a_key_are_kept(self) -> None:
        """Edge case: a malformed state entry is not silently discarded."""
        lamp = _light("light.plain", ["onoff"])
        payload: dict[str, Any] = {"light.plain": {"states": [{"value": {"type": "BOOL"}}, "junk"]}}
        assert lamp._filter_undeclared_states(payload)["light.plain"]["states"] == [
            {"value": {"type": "BOOL"}},
            "junk",
        ]


# ---------------------------------------------------------------------------
#  Subclass contract: the publish wrapper must stay in BaseEntity
# ---------------------------------------------------------------------------


def _classes_below_base(cls: type) -> list[type]:
    """Return the MRO entries of a device class up to (excluding) BaseEntity.

    Args:
        cls: A concrete device class.

    Returns:
        Every class in ``cls.__mro__`` that sits below ``BaseEntity``.
    """
    below: list[type] = []
    for klass in cls.__mro__:
        if klass is BaseEntity:
            break
        below.append(klass)
    return below


class TestSubclassContract:
    """``to_sber_current_state`` is the wrapper; subclasses extend the hook.

    :meth:`BaseEntity.to_sber_current_state` applies
    :meth:`BaseEntity._filter_undeclared_states`.  A device class that
    overrode the wrapper (as every class did before this fix, and as the
    contributing guide used to instruct) would silently opt out of the
    filter and resurrect issue #44 for its own category — with no other
    test failing.  These tests pin the contract itself.
    """

    @pytest.mark.parametrize("category", sorted(CATEGORY_DOMAIN_MAP))
    def test_no_device_class_overrides_the_publish_wrapper(self, category: str) -> None:
        """Only ``BaseEntity`` may define ``to_sber_current_state``."""
        offenders = [
            klass.__qualname__
            for klass in _classes_below_base(CATEGORY_DOMAIN_MAP[category].cls)
            if "to_sber_current_state" in vars(klass)
        ]
        assert offenders == [], (
            f"{offenders} override to_sber_current_state and therefore bypass "
            "_filter_undeclared_states; implement _build_current_state instead"
        )

    @pytest.mark.parametrize("category", sorted(CATEGORY_DOMAIN_MAP))
    def test_every_device_class_implements_the_hook(self, category: str) -> None:
        """The state builder must be a real implementation, not the abstract stub."""
        cls = CATEGORY_DOMAIN_MAP[category].cls
        assert any("_build_current_state" in vars(klass) for klass in _classes_below_base(cls))
        assert getattr(cls._build_current_state, "__isabstractmethod__", False) is False

    @pytest.mark.parametrize("category", sorted(CATEGORY_DOMAIN_MAP))
    def test_the_wrapper_is_the_one_that_filters(self, category: str) -> None:
        """The hook still leaks undeclared keys; only the wrapper is clean."""
        entity = _probe_entity(category)
        declared = set(entity.get_final_features_list()) | ALWAYS_PUBLISHED_FEATURES
        published = {
            str(state["key"])
            for block in entity.to_sber_current_state().values()
            for state in block["states"]
            if isinstance(state, dict) and "key" in state
        }
        assert published <= declared
        assert entity.to_sber_current_state.__func__ is BaseEntity.to_sber_current_state

    def test_contributing_guide_points_at_the_hook(self) -> None:
        """Docs must not tell contributors to implement the wrapper."""
        text = (REPO_ROOT / "docs" / "contributing.md").read_text(encoding="utf-8")
        instructions = [line for line in text.splitlines() if line.startswith("- ") and "to_sber_current_state" in line]
        assert instructions == [], f"contributing.md still instructs implementing the wrapper: {instructions}"
        assert "_build_current_state" in text
