"""Custom YAML capabilities for Sber Smart Home MQTT Bridge.

Allows users to override Sber device properties per entity via
``configuration.yaml``:

.. code-block:: yaml

    sber_mqtt_bridge:
      entity_config:
        switch.kettle:
          sber_type: light        # override Sber category
          sber_name: "Чайник"     # override display name
          sber_room: "Кухня"      # set room

The parsed configuration is stored in ``hass.data[DOMAIN]["yaml_config"]``
and applied during entity loading in :class:`SberBridge`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class EntityCustomConfig:
    """Custom configuration for a single HA entity exported to Sber.

    Attributes:
        sber_type: Override Sber device category (e.g. ``"light"`` for a switch).
        sber_name: Override display name shown in Sber.
        sber_room: Override room/area name in Sber.
        sber_nicknames: Alternative voice names for Sber (e.g. ``["Свет кухня"]``).
        sber_groups: Device groups in Sber (e.g. ``["Свет", "Кухня"]``).
        sber_parent_id: Parent device entity_id for hub hierarchy.
        sber_partner_meta: Arbitrary key-value metadata passed as ``partner_meta`` to Sber.
        sber_features_add: Extra Sber features to add to the entity.
        sber_features_remove: Sber features to remove from the entity.
    """

    sber_type: str | None = None
    sber_name: str | None = None
    sber_room: str | None = None
    sber_nicknames: list[str] | None = None
    sber_groups: list[str] | None = None
    sber_parent_id: str | None = None
    sber_partner_meta: dict[str, str] | None = None
    sber_features_add: list[str] | None = None
    sber_features_remove: list[str] | None = None


@dataclass
class CustomConfig:
    """Container for all custom YAML entity configurations.

    Attributes:
        entity_configs: Mapping of entity_id to its custom config.
    """

    entity_configs: dict[str, EntityCustomConfig] = field(default_factory=dict)

    def get(self, entity_id: str) -> EntityCustomConfig | None:
        """Get custom config for a specific entity.

        Args:
            entity_id: HA entity identifier.

        Returns:
            EntityCustomConfig if found, None otherwise.
        """
        return self.entity_configs.get(entity_id)

    def has_override(self, entity_id: str) -> bool:
        """Check whether an entity has any custom configuration.

        Args:
            entity_id: HA entity identifier.

        Returns:
            True if custom config exists for this entity.
        """
        return entity_id in self.entity_configs


# ---------------------------------------------------------------------------
# YAML schema
# ---------------------------------------------------------------------------

ENTITY_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional("sber_type"): str,
        vol.Optional("sber_name"): str,
        vol.Optional("sber_room"): str,
        vol.Optional("sber_nicknames"): [str],
        vol.Optional("sber_groups"): [str],
        vol.Optional("sber_parent_id"): str,
        vol.Optional("sber_partner_meta"): {str: str},
        vol.Optional("sber_features_add"): [str],
        vol.Optional("sber_features_remove"): [str],
    }
)
"""Schema for a single entity's custom configuration."""

PLATFORM_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_config", default={}): {str: ENTITY_CONFIG_SCHEMA},
    },
    extra=vol.ALLOW_EXTRA,
)
"""Root schema for the ``sber_mqtt_bridge:`` YAML section."""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_yaml_config(yaml_data: dict[str, Any]) -> CustomConfig:
    """Parse the ``sber_mqtt_bridge`` YAML section into a CustomConfig.

    Args:
        yaml_data: Raw dict from ``configuration.yaml`` for the domain.

    Returns:
        Populated CustomConfig instance.
    """
    validated = PLATFORM_SCHEMA(yaml_data)
    entity_configs: dict[str, EntityCustomConfig] = {}

    for entity_id, raw_cfg in validated.get("entity_config", {}).items():
        cfg = EntityCustomConfig(
            sber_type=raw_cfg.get("sber_type"),
            sber_name=raw_cfg.get("sber_name"),
            sber_room=raw_cfg.get("sber_room"),
            sber_nicknames=raw_cfg.get("sber_nicknames"),
            sber_groups=raw_cfg.get("sber_groups"),
            sber_parent_id=raw_cfg.get("sber_parent_id"),
            sber_partner_meta=raw_cfg.get("sber_partner_meta"),
            sber_features_add=raw_cfg.get("sber_features_add"),
            sber_features_remove=raw_cfg.get("sber_features_remove"),
        )
        entity_configs[entity_id] = cfg
        _LOGGER.debug(
            "Custom config for %s: type=%s, name=%s, room=%s, nicknames=%s, groups=%s, parent_id=%s, partner_meta=%s",
            entity_id,
            cfg.sber_type,
            cfg.sber_name,
            cfg.sber_room,
            cfg.sber_nicknames,
            cfg.sber_groups,
            cfg.sber_parent_id,
            cfg.sber_partner_meta,
        )

    return CustomConfig(entity_configs=entity_configs)


def get_custom_config(hass: HomeAssistant) -> CustomConfig:
    """Retrieve the parsed custom config from hass.data.

    If no YAML configuration was provided, returns an empty CustomConfig.

    Args:
        hass: Home Assistant core instance.

    Returns:
        CustomConfig instance (possibly empty).
    """
    domain_data = hass.data.get(DOMAIN)
    if domain_data is None:
        return CustomConfig()
    return domain_data.get("yaml_config", CustomConfig())
