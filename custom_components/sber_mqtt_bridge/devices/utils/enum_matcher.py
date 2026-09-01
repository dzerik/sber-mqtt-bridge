"""Matching of Home Assistant labels onto Sber ENUM vocabularies.

Sber ENUM features accept a **closed** set of values, documented on the
function's own page and mirrored in
:data:`~custom_components.sber_mqtt_bridge._generated.reference_values.FEATURE_ENUM_VALUES`.
Home Assistant, in contrast, hands out free-form human labels: a TV
reports its inputs as ``"HDMI 1"`` / ``"Станция"``, a vacuum its modes as
``"Spot Clean"``.  Publishing such a label verbatim gives the cloud a
value it cannot route — the device looks accepted but the control is dead
(issue #61 audit).

The matcher bridges the two by comparing *normalized* tokens: case,
spaces, hyphens and underscores are meaningless noise on the HA side, so
``"HDMI 1"``, ``"hdmi-1"`` and ``"HDMI_1"`` all resolve to the documented
``hdmi1``.  A label that resolves to nothing is dropped rather than
guessed: an undeclared source is merely missing, an invented one is
broken.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping

_LOGGER = logging.getLogger(__name__)

_NOISE_CHARS = frozenset({" ", "-", "_", "	"})
"""Characters that carry no meaning when comparing an HA label to a Sber value."""


def normalize_enum_token(name: str) -> str:
    """Reduce a label to its comparable token.

    Args:
        name: Raw label, from either side of the bridge.

    Returns:
        Case-folded label with spaces, hyphens and underscores removed
        (``"HDMI 1"`` → ``"hdmi1"``, ``"random_route"`` → ``"randomroute"``).
    """
    return "".join(ch for ch in name.casefold() if ch not in _NOISE_CHARS)


def build_enum_index(vocabulary: Iterable[str]) -> dict[str, str]:
    """Index a Sber vocabulary by the normalized form of each value.

    Args:
        vocabulary: The documented values of one ENUM feature.

    Returns:
        Mapping ``normalized token → documented Sber value``.
    """
    return {normalize_enum_token(value): value for value in vocabulary}


def match_enum_value(
    ha_label: str,
    vocabulary: Iterable[str],
    *,
    synonyms: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve one HA label to the Sber value it denotes.

    Args:
        ha_label: Label as Home Assistant reports it.
        vocabulary: Documented Sber values for the target feature.
        synonyms: Optional ``normalized HA token → Sber value`` table for
            labels that mean the same thing under a different word
            (``"edge"`` for ``perimeter``).  Consulted only after the
            direct match fails, and its values are still checked against
            ``vocabulary`` so a stale synonym can never smuggle an
            undocumented value out.

    Returns:
        The documented Sber value, or ``None`` when the label denotes
        nothing Sber knows.
    """
    values = set(vocabulary)
    if ha_label in values:
        return ha_label
    token = normalize_enum_token(ha_label)
    if not token:
        return None
    index = build_enum_index(values)
    if token in index:
        return index[token]
    if synonyms:
        candidate = synonyms.get(token)
        if candidate in values:
            return candidate
    return None


def map_ha_values(
    ha_labels: Iterable[str],
    vocabulary: Iterable[str],
    *,
    synonyms: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Map a list of HA labels onto the Sber vocabulary, dropping the rest.

    Order of ``ha_labels`` is preserved, which keeps the resulting
    ``allowed_values`` list — and therefore the capability digest behind
    ``model.id`` — stable for a given device.  When two labels resolve to
    the same Sber value the first one wins: the cloud has one slot for
    that value, and silently rebinding it to a later label would make the
    published state and the accepted command disagree.

    Args:
        ha_labels: Labels as Home Assistant reports them.
        vocabulary: Documented Sber values for the target feature.
        synonyms: Optional synonym table, see :func:`match_enum_value`.

    Returns:
        Ordered mapping ``HA label → Sber value`` containing only the
        labels that resolved.  Empty when none did — the caller must then
        declare no feature at all rather than an empty one.
    """
    if isinstance(ha_labels, str):
        # A malformed integration handing us a bare string instead of a
        # list would otherwise be iterated character by character, and a
        # stray "-" is a documented ``source`` value.
        _LOGGER.debug("Expected a list of HA labels, got the string %r — ignoring", ha_labels)
        return {}
    mapped: dict[str, str] = {}
    taken: set[str] = set()
    for label in ha_labels:
        if not isinstance(label, str) or label in mapped:
            continue
        sber_value = match_enum_value(label, vocabulary, synonyms=synonyms)
        if sber_value is None:
            _LOGGER.debug("HA label %r matches no documented Sber value, skipping", label)
            continue
        if sber_value in taken:
            _LOGGER.debug("HA label %r duplicates Sber value %r, skipping", label, sber_value)
            continue
        taken.add(sber_value)
        mapped[label] = sber_value
    return mapped


def invert_value_map(ha_to_sber: Mapping[str, str]) -> dict[str, str]:
    """Build the command-direction lookup from a publish-direction map.

    Args:
        ha_to_sber: Mapping produced by :func:`map_ha_values`.

    Returns:
        Mapping ``Sber value → HA label``.
    """
    return {sber: ha for ha, sber in ha_to_sber.items()}
